import json
import os

import boto3
import urllib3

secretsmanager_client = boto3.client("secretsmanager")
sns_client = boto3.client("sns")
http = urllib3.PoolManager()


def lambda_handler(event, context):
    # Secrets Manager에서 Slack Webhook URL 가져오기
    secret_name = os.environ["SECRET_NAME"]
    secret_value_response = secretsmanager_client.get_secret_value(SecretId=secret_name)
    slack_webhook_url = secret_value_response["SecretString"]

    # 이벤트에서 중요한 정보 추출
    detail = event.get("detail", {})
    event_type = detail.get("eventType", "N/A")
    event_name = detail.get("eventName", "N/A")
    cluster_arn = detail.get("clusterArn", "N/A")
    deployment_id = detail.get("deploymentId", "N/A")
    reason = detail.get("reason", "N/A")
    updated_at = detail.get("updatedAt", "N/A")

    # 클러스터 이름과 서비스 이름 추출 (ARN에서 이름만 추출)
    cluster_name = cluster_arn.split("/")[-1] if cluster_arn != "N/A" else "N/A"

    # 메시지 포맷팅
    message = (
        f"*ECS 배포 이벤트 발생*\n"
        f"• *이벤트 유형*: {event_type}\n"
        f"• *이벤트 이름*: {event_name}\n"
        f"• *클러스터 이름*: {cluster_name}\n"
        f"• *배포 ID*: {deployment_id}\n"
        f"• *사유*: {reason}\n"
        f"• *업데이트 시각*: {updated_at}"
    )

    # Slack 메시지 전송
    slack_message = {"text": message}

    # Slack Webhook 호출
    response = http.request(
        "POST",
        slack_webhook_url,
        body=json.dumps(slack_message),
        headers={"Content-Type": "application/json"},
    )

    # 응답 상태 확인
    if response.status != 200:
        raise Exception(f"Slack Webhook 호출 실패. 상태 코드: {response.status}")

    # 성공 시 SNS에 알림 게시
    sns_topic_arn = os.environ["SNS_TOPIC_ARN"]
    sns_client.publish(
        TopicArn=sns_topic_arn,
        Message=f"Slack으로 알림 전송 성공: {message}",
        Subject="ECS 배포 알림 성공",
    )

    return {
        "statusCode": 200,
        "body": json.dumps("Slack notification sent successfully!"),
    }
