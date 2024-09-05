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
from aws_cdk import aws_elasticloadbalancingv2 as elbv2
from aws_cdk import CfnOutput
from constructs import Construct
from aws_cdk import Fn


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


class BackendInfraStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # VPC를 명시적 속성으로 가져오기
        linked_paper_vpc = ec2.Vpc.from_lookup(
            self, "ExistingVpc", vpc_id="vpc-058b5208a767d5d1c"
        )
        private_subnets = [
            ec2.SubnetSelection(
                subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS,
                availability_zones=[linked_paper_vpc.availability_zones[0]],
            ),
        ]

        # 보안 그룹 생성 (API 서버와 Search Service 간 통신을 허용하는 보안 그룹)
        api_security_group = ec2.SecurityGroup(
            self,
            "ApiSecurityGroup",
            vpc=linked_paper_vpc,
            allow_all_outbound=True,
        )

        search_service_security_group = ec2.SecurityGroup(
            self,
            "SearchServiceSecurityGroup",
            vpc=linked_paper_vpc,
            allow_all_outbound=True,
        )

        # API 서버가 Search Service의 포트에 접근할 수 있도록 보안 그룹 규칙 추가
        search_service_security_group.add_ingress_rule(
            peer=api_security_group,
            connection=ec2.Port.tcp(8000),  # Search Service의 포트 8000
        )

        # Fargate 클러스터 생성 (API 서버용)
        api_cluster = ecs.Cluster(self, "ApiServiceCluster", vpc=linked_paper_vpc)

        # ECS Task 정의 생성 (API 서버)
        api_task_definition = ecs.FargateTaskDefinition(
            self,
            "ApiServiceTaskDef",
            memory_limit_mib=2048,  # Task memory limit
            cpu=1024,  # Task CPU limit
        )

        # ECS Task 정의에 API 서버 컨테이너 추가
        api_task_definition.add_container(
            "ApiServiceContainer",
            image=ecs.ContainerImage.from_registry(
                f"{Aws.ACCOUNT_ID}.dkr.ecr.{Aws.REGION}.amazonaws.com/api_service_image:latest"
            ),
            environment={
                "NODE_ENV": "production",
                "SEARCH_SERVICE_URL": "http://search-service:8000",  # Search Service URL (서비스 디스커버리 사용 가능)
            },
            cpu=1024,
            memory_limit_mib=2048,
            logging=ecs.LogDrivers.aws_logs(stream_prefix="ApiService"),
            port_mappings=[ecs.PortMapping(container_port=8080)],
        )

        # API 서버 Fargate 서비스 생성 (Private Subnet에 배포)
        api_service = ecs_patterns.ApplicationLoadBalancedFargateService(
            self,
            "ApiServiceFargateService",
            cluster=api_cluster,
            task_definition=api_task_definition,
            public_load_balancer=True,  # Public ALB (외부에서 API 서버로 접근 가능)
            task_subnets=private_subnets[0],
            security_groups=[api_security_group],
        )

        # Search Service Fargate 클러스터 생성 (Private Subnet에 배포)
        search_cluster = ecs.Cluster(self, "SearchServiceCluster", vpc=linked_paper_vpc)

        # ECS Task 정의 생성 (Search Service)
        search_task_definition = ecs.FargateTaskDefinition(
            self,
            "SearchServiceTaskDef",
            memory_limit_mib=4096,  # Task memory limit
            cpu=2048,  # Task CPU limit
        )

        # Search Service의 ECS Task 정의에 컨테이너 추가
        search_task_definition.add_container(
            "SearchServiceContainer",
            image=ecs.ContainerImage.from_registry(
                f"{Aws.ACCOUNT_ID}.dkr.ecr.{Aws.REGION}.amazonaws.com/search_service_image:latest"
            ),
            environment={
                "NODE_ENV": "production",
            },
            cpu=2048,
            memory_limit_mib=4096,
            logging=ecs.LogDrivers.aws_logs(stream_prefix="SearchService"),
            port_mappings=[ecs.PortMapping(container_port=8000)],
        )

        # Search Service Fargate 서비스 생성 (Private Subnet에 배포)
        search_service = ecs_patterns.ApplicationLoadBalancedFargateService(
            self,
            "SearchServiceFargateService",
            cluster=search_cluster,
            task_definition=search_task_definition,
            public_load_balancer=False,  # Private ALB
            task_subnets=private_subnets[0],
            security_groups=[search_service_security_group],
        )

        # Auto Scaling 설정 (API 서버)
        api_scalable_target = api_service.service.auto_scale_task_count(
            min_capacity=1,
            max_capacity=2,
        )

        api_scalable_target.scale_on_cpu_utilization(
            "CpuScaling",
            target_utilization_percent=70,
        )

        # Auto Scaling 설정 (Search Service)
        search_scalable_target = search_service.service.auto_scale_task_count(
            min_capacity=1,
            max_capacity=2,
        )

        search_scalable_target.scale_on_cpu_utilization(
            "CpuScaling",
            target_utilization_percent=70,
        )

        # Output: API 서버의 Load Balancer DNS
        CfnOutput(
            self,
            "ApiServiceLoadBalancerDNS",
            value=api_service.load_balancer.load_balancer_dns_name,
        )
