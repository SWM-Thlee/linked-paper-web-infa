from aws_cdk import Aws, CfnOutput, Duration, RemovalPolicy, Stack
from aws_cdk import aws_certificatemanager as acm
from aws_cdk import aws_cloudfront as cloudfront
from aws_cdk import aws_cloudfront_origins as origins
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_ecs as ecs
from aws_cdk import aws_ecs_patterns as ecs_patterns
from aws_cdk import aws_iam as iam
from aws_cdk import aws_route53 as route53
from aws_cdk import aws_route53_targets as targets
from aws_cdk import aws_s3 as s3
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

        scalable_target.scale_on_cpu_utilization(
            "CpuScaling",
            target_utilization_percent=100,  # 목표 CPU 사용률 90%
            scale_in_cooldown=Duration.seconds(30),  # 스케일 인 쿨다운 (30초)
            scale_out_cooldown=Duration.seconds(10),  # 스케일 아웃 쿨다운 (10초)
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

        # S3 정적 파일 버킷 생성
        static_files_bucket = s3.Bucket(
            self,
            "LinkedPaperStaticFilesBucket",
            removal_policy=RemovalPolicy.RETAIN,  # 삭제 방지
            auto_delete_objects=False,
        )

        # us-east-1에서 발급된 SSL 인증서 사용
        cloudfront_certificate = acm.Certificate.from_certificate_arn(
            self,
            "CloudFrontCertificate",
            certificate_arn="arn:aws:acm:us-east-1:058264275251:certificate/ab1b9c1f-8976-4ed7-8979-a0866a0d28b4",
        )

        # CloudFront 배포 생성 (S3를 오리진으로 사용)
        cloudfront_distribution = cloudfront.Distribution(
            self,
            "LinkedPaperDistribution",
            default_behavior={
                "origin": origins.S3Origin(static_files_bucket),
                "allowed_methods": cloudfront.AllowedMethods.ALLOW_GET_HEAD,
                "viewer_protocol_policy": cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
            },
            domain_names=["cdn.linked-paper.com"],  # CDN 도메인
            certificate=cloudfront_certificate,  # us-east-1에서 발급된 인증서 사용
        )

        # Route53에 A 레코드 생성 (cdn.linked-paper.com을 CloudFront로 연결)
        route53.ARecord(
            self,
            "CdnAliasRecord",
            zone=hosted_zone,
            target=route53.RecordTarget.from_alias(
                targets.CloudFrontTarget(cloudfront_distribution)
            ),
            record_name="cdn",  # cdn.linked-paper.com으로 사용
        )

        # CloudFront URL 출력
        CfnOutput(
            self,
            "CloudFrontUrl",
            value=f"https://{cloudfront_distribution.distribution_domain_name}",
            description="URL of the CloudFront distribution",
        )
