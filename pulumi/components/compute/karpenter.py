"""Karpenter deployment for cluster-autoscaling."""
import json

import pulumi
import pulumi_aws as aws
import pulumi_kubernetes as k8s
from pulumi_kubernetes.helm.v3 import Chart, ChartOpts, FetchOpts


class KarpenterComponent:
    """Deploy Karpenter with IRSA and a basic Provisioner."""

    def __init__(
        self,
        name: str,
        cluster_name: str,
        cluster_endpoint: str,
        cluster_ca: str,
        cluster_oidc_provider_arn: str,
        subnet_ids: list[str],
        sg_ids: list[str],
        kubeconfig: str,
        default_instance_type: str = "t3.medium",
        min_capacity: int = 2,
        max_capacity: int = 10,
    ):
        self.name = name
        self.cluster_name = cluster_name
        self.cluster_oidc_provider_arn = cluster_oidc_provider_arn
        self.subnet_ids = subnet_ids
        self.sg_ids = sg_ids
        self.k8s_provider = k8s.Provider(
            f"{name}-karpenter-k8s",
            kubeconfig=kubeconfig,
        )

        self.role = self._create_irsa_role()
        self.chart = self._install_chart()
        self.provisioner = self._create_provisioner(default_instance_type, min_capacity, max_capacity)

    def _create_irsa_role(self):
        """Create IAM role for Karpenter controller."""
        provider_url = self.cluster_oidc_provider_arn.split("oidc-provider/")[1]
        assume_doc = aws.iam.get_policy_document(
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
                            values=["system:serviceaccount:karpenter:karpenter"],
                        )
                    ],
                )
            ]
        )

        policy_arn = "arn:aws:iam::aws:policy/AmazonEKSClusterAutoscalerPolicy"

        role = aws.iam.Role(
            f"{self.name}-karpenter-role",
            assume_role_policy=assume_doc.json,
        )
        aws.iam.RolePolicyAttachment(
            f"{self.name}-karpenter-role-attach",
            role=role.name,
            policy_arn=policy_arn,
        )
        return role

    def _install_chart(self):
        """Install Karpenter Helm chart."""
        return Chart(
            f"{self.name}-karpenter",
            ChartOpts(
                chart="karpenter",
                version="0.37.0",
                fetch_opts=FetchOpts(repo="https://charts.karpenter.sh"),
                namespace="karpenter",
                create_namespace=True,
                values={
                    "serviceAccount": {
                        "create": True,
                        "name": "karpenter",
                        "annotations": {
                            "eks.amazonaws.com/role-arn": self.role.arn,
                        },
                    },
                    "settings": {
                        "clusterName": self.cluster_name,
                    },
                },
            ),
            opts=pulumi.ResourceOptions(provider=self.k8s_provider),
        )

    def _create_provisioner(self, instance_type: str, min_capacity: int, max_capacity: int):
        """Create a default provisioner (spot-only, amd64/arm64, all instance types)."""
        return k8s.apiextensions.CustomResource(
            f"{self.name}-karpenter-provisioner",
            api_version="karpenter.sh/v1beta1",
            kind="Provisioner",
            metadata=k8s.meta.v1.ObjectMetaArgs(name="default"),
            spec={
                "requirements": [
                    {"key": "karpenter.sh/capacity-type", "operator": "In", "values": ["spot"]},
                    {"key": "kubernetes.io/arch", "operator": "In", "values": ["amd64", "arm64"]},
                    {"key": "node.kubernetes.io/instance-type", "operator": "In", "values": ["*"]},
                ],
                "limits": {"resources": {"cpu": f"{max_capacity * 2}"}},
                "provider": {
                    "subnetSelector": {"karpenter.sh/discovery": self.cluster_name},
                    "securityGroupSelector": {"karpenter.sh/discovery": self.cluster_name},
                    "instanceProfile": self.role.name,
                },
                "consolidation": {"enabled": True},
                "ttlSecondsAfterEmpty": 0,
            },
            opts=pulumi.ResourceOptions(provider=self.k8s_provider, depends_on=[self.chart]),
        )

