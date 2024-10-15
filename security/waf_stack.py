from aws_cdk import CfnOutput, Stack
from aws_cdk import aws_wafv2 as wafv2
from constructs import Construct


class WafStack(Stack):
    def __init__(self, scope: Construct, id: str, **kwargs) -> None:
        super().__init__(scope, id, **kwargs)

        # Define the allowed paths
        allowed_paths = [
            "/search",
            "/correlations",
        ]  # No need for wildcards in the array

        # Create the WAF Web ACL
        waf_acl = wafv2.CfnWebACL(
            self,
            "ApiLoadBalancerWafAcl",
            default_action=wafv2.CfnWebACL.DefaultActionProperty(
                block={}
            ),  # Default action is to block
            scope="REGIONAL",  # This is for Load Balancer (REGIONAL type)
            visibility_config=wafv2.CfnWebACL.VisibilityConfigProperty(
                cloud_watch_metrics_enabled=False,
                metric_name="ApiLoadBalancerWafAcl",
                sampled_requests_enabled=False,
            ),
            rules=[
                # Allow paths that start with /search or /correlations
                wafv2.CfnWebACL.RuleProperty(
                    name="AllowSpecificPaths",
                    priority=1,
                    action=wafv2.CfnWebACL.RuleActionProperty(
                        allow={}
                    ),  # Allow these paths
                    statement=wafv2.CfnWebACL.StatementProperty(
                        or_statement=wafv2.CfnWebACL.OrStatementProperty(
                            statements=[
                                wafv2.CfnWebACL.StatementProperty(
                                    byte_match_statement=wafv2.CfnWebACL.ByteMatchStatementProperty(
                                        field_to_match=wafv2.CfnWebACL.FieldToMatchProperty(
                                            uri_path={}
                                        ),
                                        positional_constraint="STARTS_WITH",
                                        search_string=path,  # Directly pass the string
                                        text_transformations=[
                                            wafv2.CfnWebACL.TextTransformationProperty(
                                                priority=0, type="NONE"
                                            )
                                        ],
                                    )
                                )
                                for path in allowed_paths
                            ]
                        )
                    ),
                    visibility_config=wafv2.CfnWebACL.VisibilityConfigProperty(
                        cloud_watch_metrics_enabled=False,
                        metric_name="AllowSpecificPaths",
                        sampled_requests_enabled=False,
                    ),
                )
            ],
        )

        # Export the Web ACL ARN so other stacks can reference it
        CfnOutput(
            self,
            "WafAclArn",
            value=waf_acl.attr_arn,
            export_name="WafAclArn",  # This name will be used for importing
        )
