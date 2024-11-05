from aws_cdk import Duration, Fn, Stack
from aws_cdk import aws_cloudwatch as cloudwatch
from aws_cdk import aws_cloudwatch_actions as actions
from aws_cdk import aws_iam as iam
from aws_cdk import aws_lambda as lambda_
from constructs import Construct


class ApiServerHealthMonitor(Stack):
    def __init__(self, scope: Construct, id: str, **kwargs) -> None:
        super().__init__(scope, id, **kwargs)

        # ECS 클러스터 및 서비스 이름 가져오기
        cluster_name = Fn.import_value("ApiClusterName")
        service_name = Fn.import_value("ApiServiceName")

        # Lambda 함수 정의
        slack_notifier_lambda = lambda_.Function(
            self,
            "SlackNotifierLambda",
            runtime=lambda_.Runtime.PYTHON_3_9,
            handler="ecs_health_notifier.lambda_handler",
            code=lambda_.Code.from_asset("lambda"),
            environment={
                "SECRET_NAME": "GlueSlackWebhookURL",
            },
        )

        # CloudWatch 및 Secrets Manager 권한 부여
        slack_notifier_lambda.add_to_role_policy(
            iam.PolicyStatement(
                actions=[
                    "cloudwatch:GetMetricStatistics",
                    "secretsmanager:GetSecretValue",
                ],
                resources=["*"],
            )
        )

        # CloudWatch에서 ECS 서비스의 CPU 및 메모리 메트릭 직접 정의
        cpu_metric = cloudwatch.Metric(
            namespace="AWS/ECS",
            metric_name="CPUUtilization",
            dimensions_map={"ClusterName": cluster_name, "ServiceName": service_name},
            period=Duration.minutes(5),
            statistic="Average",
        )

        memory_metric = cloudwatch.Metric(
            namespace="AWS/ECS",
            metric_name="MemoryUtilization",
            dimensions_map={"ClusterName": cluster_name, "ServiceName": service_name},
            period=Duration.minutes(5),
            statistic="Average",
        )

        # CloudWatch 알람 생성 및 Lambda 액션 추가
        cpu_alarm = cloudwatch.Alarm(
            self,
            "CpuAlarm",
            metric=cpu_metric,
            threshold=0.8,  # % 사용량 기준
            evaluation_periods=1,
            alarm_description="Alarm when ECS CPU utilization exceeds 80%",
            comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
        )
        cpu_alarm.add_alarm_action(actions.LambdaAction(slack_notifier_lambda))

        memory_alarm = cloudwatch.Alarm(
            self,
            "MemoryAlarm",
            metric=memory_metric,
            threshold=80,  # % 사용량 기준
            evaluation_periods=1,
            alarm_description="Alarm when ECS memory utilization exceeds 80%",
            comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
        )
        memory_alarm.add_alarm_action(actions.LambdaAction(slack_notifier_lambda))
