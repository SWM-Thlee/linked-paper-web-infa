from aws_cdk import Stack
from aws_cdk import aws_events as events
from aws_cdk import aws_events_targets as targets
from aws_cdk import aws_iam as iam
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_lambda_event_sources as lambda_event_sources
from aws_cdk import aws_sns as sns
from constructs import Construct


class EcsDeploymentNotifierStack(Stack):

    def __init__(self, scope: Construct, id: str, **kwargs) -> None:
        super().__init__(scope, id, **kwargs)

        # SNS Topic 생성
        sns_topic = sns.Topic(self, "EcsDeploymentTopic")

        # Lambda 함수 정의
        slack_notifier_lambda = lambda_.Function(
            self,
            "SlackNotifierLambda",
            runtime=lambda_.Runtime.PYTHON_3_9,
            handler="deploy_notifier.lambda_handler",
            code=lambda_.Code.from_asset("lambda"),
            environment={
                "SECRET_NAME": "GlueSlackWebhookURL",  # Secrets Manager의 Webhook URL 키
                "SNS_TOPIC_ARN": sns_topic.topic_arn,
            },
        )

        # Lambda에 Secrets Manager 및 SNS 권한 부여
        slack_notifier_lambda.add_to_role_policy(
            iam.PolicyStatement(
                actions=["secretsmanager:GetSecretValue", "sns:Publish"],
                resources=["*"],
            )
        )

        # EventBridge 규칙을 설정하여 ECS 배포 이벤트 감지
        ecs_deployment_event_rule = events.Rule(
            self,
            "EcsDeploymentEventRule",
            event_pattern=events.EventPattern(
                source=["aws.ecs"],
                detail_type=[
                    "ECS Deployment State Change"
                ],  # EventBridge에 정의된 ECS 이벤트 타입
            ),
        )

        # EventBridge 규칙이 Lambda 함수를 타겟으로 설정
        ecs_deployment_event_rule.add_target(
            targets.LambdaFunction(slack_notifier_lambda)
        )

        # Lambda가 SNS에 메시지를 게시할 수 있도록 권한 추가
        sns_topic.grant_publish(slack_notifier_lambda)
