
# Linked Paper Web Infra as Code

This project automates the deployment of Linked Paper's web infrastructure on AWS using Infrastructure as Code (IaC) with AWS CDK. The architecture includes both frontend and backend services, as well as security and monitoring components.

## Architecture
(그림)

## Stacks
1. **LinkedPaperWebInfraStack**
    - **Role**: Manages the frontend web service deployment using Next.js.
    - **Key Components**: VPC, ALB, ECS Fargate.
    - [FE Nextjs 프로젝트](https://github.com/SWM-Thlee/linked-paper-front)을 배포하고 트래픽을 분산 처리합니다.

2. **BackendInfraStack**
    - **Role**: Manages backend services including the API server and search server.
    - **Key Components**: ECS cluster for API and search, OpenSearch for search functionalities.
    - Private Subnets 내 ECS 클러스터([API server](https://github.com/SWM-Thlee/linked-paper-backend), [Search server](https://github.com/SWM-Thlee/linked-paper-search/tree/main/search_server))를 관리합니다.

3. **WafStack**
    - **Role**: Protects the web application through AWS WAF by setting security rules to prevent attacks such as SQL injection and XSS.
    - **Key Components**: WAF, integration with ALB.
    - ALB(API 서버)에 WAF 보안을 적용하여 웹 공격을 방어합니다.

4. **NatGatewayMonitoringStack**
    - **Role**: Monitors NAT Gateway traffic to optimize costs.
    - **Key Components**: CloudWatch alarms for traffic monitoring, cost analysis tools.
    - NAT Gateway의 트래픽을 추적하고 과도한 비용이 사용되지 않도록 경보를 생성합니다.

5. **EcsDeploymentNotifierStack**
    - **Role**: Sends real-time ECS deployment notifications to Slack, helping the team track deployment statuses.
    - **Key Components**: Lambda for notifications, Slack integration.
    - ECS 배포 상태를 실시간으로 Slack에 알림으로 전달해 배포 상황을 추적할 수 있게 도와줍니다.
