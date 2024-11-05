import json
import os
from datetime import datetime, timedelta

import boto3
import urllib3

secretsmanager_client = boto3.client("secretsmanager")
cloudwatch_client = boto3.client("cloudwatch")
http = urllib3.PoolManager()


def lambda_handler(event, context):
    # 이벤트에서 클러스터와 서비스 이름 가져오기
    cluster_name = event.get("cluster_name", "N/A")
    service_name = event.get("service_name", "N/A")

    # Slack Webhook URL 가져오기
    secret_name = os.environ["SECRET_NAME"]
    secret_value_response = secretsmanager_client.get_secret_value(SecretId=secret_name)
    slack_webhook_url = secret_value_response["SecretString"]

    # 이벤트에서 알람 정보 추출
    detail = event.get("detail", {})
    alarm_name = detail.get("alarmName", "N/A")
    new_state = detail.get("newStateValue", "N/A")
    reason = detail.get("newStateReason", "N/A")
    timestamp = detail.get("stateChangeTime", "N/A")

    # 알람 이름을 기반으로 메트릭 종류 확인 (CPU 또는 메모리)
    if "CpuAlarm" in alarm_name:
        alarm_type = "CPU Utilization"
        metric_name = "CPUUtilization"
    elif "MemoryAlarm" in alarm_name:
        alarm_type = "Memory Utilization"
        metric_name = "MemoryUtilization"
    else:
        alarm_type = "Unknown Alarm"
        metric_name = None

    # 최근 5분간의 메트릭 평균값 조회
    if metric_name:
        end_time = datetime.utcnow()
        start_time = end_time - timedelta(minutes=5)
        response = cloudwatch_client.get_metric_statistics(
            Namespace="AWS/ECS",
            MetricName=metric_name,
            Dimensions=[
                {"Name": "ClusterName", "Value": cluster_name},
                {"Name": "ServiceName", "Value": service_name},
            ],
            StartTime=start_time,
            EndTime=end_time,
            Period=300,
            Statistics=["Average"],
        )
        # CPU 및 메모리 사용량 값 추출
        data_points = response["Datapoints"]
        if data_points:
            avg_usage = data_points[-1]["Average"]
            usage_message = f"{avg_usage:.2f}%"
        else:
            usage_message = "데이터 없음"
    else:
        usage_message = "N/A"

    # 메시지 포맷팅
    message = (
        f"*ECS {alarm_type} 알람 발생*\n"
        f"• *알람 이름*: `{alarm_name}`\n"
        f"• *클러스터 이름*: `{cluster_name}`\n"
        f"• *서비스 이름*: `{service_name}`\n"
        f"• *새로운 상태*: `{new_state}`\n"
        f"• *사유*: {reason}\n"
        f"• *발생 시각*: {timestamp}\n"
        f"• *평균 {alarm_type} 사용량*: {usage_message}"
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
