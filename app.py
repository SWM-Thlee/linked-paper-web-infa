#!/usr/bin/env python3
import aws_cdk as cdk
import boto3

from deploy_monitor.ecs_deploy_monitor import EcsDeploymentNotifierStack
from etl_monitor.batch_monitor import BatchFailureAlertStack
from linked_paper_web_infra.backend_stack import BackendInfraStack
from linked_paper_web_infra.front_stack import LinkedPaperWebInfraStack
from security.waf_stack import WafStack
from traffic_monitor.nat_gateway import NatGatewayMonitoringStack


def get_aws_account_id():
    sts_client = boto3.client("sts")
    return sts_client.get_caller_identity()["Account"]


def get_default_region():
    session = boto3.session.Session()
    return session.region_name


app = cdk.App()
LinkedPaperWebInfraStack(
    app,
    "LinkedPaperWebInfraStack",
    # If you don't specify 'env', this stack will be environment-agnostic.
    # Account/Region-dependent features and context lookups will not work,
    # but a single synthesized template can be deployed anywhere.
    # Uncomment the next line to specialize this stack for the AWS Account
    # and Region that are implied by the current CLI configuration.
    # env=cdk.Environment(account=os.getenv('CDK_DEFAULT_ACCOUNT'), region=os.getenv('CDK_DEFAULT_REGION')),
    # Uncomment the next line if you know exactly what Account and Region you
    # want to deploy the stack to. */
    env=cdk.Environment(account=get_aws_account_id(), region=get_default_region()),
    # For more information, see https://docs.aws.amazon.com/cdk/latest/guide/environments.html
)

WafStack(
    app,
    "WafStack",
    env=cdk.Environment(account=get_aws_account_id(), region=get_default_region()),
)


BackendInfraStack(
    app,
    "BackendInfraStack",
    env=cdk.Environment(account=get_aws_account_id(), region=get_default_region()),
)

NatGatewayMonitoringStack(
    app,
    "NatGatewayMonitoringStack",
    env=cdk.Environment(account=get_aws_account_id(), region=get_default_region()),
)

EcsDeploymentNotifierStack(
    app,
    "EcsDeploymentNotifierStack",
    env=cdk.Environment(account=get_aws_account_id(), region=get_default_region()),
)

BatchFailureAlertStack(
    app,
    "BatchFailureAlertStack",
    env=cdk.Environment(account=get_aws_account_id(), region=get_default_region()),
)

app.synth()
