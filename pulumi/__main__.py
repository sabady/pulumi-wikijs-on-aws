"""Main stack entry point for Wiki.js infrastructure."""
import pulumi
import pulumi_aws as aws
import pulumi_kubernetes as k8s

# Import components
from components.networking.vpc import VPCComponent
from components.storage.s3 import S3BucketComponent
from components.storage.rds import RDSPostgresComponent
from components.compute.eks import EKSComponent
from components.compute.wikijs import WikiJSComponent
from components.compute.alb_controller import AlbController
from components.compute.karpenter import KarpenterComponent
from components.security.iam import IAMComponent
from components.monitoring.keda import KedaComponent
from components.monitoring.observability import ObservabilityComponent
from components.monitoring.efk import EFKComponent

# Main stack entry point
# This file orchestrates all components

config = pulumi.Config()
environment = config.get("environment") or "prod"
stack_name = pulumi.get_stack()
base_name = f"wikijs-{environment}"

# Sensitive configs
wikijs_cfg = pulumi.Config("wikijs")
db_user = wikijs_cfg.require_secret("dbUser")  # require explicit user
db_password = wikijs_cfg.require_secret("dbPassword")
db_name = wikijs_cfg.get("dbName") or "wikijs"
grafana_cfg = pulumi.Config("grafana")
grafana_admin_password = grafana_cfg.require_secret("adminPassword")

# 1. Create VPC with subnets in 2 availability zones
pulumi.log.info("Creating VPC and networking components...")
vpc = VPCComponent(
    name=base_name,
    cidr="10.0.0.0/16",
)

# 2. Create S3 bucket for WikiJS storage
pulumi.log.info("Creating S3 bucket for WikiJS storage...")
s3_bucket = S3BucketComponent(
    name=base_name,
    enable_versioning=True,
)

# 3. Create EKS cluster with node groups spanning 2 AZs
pulumi.log.info("Creating EKS cluster...")
eks_cluster = EKSComponent(
    name=base_name,
    vpc_id=vpc.vpc.id,
    private_subnet_ids=[subnet.id for subnet in vpc.private_subnets],
    public_subnet_ids=[subnet.id for subnet in vpc.public_subnets],
    instance_type="t3.medium",
    min_size=2,
    max_size=4,
    desired_size=2,
)

# 4. Security Group for ALB locked down to Cloudflare IP ranges
pulumi.log.info("Creating ALB security group restricted to Cloudflare ranges...")
cloudflare_ipv4 = [
    "173.245.48.0/20",
    "103.21.244.0/22",
    "103.22.200.0/22",
    "103.31.4.0/22",
    "141.101.64.0/18",
    "108.162.192.0/18",
    "190.93.240.0/20",
    "188.114.96.0/20",
    "197.234.240.0/22",
    "198.41.128.0/17",
    "162.158.0.0/15",
    "104.16.0.0/13",
    "104.24.0.0/14",
    "172.64.0.0/13",
    "131.0.72.0/22",
]
cloudflare_ipv6 = [
    "2400:cb00::/32",
    "2606:4700::/32",
    "2803:f800::/32",
    "2405:b500::/32",
    "2405:8100::/32",
    "2a06:98c0::/29",
    "2c0f:f248::/32",
]

alb_sg = aws.ec2.SecurityGroup(
    f"{base_name}-alb-sg",
    vpc_id=vpc.vpc.id,
    description="ALB SG allowing 80/443 only from Cloudflare",
    ingress=[
        *[
            aws.ec2.SecurityGroupIngressArgs(
                protocol="tcp",
                from_port=443,
                to_port=443,
                cidr_blocks=[cidr],
            )
            for cidr in cloudflare_ipv4
        ],
        *[
            aws.ec2.SecurityGroupIngressArgs(
                protocol="tcp",
                from_port=443,
                to_port=443,
                ipv6_cidr_blocks=[cidr],
            )
            for cidr in cloudflare_ipv6
        ],
    ],
    egress=[
        aws.ec2.SecurityGroupEgressArgs(
            protocol="-1",
            from_port=0,
            to_port=0,
            cidr_blocks=["0.0.0.0/0"],
            ipv6_cidr_blocks=["::/0"],
        )
    ],
    tags={"Name": f"{base_name}-alb-sg"},
)

# 4. Deploy AWS Load Balancer Controller (ALB) for ingress
pulumi.log.info("Deploying AWS Load Balancer Controller...")
alb_controller = AlbController(
    name=base_name,
    cluster_name=eks_cluster.cluster.core.cluster.name,
    cluster_oidc_provider_arn=eks_cluster.oidc_provider_arn,
    kubeconfig=eks_cluster.kubeconfig,
    region="us-east-1",
    vpc_id=vpc.vpc.id,
)

# 5. Create IAM roles and policies (S3, EBS CSI)
pulumi.log.info("Creating IAM roles and policies...")
iam = IAMComponent(
    name=base_name,
    s3_bucket_arn=s3_bucket.bucket.arn,
    cluster_name=eks_cluster.cluster.core.cluster.name,
    oidc_provider_arn=eks_cluster.oidc_provider_arn,
)

# 6. RDS PostgreSQL for WikiJS
pulumi.log.info("Creating RDS PostgreSQL for WikiJS...")
rds = RDSPostgresComponent(
    name=base_name,
    db_name=db_name,
    username=db_user,
    password=db_password,
    subnet_ids=[subnet.id for subnet in vpc.private_subnets],
    vpc_id=vpc.vpc.id,
)

# 7. Deploy WikiJS using Helm (Ingress handled via ALB controller)
pulumi.log.info("Deploying WikiJS using Helm...")
wikijs = WikiJSComponent(
    name=base_name,
    kubeconfig=eks_cluster.cluster.kubeconfig,
    s3_bucket_name=s3_bucket.bucket.id,
    s3_region="us-east-1",
    ebs_csi_addon=eks_cluster.ebs_csi_addon,
    alb_security_group_id=alb_sg.id,
    db_host=rds.instance.address,
    db_port=5432,
    db_user=db_user,
    db_password=db_password,
    db_name=db_name,
)

# 7. Karpenter for node autoscaling
pulumi.log.info("Deploying Karpenter for node autoscaling...")
karpenter = KarpenterComponent(
    name=base_name,
    cluster_name=eks_cluster.cluster.core.cluster.name,
    cluster_endpoint=eks_cluster.cluster.core.cluster.endpoint,
    cluster_ca=eks_cluster.cluster.core.cluster.certificate_authority.data,
    cluster_oidc_provider_arn=eks_cluster.oidc_provider_arn,
    subnet_ids=[subnet.id for subnet in vpc.private_subnets],
    sg_ids=[alb_sg.id],
    kubeconfig=eks_cluster.kubeconfig,
)

# 8. Observability: Prometheus + Grafana
pulumi.log.info("Deploying Prometheus/Grafana (kube-prometheus-stack)...")
observability = ObservabilityComponent(
    name=base_name,
    kubeconfig=eks_cluster.kubeconfig,
)

# 9. KEDA for app autoscaling using Prometheus metrics
pulumi.log.info("Deploying KEDA...")
keda = KedaComponent(
    name=base_name,
    kubeconfig=eks_cluster.kubeconfig,
)

# 10. EFK stack for logs and alerts
pulumi.log.info("Deploying EFK stack...")
efk = EFKComponent(
    name=base_name,
    kubeconfig=eks_cluster.kubeconfig,
)

# 11. KEDA ScaledObject for WikiJS using Prometheus metrics
pulumi.log.info("Creating KEDA ScaledObject for WikiJS...")
prometheus_server = "http://kube-prometheus-stack-prometheus.monitoring.svc:9090"
keda_scaled_object = k8s.apiextensions.CustomResource(
    f"{base_name}-wikijs-scaledobject",
    api_version="keda.sh/v1alpha1",
    kind="ScaledObject",
    metadata=k8s.meta.v1.ObjectMetaArgs(
        name=f"{base_name}-wikijs",
        namespace="wikijs",
    ),
    spec={
        "scaleTargetRef": {"name": "wikijs-wiki"},
        "minReplicaCount": 2,
        "maxReplicaCount": 10,
        "triggers": [
            {
                "type": "prometheus",
                "metadata": {
                    "serverAddress": prometheus_server,
                    "metricName": "wikijs_requests_per_second",
                    "threshold": "10",
                    "query": 'sum(rate(http_requests_total{app="wikijs"}[1m]))',
                },
            }
        ],
    },
    opts=pulumi.ResourceOptions(
        provider=keda.k8s_provider,
        depends_on=[keda.chart, observability.chart, wikijs.wikijs_release],
    ),
)

# Export outputs
pulumi.export("vpc_id", vpc.vpc.id)
pulumi.export("s3_bucket_name", s3_bucket.bucket.id)
pulumi.export("eks_cluster_name", eks_cluster.cluster.core.cluster.name)
pulumi.export("eks_cluster_endpoint", eks_cluster.cluster.core.cluster.endpoint)

