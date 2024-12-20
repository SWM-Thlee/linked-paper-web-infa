from aws_cdk import Aws, CfnOutput, Duration, Fn, Stack
from aws_cdk import aws_apigatewayv2 as apigateway
from aws_cdk import aws_apigatewayv2_integrations as apigateway_integrations
from aws_cdk import aws_autoscaling as autoscaling
from aws_cdk import aws_certificatemanager as acm
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_ecs as ecs
from aws_cdk import aws_ecs_patterns as ecs_patterns
from aws_cdk import aws_elasticloadbalancingv2 as elbv2
from aws_cdk import aws_iam as iam
from aws_cdk import aws_route53 as route53
from aws_cdk import aws_route53_targets as route53_targets
from aws_cdk import aws_wafv2 as wafv2
from constructs import Construct


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

        # EC2 인스턴스에 할당할 IAM 역할 생성
        ec2_instance_role = iam.Role(
            self,
            "EC2InstanceRole",
            assumed_by=iam.ServicePrincipal("ec2.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "service-role/AmazonECSTaskExecutionRolePolicy"
                ),  # 수정된 정책
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "AmazonSSMManagedInstanceCore"
                ),  # EC2 인스턴스 관리용 (SSM 접근)
            ],
        )

        user_data = ec2.UserData.for_linux()

        user_data.add_commands(
            "echo ECS_ENABLE_GPU_SUPPORT=true >> /etc/ecs/ecs.config"
        )

        # Auto Scaling 그룹 생성 (g4dn.xlarge GPU 지원 인스턴스)
        gpu_asg = autoscaling.AutoScalingGroup(
            self,
            "GPUAutoScalingGroup",
            vpc=linked_paper_vpc,
            vpc_subnets=private_subnets[0],
            instance_type=ec2.InstanceType("g4dn.xlarge"),  # g4dn.xlarge 인스턴스 유형
            machine_image=ecs.EcsOptimizedImage.amazon_linux2(
                ecs.AmiHardwareType.GPU
            ),  # GPU용 ECS 최적화 AMI
            desired_capacity=2,  # 기본 EC2 인스턴스 개수
            min_capacity=1,  # 최소 EC2 인스턴스 개수
            max_capacity=3,  # 최대 EC2 인스턴스 개수 ecs 최대 인스턴스 수 + 배포할 인스턴스
            security_group=search_service_security_group,  # 보안 그룹 재사용
            role=ec2_instance_role,  # EC2 인스턴스에 필요한 IAM 역할
            user_data=user_data,  # GPU 지원 활성화
        )

        # ASG Capacity Provider 생성
        asg_capacity_provider = ecs.AsgCapacityProvider(
            self,
            "AsgCapacityProvider",
            auto_scaling_group=gpu_asg,
            enable_managed_scaling=True,  # ECS에서 자동으로 ASG 확장/축소 관리
            enable_managed_draining=True,  # ECS에서 자동으로 인스턴스 드레인 관리
        )

        # ECS 클러스터에 Capacity Provider 추가
        search_cluster.add_asg_capacity_provider(
            asg_capacity_provider,
            can_containers_access_instance_role=True,  # 컨테이너가 EC2 인스턴스의 역할을 사용할 수 있게 함
        )

        # ECS Task 정의 생성 (EC2 기반)
        search_task_definition = ecs.Ec2TaskDefinition(
            self,
            "SearchServiceTaskDef",
            network_mode=ecs.NetworkMode.AWS_VPC,
            task_role=search_service_task_role,
        )

        search_task_definition.add_to_execution_role_policy(
            iam.PolicyStatement(
                actions=[
                    "ecr:GetDownloadUrlForLayer",
                    "ecr:BatchGetImage",
                    "ecr:GetAuthorizationToken",
                ],
                resources=["*"],  # 모든 ECR 리소스에 대한 권한을 부여
            )
        )

        # GPU 자원을 사용하는 컨테이너 추가
        search_task_definition.add_container(
            "SearchServiceContainer",
            image=ecs.ContainerImage.from_registry(
                f"{Aws.ACCOUNT_ID}.dkr.ecr.{Aws.REGION}.amazonaws.com/search_service_image:latest"
            ),
            environment={
                "NODE_ENV": "production",
            },
            memory_limit_mib=1024 * 8,  # 8 GB 메모리
            cpu=1024 * 4,  # 4 vCPU
            gpu_count=1,  # GPU 자원 요청
            logging=ecs.LogDrivers.aws_logs(stream_prefix="SearchService"),
            port_mappings=[ecs.PortMapping(container_port=8000)],
        )

        # ECS 서비스 생성 (EC2 기반)
        search_service = ecs.Ec2Service(
            self,
            "SearchServiceEC2Service",
            cluster=search_cluster,
            task_definition=search_task_definition,
            desired_count=1,  # 원하는 태스크 개수
            security_groups=[search_service_security_group],
            vpc_subnets=private_subnets[0],
            placement_constraints=[
                ecs.PlacementConstraint.member_of(
                    "attribute:ecs.instance-type == g4dn.xlarge"
                )  # GPU 인스턴스에서만 배치
            ],
        )

        # Application Load Balancer 생성 (HTTP 트래픽을 EC2 서비스로 전달)
        search_service_load_balancer = elbv2.ApplicationLoadBalancer(
            self,
            "SearchServiceLB",
            vpc=linked_paper_vpc,
            vpc_subnets=ec2.SubnetSelection(
                subnets=linked_paper_vpc.private_subnets  # 프라이빗 서브넷으로 로드 밸런서를 배치
            ),
            internet_facing=False,
            security_group=search_service_security_group,  # 동일한 보안 그룹을 사용
        )

        listener = elbv2.ApplicationListener(
            self,
            "SearchApiListener",
            load_balancer=search_service_load_balancer,
            port=80,
            default_action=elbv2.ListenerAction.forward(
                target_groups=[
                    elbv2.ApplicationTargetGroup(
                        self,
                        "SearchServiceTargetGroup",
                        vpc=linked_paper_vpc,
                        port=8000,
                        targets=[search_service],
                        health_check=elbv2.HealthCheck(
                            path="/",
                            interval=Duration.seconds(30),
                        ),
                    )
                ]
            ),
        )

        # Output: API 서버의 Load Balancer DNS
        search_service_load_balancer_dns = (
            search_service_load_balancer.load_balancer_dns_name
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

        # Create an API Gateway HTTP API
        api_gateway = apigateway.HttpApi(self, "ApiGateway")

        # Create a custom domain name for the API Gateway
        domain_name = apigateway.DomainName(
            self,
            "ApiDomainName",
            domain_name="api.linked-paper.com",
            certificate=api_certificate,
        )

        # Map the custom domain name to the API Gateway stage
        apigateway.ApiMapping(
            self,
            "ApiGatewayDomainMapping",
            domain_name=domain_name,
            api=api_gateway,
            stage=api_gateway.default_stage,
        )

        # Integration with the Load Balancer (Direct DNS approach)
        lb_dns = api_service.load_balancer.load_balancer_dns_name

        lb_integration = apigateway_integrations.HttpUrlIntegration(
            "ApiGatewayLoadBalancerIntegration",
            url=f"http://{lb_dns}/{{proxy}}",  # Correctly forward the path
        )

        # Add routes for "/search" and "/correlations" paths using a proxy pattern
        api_gateway.add_routes(
            path="/{proxy+}",  # Catch all paths and forward them to the Load Balancer
            methods=[apigateway.HttpMethod.ANY],  # Support all HTTP methods
            integration=lb_integration,
        )

        # Route53 A Record for api.linked-paper.com
        route53.ARecord(
            self,
            "ApiServiceRecord",
            zone=hosted_zone,
            record_name="api",  # This creates api.linked-paper.com
            target=route53.RecordTarget.from_alias(
                route53_targets.ApiGatewayv2DomainProperties(
                    domain_name.regional_domain_name,
                    domain_name.regional_hosted_zone_id,
                )
            ),
        )

        # Import the WAF Web ACL ARN from the WAF stack
        waf_acl_arn = Fn.import_value("WafAclArn")

        # WAF Web ACL association with API Gateway
        wafv2.CfnWebACLAssociation(
            self,
            "ApiGatewayWafAssociation",
            resource_arn=api_service.load_balancer.load_balancer_arn,
            web_acl_arn=waf_acl_arn,  # Use the imported ARN here
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

        CfnOutput(
            self,
            "ApiServiceName",
            value=api_service.service.service_name,
            export_name="ApiServiceName",
        )

        CfnOutput(
            self,
            "ApiClusterName",
            value=api_cluster.cluster_name,
            export_name="ApiClusterName",
        )
