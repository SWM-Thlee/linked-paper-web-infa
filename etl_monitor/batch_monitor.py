import os

from aws_cdk import Stack
from aws_cdk import aws_events as events
from aws_cdk import aws_events_targets as targets
from aws_cdk import aws_iam as iam
from aws_cdk import aws_lambda as _lambda
from constructs import Construct


class BatchFailureAlertStack(Stack):

    def __init__(self, scope: Construct, id: str, **kwargs) -> None:
        super().__init__(scope, id, **kwargs)

        slack_alert_lambda = _lambda.Function(
            self,
            "SlackAlertLambda",
            runtime=_lambda.Runtime.PYTHON_3_9,
            handler="batch_alarm.lambda_handler",
            code=_lambda.Code.from_asset("lambda"),
            environment={
                "SECRET_NAME": "GlueSlackWebhookURL",  # Secrets Manager의 Webhook URL 키
            },
        )

        # Lambda 함수가 CloudWatch Logs와 EventBridge 이벤트를 읽을 수 있도록 IAM 권한 설정
        slack_alert_lambda.add_to_role_policy(
            iam.PolicyStatement(actions=["logs:*", "events:*"], resources=["*"])
        )

        slack_alert_lambda.add_to_role_policy(
            iam.PolicyStatement(
                actions=["secretsmanager:GetSecretValue"],
                resources=["*"],
            )
        )

        # EventBridge 규칙 생성: Batch 작업 실패 및 성공 시 Lambda 트리거
        rule = events.Rule(
            self,
            "BatchStateChangeRule",
            event_pattern=events.EventPattern(
                source=["aws.batch"],
                detail_type=[
                    "Batch Job State Change"
                ],  # EventBridge에서 정의된 Batch 이벤트 타입
            ),
        )

        # 규칙이 Lambda 함수를 대상으로 설정되도록 지정
        rule.add_target(targets.LambdaFunction(slack_alert_lambda))
