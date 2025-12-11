"""AWS Load Balancer Controller deployment."""
import json

import pulumi
import pulumi_aws as aws
import pulumi_kubernetes as k8s
from pulumi_kubernetes.helm.v3 import Chart, ChartOpts, FetchOpts


class AlbController:
    """Deploy the AWS Load Balancer Controller via Helm with IRSA."""

    def __init__(
        self,
        name: str,
        cluster_name: str,
        cluster_oidc_provider_arn: str,
        kubeconfig: str,
        region: str,
        vpc_id: str,
    ):
        self.name = name
        self.cluster_name = cluster_name
        self.cluster_oidc_provider_arn = cluster_oidc_provider_arn
        self.region = region
        self.vpc_id = vpc_id
        self.k8s_provider = k8s.Provider(
            f"{name}-k8s-provider",
            kubeconfig=kubeconfig,
        )

        self.policy = self._create_policy()
        self.sa = self._create_service_account()
        self.chart = self._install_chart()

    def _create_policy(self) -> aws.iam.Policy:
        """IAM policy for the controller (AWS provided)."""
        policy_doc = aws.iam.get_policy_document(
            statements=[
                aws.iam.GetPolicyDocumentStatementArgs(
                    effect="Allow",
                    actions=["elasticloadbalancing:*", "ec2:Describe*"],
                    resources=["*"],
                ),
                aws.iam.GetPolicyDocumentStatementArgs(
                    effect="Allow",
                    actions=["ec2:CreateSecurityGroup", "ec2:CreateTags", "ec2:AuthorizeSecurityGroupIngress", "ec2:AuthorizeSecurityGroupEgress", "ec2:RevokeSecurityGroupIngress", "ec2:RevokeSecurityGroupEgress", "ec2:DeleteSecurityGroup"],
                    resources=["*"],
                ),
                aws.iam.GetPolicyDocumentStatementArgs(
                    effect="Allow",
                    actions=["iam:CreateServiceLinkedRole"],
                    resources=["*"],
                    conditions=[
                        aws.iam.GetPolicyDocumentStatementConditionArgs(
                            test="StringEquals",
                            variable="iam:AWSServiceName",
                            values=["elasticloadbalancing.amazonaws.com"],
                        )
                    ],
                ),
            ]
        )
        return aws.iam.Policy(
            f"{self.name}-alb-policy",
            policy=policy_doc.json,
        )

    def _create_service_account(self) -> k8s.core.v1.ServiceAccount:
        """Create service account with IRSA for the controller."""
        sa_name = "aws-load-balancer-controller"
        namespace = "kube-system"
        provider_url = self.cluster_oidc_provider_arn.split("oidc-provider/")[1]

        # IRSA role
        assume_role_policy = aws.iam.get_policy_document(
            statements=[
                aws.iam.GetPolicyDocumentStatementArgs(
                    effect="Allow",
                    principals=[
                        aws.iam.GetPolicyDocumentStatementPrincipalArgs(
                            type="Federated",
                            identifiers=[self.cluster_oidc_provider_arn],
                        )
                    ],
                    actions=["sts:AssumeRoleWithWebIdentity"],
                    conditions=[
                        aws.iam.GetPolicyDocumentStatementConditionArgs(
                            test="StringEquals",
                            variable=f"{provider_url}:sub",
                            values=[f"system:serviceaccount:{namespace}:{sa_name}"],
                        ),
                        aws.iam.GetPolicyDocumentStatementConditionArgs(
                            test="StringEquals",
                            variable=f"{provider_url}:aud",
                            values=["sts.amazonaws.com"],
                        ),
                    ],
                )
            ]
        )

        role = aws.iam.Role(
            f"{self.name}-alb-role",
            assume_role_policy=assume_role_policy.json,
        )
        aws.iam.RolePolicyAttachment(
            f"{self.name}-alb-role-attach",
            role=role.name,
            policy_arn=self.policy.arn,
        )

        return k8s.core.v1.ServiceAccount(
            f"{self.name}-alb-sa",
            metadata=k8s.meta.v1.ObjectMetaArgs(
                name=sa_name,
                namespace=namespace,
                annotations={
                    "eks.amazonaws.com/role-arn": role.arn,
                },
            ),
            opts=pulumi.ResourceOptions(provider=self.k8s_provider),
        )

    def _install_chart(self):
        """Install AWS Load Balancer Controller Helm chart."""
        return Chart(
            f"{self.name}-alb-controller",
            ChartOpts(
                chart="aws-load-balancer-controller",
                version="1.8.1",
                fetch_opts=FetchOpts(
                    repo="https://aws.github.io/eks-charts",
                ),
                namespace="kube-system",
                values={
                    "clusterName": self.cluster_name,
                    "region": self.region,
                    "vpcId": self.vpc_id,
                    "serviceAccount": {
                        "create": False,
                        "name": "aws-load-balancer-controller",
                    },
                },
            ),
            opts=pulumi.ResourceOptions(
                provider=self.k8s_provider,
                depends_on=[self.sa],
            ),
        )
"""AWS Load Balancer Controller component."""
import pulumi
import pulumi_kubernetes as k8s
from pulumi_kubernetes.helm.v3 import Chart, ChartOpts, FetchOpts


class ALBControllerComponent:
    """Deploys AWS Load Balancer Controller using Helm chart."""

    def __init__(
        self,
        name: str,
        kubeconfig: str,
        cluster_name: str,
        vpc_id: str,
        service_account_role_arn: str,
    ):
        """Initialize ALB Controller component.

        Args:
            name: Base name for resources
            kubeconfig: Kubeconfig for Kubernetes cluster
            cluster_name: Name of EKS cluster
            vpc_id: VPC ID where cluster is deployed
            service_account_role_arn: IAM role ARN for the service account
        """
        self.name = name
        self.cluster_name = cluster_name
        self.vpc_id = vpc_id
        self.service_account_role_arn = service_account_role_arn
        self.k8s_provider = None
        self.controller_release = None
        self._create_k8s_provider(kubeconfig)
        self._deploy_controller()

    def _create_k8s_provider(self, kubeconfig: str):
        """Create Kubernetes provider."""
        self.k8s_provider = k8s.Provider(
            f"{self.name}-alb-k8s-provider",
            kubeconfig=kubeconfig,
        )

    def _deploy_controller(self):
        """Deploy AWS Load Balancer Controller using Helm chart."""
        # Create namespace for AWS Load Balancer Controller
        namespace = k8s.core.v1.Namespace(
            f"{self.name}-aws-load-balancer-controller-ns",
            metadata=k8s.meta.v1.ObjectMetaArgs(
                name="kube-system",
            ),
            opts=pulumi.ResourceOptions(provider=self.k8s_provider),
        )

        # Create service account with IAM role annotation
        # Handle both string and Output types for role ARN
        annotations = pulumi.Output.all(self.service_account_role_arn).apply(
            lambda args: {"eks.amazonaws.com/role-arn": args[0]}
        )
        
        service_account = k8s.core.v1.ServiceAccount(
            f"{self.name}-aws-load-balancer-controller-sa",
            metadata=k8s.meta.v1.ObjectMetaArgs(
                name="aws-load-balancer-controller",
                namespace="kube-system",
                annotations=annotations,
            ),
            opts=pulumi.ResourceOptions(
                provider=self.k8s_provider,
                depends_on=[namespace],
            ),
        )

        # Deploy AWS Load Balancer Controller Helm chart
        self.controller_release = Chart(
            f"{self.name}-aws-load-balancer-controller",
            ChartOpts(
                chart="aws-load-balancer-controller",
                version="1.7.0",
                fetch_opts=FetchOpts(
                    repo="https://aws.github.io/eks-charts",
                ),
                namespace="kube-system",
                values={
                    "clusterName": self.cluster_name,
                    "serviceAccount": {
                        "create": False,
                        "name": "aws-load-balancer-controller",
                    },
                    "region": "us-east-1",
                    "vpcId": self.vpc_id,
                    "enableServiceMutatorWebhook": False,
                },
            ),
            opts=pulumi.ResourceOptions(
                provider=self.k8s_provider,
                depends_on=[service_account],
            ),
        )

        pulumi.export("alb_controller_deployed", True)

