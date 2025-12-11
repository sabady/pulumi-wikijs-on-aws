"""EKS cluster component for WikiJS."""
import pulumi
import pulumi_aws as aws
import pulumi_eks as eks


class EKSComponent:
    """Creates EKS cluster with node groups spanning 2 availability zones."""

    def __init__(
        self,
        name: str,
        vpc_id: str,
        private_subnet_ids: list,
        public_subnet_ids: list,
        instance_type: str = "t3.medium",
        min_size: int = 2,
        max_size: int = 4,
        desired_size: int = 2,
    ):
        """Initialize EKS component.

        Args:
            name: Base name for resources
            vpc_id: VPC ID where cluster will be created
            private_subnet_ids: List of private subnet IDs
            public_subnet_ids: List of public subnet IDs
            instance_type: EC2 instance type for nodes
            min_size: Minimum number of nodes
            max_size: Maximum number of nodes
            desired_size: Desired number of nodes
        """
        self.name = name
        self.vpc_id = vpc_id
        self.private_subnet_ids = private_subnet_ids
        self.public_subnet_ids = public_subnet_ids
        self.instance_type = instance_type
        self.min_size = min_size
        self.max_size = max_size
        self.desired_size = desired_size
        self.cluster = None
        self.node_group = None
        self._create_cluster()

    def _create_cluster(self):
        """Create EKS cluster with node groups."""
        # Create EKS cluster
        self.cluster = eks.Cluster(
            f"{self.name}-cluster",
            name=f"{self.name}-cluster",
            vpc_id=self.vpc_id,
            subnet_ids=self.private_subnet_ids,
            # Do not create managed node group; Karpenter will provision all capacity
            create_node_group=False,
            enabled_cluster_log_types=["api", "audit", "authenticator", "controllerManager", "scheduler"],
            tags={
                "Name": f"{self.name}-cluster",
                "Environment": pulumi.get_stack(),
            },
        )

        # Expose kubeconfig and oidc provider arn for integrations
        self.kubeconfig = self.cluster.kubeconfig
        self.oidc_provider_arn = self.cluster.core.oidc_provider.arn

        # Add EBS CSI driver addon for EBS volume support
        self.ebs_csi_addon = aws.eks.Addon(
            f"{self.name}-ebs-csi-addon",
            cluster_name=self.cluster.core.cluster.name,
            addon_name="aws-ebs-csi-driver",
            # The addon will use the default service role created by EKS
            # or we can specify a custom role if needed
            tags={
                "Name": f"{self.name}-ebs-csi-addon",
            },
            opts=pulumi.ResourceOptions(depends_on=[self.cluster]),
        )

        # Get OIDC provider URL from cluster
        # Extract from cluster identity
        current = aws.get_caller_identity()
        self.oidc_provider_url = self.cluster.core.cluster.identities[0].oidcs[0].issuer
        
        # Extract OIDC provider ARN
        # Format: https://oidc.eks.us-east-1.amazonaws.com/id/PROVIDER_ID
        self.oidc_provider_arn = pulumi.Output.all(
            self.oidc_provider_url, current.account_id
        ).apply(
            lambda args: f"arn:aws:iam::{args[1]}:oidc-provider/{args[0].replace('https://', '')}"
        )

        # Export cluster information
        pulumi.export("eks_cluster_name", self.cluster.core.cluster.name)
        pulumi.export("eks_cluster_endpoint", self.cluster.core.cluster.endpoint)
        pulumi.export("eks_kubeconfig", self.cluster.kubeconfig)
        pulumi.export("eks_oidc_provider_arn", self.oidc_provider_arn)

