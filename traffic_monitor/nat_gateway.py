from aws_cdk import Duration, Fn, Stack
from aws_cdk import aws_cloudwatch as cloudwatch
from aws_cdk import aws_cloudwatch_actions as actions
from aws_cdk import aws_secretsmanager as secretsmanager
from aws_cdk import aws_sns as sns
from aws_cdk import aws_sns_subscriptions as subscriptions
from constructs import Construct


class NatGatewayMonitoringStack(Stack):
    def __init__(self, scope: Construct, id: str, **kwargs) -> None:
        super().__init__(scope, id, **kwargs)

        # NAT Gateway ID 가져오기
        nat_gateway_id = "nat-05c30695a91f4edcb"

        # Slack Webhook URL 가져오기
        slack_webhook_secret = secretsmanager.Secret.from_secret_name_v2(
            self, "SlackWebhookSecret", "GlueSlackWebhookURL"
        )
        slack_webhook_url = slack_webhook_secret.secret_value.to_string()

        # Slack 통지용 SNS 주제 생성
        slack_topic = sns.Topic(
            self,
            "SlackNotificationTopic",
            display_name="NAT Gateway Slack Notification",
        )

        # 기존 NAT Gateway의 CloudWatch 메트릭 참조
        nat_gateway_bytes_out_metric = cloudwatch.Metric(
            namespace="AWS/NATGateway",
            metric_name="BytesOutToDestination",
            dimensions_map={"NatGatewayId": nat_gateway_id},
            statistic="Sum",
            period=Duration.minutes(5),
        )

        # NAT Gateway 트래픽 알람 생성
        traffic_alarm = cloudwatch.Alarm(
            self,
            "NatGatewayTrafficAlarm",
            metric=nat_gateway_bytes_out_metric,
            threshold=20000000,  # 20MB 이상의 트래픽이 발생할 경우
            evaluation_periods=1,
            alarm_description="Alarm when NAT Gateway traffic exceeds 1GB in 5 minutes",
            comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
        )

        # 알람 발생 시 SNS 주제로 알림 전송
        traffic_alarm.add_alarm_action(actions.SnsAction(slack_topic))
