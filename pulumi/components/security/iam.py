"""IAM roles and policies for WikiJS infrastructure."""
import pulumi
import pulumi_aws as aws
import json


class IAMComponent:
    """Creates IAM roles and policies for EKS and S3 access."""

    def __init__(self, name: str, s3_bucket_arn: str, cluster_name: str, oidc_provider_arn: str = None):
        """Initialize IAM component.

        Args:
            name: Base name for resources
            s3_bucket_arn: ARN of S3 bucket for WikiJS storage
            cluster_name: Name of EKS cluster
            oidc_provider_arn: OIDC provider ARN for the EKS cluster
        """
        self.name = name
        self.s3_bucket_arn = s3_bucket_arn
        self.cluster_name = cluster_name
        self.oidc_provider_arn = oidc_provider_arn
        self.wikijs_service_role = None
        self.alb_controller_role = None
        self._create_s3_access_policy()
        self._create_ebs_csi_role()
        if oidc_provider_arn:
            self._create_alb_controller_role()

    def _create_s3_access_policy(self):
        """Create IAM policy for S3 bucket access."""
        s3_policy = aws.iam.Policy(
            f"{self.name}-wikijs-s3-policy",
            name=f"{self.name}-wikijs-s3-policy",
            description="Policy for WikiJS to access S3 bucket",
            policy=json.dumps({
                "Version": "2012-10-17",
                "Statement": [
                    {
                        "Effect": "Allow",
                        "Action": [
                            "s3:GetObject",
                            "s3:PutObject",
                            "s3:DeleteObject",
                            "s3:ListBucket",
                        ],
                        "Resource": [
                            self.s3_bucket_arn,
                            f"{self.s3_bucket_arn}/*",
                        ],
                    },
                ],
            }),
        )
        return s3_policy

    def _create_ebs_csi_role(self):
        """Create IAM role for EBS CSI driver.
        
        Note: The EBS CSI driver addon in EKS will create its own IAM role
        if service role is not provided. This method creates a policy that
        can be attached to the node group role for EBS volume access.
        """
        # Get current account ID
        current = aws.get_caller_identity()
        
        # Trust policy for EBS CSI driver (simplified - EKS addon will handle OIDC)
        # This role will be used by the EBS CSI driver addon
        trust_policy = pulumi.Output.all(current.account_id).apply(
            lambda args: json.dumps({
                "Version": "2012-10-17",
                "Statement": [
                    {
                        "Effect": "Allow",
                        "Principal": {
                            "Federated": f"arn:aws:iam::{args[0]}:oidc-provider/oidc.eks.us-east-1.amazonaws.com/id/*",
                        },
                        "Action": "sts:AssumeRoleWithWebIdentity",
                        "Condition": {
                            "StringEquals": {
                                "oidc.eks.us-east-1.amazonaws.com/id/*:sub": "system:serviceaccount:kube-system:ebs-csi-controller-sa",
                                "oidc.eks.us-east-1.amazonaws.com/id/*:aud": "sts.amazonaws.com",
                            },
                        },
                    },
                ],
            })
        )

        # EBS CSI driver policy (managed policy)
        ebs_csi_policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonEBSCSIDriverPolicy"

        # Role for EBS CSI driver
        ebs_csi_role = aws.iam.Role(
            f"{self.name}-ebs-csi-role",
            name=f"{self.name}-ebs-csi-role",
            assume_role_policy=trust_policy,
            tags={
                "Name": f"{self.name}-ebs-csi-role",
            },
        )

        # Attach EBS CSI driver policy
        aws.iam.RolePolicyAttachment(
            f"{self.name}-ebs-csi-policy-attachment",
            role=ebs_csi_role.name,
            policy_arn=ebs_csi_policy_arn,
        )

        self.ebs_csi_role = ebs_csi_role
        return ebs_csi_role

    def _create_alb_controller_role(self):
        """Create IAM role for AWS Load Balancer Controller."""
        # Trust policy for AWS Load Balancer Controller
        # Extract OIDC provider URL from ARN and build condition key
        # ARN format: arn:aws:iam::ACCOUNT:oidc-provider/oidc.eks.REGION.amazonaws.com/id/PROVIDER_ID
        # Condition key format: oidc.eks.REGION.amazonaws.com/id/PROVIDER_ID:sub
        trust_policy = self.oidc_provider_arn.apply(
            lambda arn: json.dumps({
                "Version": "2012-10-17",
                "Statement": [
                    {
                        "Effect": "Allow",
                        "Principal": {
                            "Federated": arn,
                        },
                        "Action": "sts:AssumeRoleWithWebIdentity",
                        "Condition": {
                            "StringEquals": {
                                f"{arn.split('/')[-2]}/{arn.split('/')[-1]}:sub": "system:serviceaccount:kube-system:aws-load-balancer-controller",
                                f"{arn.split('/')[-2]}/{arn.split('/')[-1]}:aud": "sts.amazonaws.com",
                            },
                        },
                    },
                ],
            })
        )

        # AWS Load Balancer Controller policy (managed policy)
        alb_controller_policy_arn = "arn:aws:iam::aws:policy/ElasticLoadBalancingFullAccess"

        # Role for AWS Load Balancer Controller
        alb_controller_role = aws.iam.Role(
            f"{self.name}-alb-controller-role",
            name=f"{self.name}-alb-controller-role",
            assume_role_policy=trust_policy,
            tags={
                "Name": f"{self.name}-alb-controller-role",
            },
        )

        # Attach AWS Load Balancer Controller policy
        aws.iam.RolePolicyAttachment(
            f"{self.name}-alb-controller-policy-attachment",
            role=alb_controller_role.name,
            policy_arn=alb_controller_policy_arn,
        )

        self.alb_controller_role = alb_controller_role
        return alb_controller_role

