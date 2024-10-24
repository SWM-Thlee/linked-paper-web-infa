import json
import os

import boto3
import urllib3

secretsmanager_client = boto3.client("secretsmanager")
http = urllib3.PoolManager()


def lambda_handler(event, context):
    # Secrets Manager에서 Slack Webhook URL 가져오기
    secret_name = os.environ["SECRET_NAME"]
    secret_value_response = secretsmanager_client.get_secret_value(SecretId=secret_name)
    slack_webhook_url = secret_value_response["SecretString"]

    # 이벤트에서 중요한 정보 추출
    detail = event.get("detail", {})
    job_name = detail.get("jobName", "N/A")
    job_id = detail.get("jobId", "N/A")
    status = detail.get("status", "N/A")
    status_reason = detail.get("statusReason", "N/A")
    created_at = detail.get("createdAt", "N/A")
    stopped_at = detail.get("stoppedAt", "N/A")

    # 메시지 포맷팅 (성공/실패에 따라 다른 메시지 구성)
    if status == "FAILED":
        message = (
            f"*AWS Batch 작업 실패* `{job_name}`\n"
            f"• *작업 ID*: `{job_id}`\n"
            f"• *상태*: `{status}`\n"
            f"• *사유*: {status_reason}\n"
            f"• *시작 시각*: {created_at}\n"
            f"• *종료 시각*: {stopped_at}"
        )
    elif status == "SUCCEEDED":
        message = (
            f"*AWS Batch 작업 성공* `{job_name}`\n"
            f"• *작업 ID*: `{job_id}`\n"
            f"• *상태*: `{status}`\n"
            f"• *시작 시각*: {created_at}\n"
            f"• *종료 시각*: {stopped_at}"
        )
    else:
        message = (
            f"*AWS Batch 작업 상태 변경* `{job_name}`\n"
            f"• *작업 ID*: `{job_id}`\n"
            f"• *상태*: `{status}`\n"
            f"• *시작 시각*: {created_at}\n"
            f"• *종료 시각*: {stopped_at}"
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

    return {
        "statusCode": 200,
        "body": json.dumps("Slack notification sent successfully!"),
    }
