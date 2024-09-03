from aws_cdk import (
    aws_ec2 as ec2,
    aws_ecs as ecs,
    aws_ecs_patterns as ecs_patterns,
    aws_route53 as route53,
    aws_route53_targets as targets,
    aws_certificatemanager as acm,
    aws_iam as iam,
    Stack,
    Aws,
)
from constructs import Construct


class LinkedPaperWebInfraStack(Stack):

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # VPC 생성
        linked_paper_vpc = ec2.Vpc(self, "LinkedPaperVpc", max_azs=2, nat_gateways=1)

        # Fargate 클러스터 생성
        linked_paper_cluster = ecs.Cluster(
            self, "LinkedPaperCluster", vpc=linked_paper_vpc
        )

        # ECS Task 정의 생성 (Fargate)
        task_definition = ecs.FargateTaskDefinition(
            self,
            "LinkedPaperTaskDef",
            memory_limit_mib=1024,  # Task memory limit
            cpu=512,  # Task CPU limit
        )

        # ECS task 정의에 컨테이너 추가
        task_definition.add_container(
            "LinkedPaperContainer",
            image=ecs.ContainerImage.from_registry(
                f"{Aws.ACCOUNT_ID}.dkr.ecr.{Aws.REGION}.amazonaws.com/next_production_image:latest"
            ),
            environment={
                "NODE_ENV": "production",
            },
            cpu=256,
            memory_limit_mib=512,
            logging=ecs.LogDrivers.aws_logs(stream_prefix="LinkedPaper"),
            port_mappings=[ecs.PortMapping(container_port=3000, host_port=3000)],
        )

        # Fargate 서비스 생성
        next_was_fargate_service = ecs_patterns.ApplicationLoadBalancedFargateService(
            self,
            "LinkedPaperFargateService",
            cluster=linked_paper_cluster,
            task_definition=task_definition,
            public_load_balancer=True,
            desired_count=1,
        )

        # ECR 접근 권한 추가
        next_was_fargate_service.task_definition.add_to_execution_role_policy(
            iam.PolicyStatement(
                actions=[
                    "ecr:GetDownloadUrlForLayer",
                    "ecr:BatchGetImage",
                    "ecr:GetAuthorizationToken",
                ],
                resources=["*"],
            )
        )

        # Auto Scaling 설정
        scalable_target = next_was_fargate_service.service.auto_scale_task_count(
            min_capacity=1,  # 최소 컨테이너 개수
            max_capacity=2,  # 최대 컨테이너 개수
        )

        # 스케일링 정책 추가 (예: CPU 사용률에 따라 스케일링)
        scalable_target.scale_on_cpu_utilization(
            "CpuScaling",
            target_utilization_percent=70,  # 목표 CPU 사용률
        )

        # Route53 호스팅 영역 가져오기
        hosted_zone = route53.HostedZone.from_lookup(
            self, "LinkedPaperHostedZone", domain_name="linked-paper.com"
        )

        # ACM 인증서 생성
        linked_paper_certificate = acm.Certificate(
            self,
            "LinkedPaperCertificate",
            domain_name="linked-paper.com",
            validation=acm.CertificateValidation.from_dns(hosted_zone),
        )

        # ALB에 도메인 연결 (HTTPS용 리스너 설정)
        next_was_fargate_service.load_balancer.add_listener(
            "HttpsListener",
            port=443,
            certificates=[linked_paper_certificate],
            default_target_groups=[next_was_fargate_service.target_group],
        )

        # Route53 A 레코드 생성
        route53.ARecord(
            self,
            "LinkedPaperRecord",
            zone=hosted_zone,
            target=route53.RecordTarget.from_alias(
                targets.LoadBalancerTarget(next_was_fargate_service.load_balancer)
            ),
        )
