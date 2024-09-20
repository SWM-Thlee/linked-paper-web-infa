from aws_cdk import Aws, CfnOutput, Duration, Fn, Stack
from aws_cdk import aws_applicationautoscaling as applicationautoscaling
from aws_cdk import aws_certificatemanager as acm
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_ecs as ecs
from aws_cdk import aws_ecs_patterns as ecs_patterns
from aws_cdk import aws_elasticloadbalancingv2 as elbv2
from aws_cdk import aws_iam as iam
from aws_cdk import aws_route53 as route53
from aws_cdk import aws_route53_targets as targets
from constructs import Construct


class LinkedPaperWebInfraStack(Stack):

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # VPC 생성
        linked_paper_vpc = ec2.Vpc(self, "LinkedPaperVpc", max_azs=2, nat_gateways=1)

        # NAT 게이트웨이 ID 가져오기
        nat_gateway_id = linked_paper_vpc.public_subnets[0].node.default_child.ref

        # NAT Gateway ID를 출력하여 다른 스택에서 사용할 수 있도록 함
        CfnOutput(
            self,
            "NatGatewayId",
            value=nat_gateway_id,
            description="NAT Gateway ID for the VPC",
            export_name="NatGatewayId",
        )

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
            connection=ec2.Port.tcp(80),  # Search Service의 LB에 대한 포트 80 열기
        )

        # Search Service Fargate 클러스터 생성 (Private Subnet에 배포)
        search_cluster = ecs.Cluster(self, "SearchServiceCluster", vpc=linked_paper_vpc)

        # Search Service ECS Task Role 생성
        search_service_task_role = iam.Role(
            self,
            "SearchServiceTaskRole",
            assumed_by=iam.ServicePrincipal("ecs-tasks.amazonaws.com"),
        )

        # OpenSearch 접근 권한 추가
        search_service_task_role.add_managed_policy(
            iam.ManagedPolicy.from_aws_managed_policy_name(
                "AmazonOpenSearchServiceFullAccess"
            )
        )

        # EC2 네트워크 리소스 읽기 권한 추가
        search_service_task_role.add_managed_policy(
            iam.ManagedPolicy.from_aws_managed_policy_name("AmazonEC2ReadOnlyAccess")
        )

        # ECS Task 정의 생성 (Search Service)
        search_task_definition = ecs.FargateTaskDefinition(
            self,
            "SearchServiceTaskDef",
            memory_limit_mib=4096,  # Task memory limit
            cpu=2048,  # Task CPU limit
            task_role=search_service_task_role,
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

        # ECR 접근 권한 추가
        search_task_definition.add_to_execution_role_policy(
            iam.PolicyStatement(
                actions=[
                    "ecr:GetDownloadUrlForLayer",
                    "ecr:BatchGetImage",
                    "ecr:GetAuthorizationToken",
                ],
                resources=["*"],
            )
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

        # Output: API 서버의 Load Balancer DNS
        search_service_load_balancer_dns = (
            search_service.load_balancer.load_balancer_dns_name
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
                "SEARCH_SERVICE_URL": f"http://{search_service_load_balancer_dns}",  # Search Service URL
            },
            cpu=1024,
            memory_limit_mib=2048,
            logging=ecs.LogDrivers.aws_logs(stream_prefix="ApiService"),
            port_mappings=[ecs.PortMapping(container_port=8080)],
        )

        # ECR 접근 권한 추가
        api_task_definition.add_to_execution_role_policy(
            iam.PolicyStatement(
                actions=[
                    "ecr:GetDownloadUrlForLayer",
                    "ecr:BatchGetImage",
                    "ecr:GetAuthorizationToken",
                ],
                resources=["*"],
            )
        )

        # Add EC2 read-only access for VPC and network resources to the execution role
        api_task_definition.add_to_task_role_policy(
            iam.PolicyStatement(
                actions=[
                    "ec2:DescribeInstances",
                    "ec2:DescribeNetworkInterfaces",
                    "ec2:DescribeSecurityGroups",
                ],
                resources=["*"],
            )
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

        # Auto Scaling 설정 (API 서버)
        api_scalable_target = api_service.service.auto_scale_task_count(
            min_capacity=1,
            max_capacity=2,
        )

        api_scalable_target.scale_on_cpu_utilization(
            "CpuScaling",
            target_utilization_percent=100,  # 목표 CPU 사용률 90%
            scale_in_cooldown=Duration.seconds(30),  # 스케일 인 쿨다운 (30초)
            scale_out_cooldown=Duration.seconds(10),  # 스케일 아웃 쿨다운 (10초)
        )

        # Auto Scaling 설정 (Search Service)
        search_scalable_target = search_service.service.auto_scale_task_count(
            min_capacity=1,
            max_capacity=3,
        )

        search_scalable_target.scale_on_cpu_utilization(
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
        api_certificate = acm.Certificate(
            self,
            "ApiServiceCertificate",
            domain_name="api.linked-paper.com",
            validation=acm.CertificateValidation.from_dns(hosted_zone),
        )

        # HTTPS 리스너에 인증서 추가
        api_service.load_balancer.add_listener(
            "ApiHttpsListener",
            port=443,
            certificates=[api_certificate],
            default_target_groups=[api_service.target_group],
        )

        # Route53 A 레코드 생성 (api.linkedpaper.com을 API 서버의 Load Balancer DNS로 매핑)
        route53.ARecord(
            self,
            "ApiServiceRecord",
            zone=hosted_zone,
            record_name="api",  # This creates api.linkedpaper.com
            target=route53.RecordTarget.from_alias(
                targets.LoadBalancerTarget(api_service.load_balancer)
            ),
        )

        # Output: API 서버의 Load Balancer DNS
        CfnOutput(
            self,
            "ApiServiceLoadBalancerDNS",
            value=api_service.load_balancer.load_balancer_dns_name,
        )

        CfnOutput(
            self,
            "SearchServiceTaskRoleArn",
            value=search_service_task_role.role_arn,
            export_name="SearchServiceTaskRoleArn",
        )
