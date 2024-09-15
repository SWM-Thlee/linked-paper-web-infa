import boto3
from aws_cdk import Duration, Fn, Stack
from aws_cdk import aws_cloudwatch as cloudwatch
from aws_cdk import aws_cloudwatch_actions as actions
from aws_cdk import aws_sns as sns
from aws_cdk import aws_sns_subscriptions as subscriptions
from constructs import Construct


class NatGatewayMonitoringStack(Stack):
    def __init__(self, scope: Construct, id: str, **kwargs) -> None:
        super().__init__(scope, id, **kwargs)

        nat_gateway_id = Fn.import_value("NatGatewayId")

        slack_topic = sns.Topic(
            self,
            "SlackNotificationTopic",
            display_name="NAT Gateway Slack Notification",
        )

        # Secrets Manager에서 Slack Webhook URL 가져오기
        secret_name = "GlueSlackWebhookURL"
        client = boto3.client("secretsmanager")
        secret_value_response = client.get_secret_value(SecretId=secret_name)
        slack_webhook_url = secret_value_response["SecretString"]

        slack_topic.add_subscription(subscriptions.UrlSubscription(slack_webhook_url))

        # CloudWatch 알람 생성 (NAT Gateway의 트래픽 모니터링)
        nat_gateway_bytes_out_metric = cloudwatch.Metric(
            namespace="AWS/NATGateway",
            metric_name="BytesOut",
            dimensions_map={"NatGatewayId": nat_gateway_id},  # NAT Gateway ID 설정
            statistic="sum",
            period=Duration.minutes(5),
        )

        # 트래픽이 특정 임계값을 초과하면 알람 발생
        traffic_alarm = cloudwatch.Alarm(
            self,
            "NatGatewayTrafficAlarm",
            metric=nat_gateway_bytes_out_metric,
            threshold=5000000000,  # 5GB 이상 트래픽 발생 시
            evaluation_periods=1,
        )

        # 알람 발생 시 SNS 주제로 알림 전송
        traffic_alarm.add_alarm_action(actions.SnsAction(slack_topic))
