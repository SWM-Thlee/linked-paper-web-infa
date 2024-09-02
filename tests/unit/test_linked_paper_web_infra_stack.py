import aws_cdk as core
import aws_cdk.assertions as assertions

from linked_paper_web_infra.linked_paper_web_infra_stack import LinkedPaperWebInfraStack

# example tests. To run these tests, uncomment this file along with the example
# resource in linked_paper_web_infra/linked_paper_web_infra_stack.py
def test_sqs_queue_created():
    app = core.App()
    stack = LinkedPaperWebInfraStack(app, "linked-paper-web-infra")
    template = assertions.Template.from_stack(stack)

#     template.has_resource_properties("AWS::SQS::Queue", {
#         "VisibilityTimeout": 300
#     })
