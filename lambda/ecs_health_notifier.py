import json
import os

import boto3
import urllib3

secretsmanager_client = boto3.client("secretsmanager")
http = urllib3.PoolManager()


def lambda_handler(event, context):
    # Slack Webhook URL 가져오기
    secret_name = os.environ["SECRET_NAME"]
    secret_value_response = secretsmanager_client.get_secret_value(SecretId=secret_name)
    slack_webhook_url = secret_value_response["SecretString"]

    # 이벤트에서 알람 정보 추출
    detail = event.get("detail", {})
    alarm_name = detail.get("alarmName", "N/A")
    state_value = detail.get("state", {}).get("value", "N/A")
    reason = detail.get("state", {}).get("reason", "N/A")
    timestamp = detail.get("state", {}).get("timestamp", "N/A")

    # 알람에서 클러스터와 서비스 이름 추출
    dimensions = detail.get("trigger", {}).get("dimensions", [])
    cluster_name = "N/A"
    service_name = "N/A"

    # dimensions에서 ClusterName과 ServiceName 값 추출
    for dimension in dimensions:
        if dimension.get("name") == "ClusterName":
            cluster_name = dimension.get("value", "N/A")
        elif dimension.get("name") == "ServiceName":
            service_name = dimension.get("value", "N/A")

    # 메시지 포맷팅
    message = (
        f"*ECS Healthy Check Alarm Notification*\n"
        f"• *알람 이름*: `{alarm_name}`\n"
        f"• *상태 변경*: `{state_value}`\n"
        f"• *사유*: {reason}\n"
        f"• *발생 시각*: {timestamp}\n"
        f"• *클러스터 이름*: `{cluster_name}`\n"
        f"• *서비스 이름*: `{service_name}`"
    )

    # Slack 메시지 전송
    slack_message = {"text": message}
    response = http.request(
        "POST",
        slack_webhook_url,
        body=json.dumps(slack_message),
        headers={"Content-Type": "application/json"},
    )

    # 응답 상태 확인
    if response.status != 200:
        raise Exception(f"Slack Webhook 호출 실패. 상태 코드: {response.status}")

    return {
        "statusCode": 200,
        "body": json.dumps("Slack notification sent successfully!"),
    }
