"""WikiJS Helm deployment component."""
from typing import Optional

import pulumi
import pulumi_kubernetes as k8s
from pulumi_kubernetes.helm.v3 import Chart, ChartOpts, FetchOpts


class WikiJSComponent:
    """Deploys WikiJS using Helm chart."""

    def __init__(
        self,
        name: str,
        kubeconfig: str,
        s3_bucket_name: str,
        s3_region: str = "us-east-1",
        s3_access_key_id: str = None,
        s3_secret_access_key: str = None,
        ebs_csi_addon: pulumi.Resource = None,
        hostname: Optional[str] = None,
        certificate_arn: Optional[str] = None,
        alb_security_group_id: Optional[str] = None,
        db_host: Optional[str] = None,
        db_port: int = 5432,
        db_user: Optional[pulumi.Input[str]] = None,
        db_password: Optional[pulumi.Input[str]] = None,
        db_name: str = "wikijs",
    ):
        """Initialize WikiJS component.

        Args:
            name: Base name for resources
            kubeconfig: Kubeconfig for Kubernetes cluster
            s3_bucket_name: S3 bucket name for WikiJS storage
            s3_region: AWS region for S3 bucket
            s3_access_key_id: AWS access key ID for S3 (optional, can use IAM roles)
            s3_secret_access_key: AWS secret access key for S3 (optional, can use IAM roles)
            ebs_csi_addon: EBS CSI addon resource to wait for
            hostname: Optional hostname to configure on ingress
            certificate_arn: Optional ACM certificate ARN for HTTPS
            alb_security_group_id: Optional security group ID to attach to the ALB
            db_host/db_port/db_user/db_password/db_name: External Postgres (RDS) connection
        """
        self.name = name
        self.s3_bucket_name = s3_bucket_name
        self.s3_region = s3_region
        self.s3_access_key_id = s3_access_key_id
        self.s3_secret_access_key = s3_secret_access_key
        self.ebs_csi_addon = ebs_csi_addon
        self.hostname = hostname
        self.certificate_arn = certificate_arn
        self.alb_security_group_id = alb_security_group_id
        self.db_host = db_host
        self.db_port = db_port
        self.db_user = db_user
        self.db_password = db_password
        self.db_name = db_name
        self.k8s_provider = None
        self.storage_class = None
        self.wikijs_release = None
        self._create_k8s_provider(kubeconfig)
        self._create_storage_class()
        self._deploy_wikijs()

    def _create_k8s_provider(self, kubeconfig: str):
        """Create Kubernetes provider."""
        self.k8s_provider = k8s.Provider(
            f"{self.name}-k8s-provider",
            kubeconfig=kubeconfig,
        )

    def _create_storage_class(self):
        """Create EBS storage class for PostgreSQL."""
        # Wait for EBS CSI addon if provided
        depends_on = []
        if self.ebs_csi_addon:
            depends_on.append(self.ebs_csi_addon)
        
        self.storage_class = k8s.storage.v1.StorageClass(
            f"{self.name}-ebs-sc",
            metadata=k8s.meta.v1.ObjectMetaArgs(
                name="ebs-sc",
            ),
            provisioner="ebs.csi.aws.com",
            volume_binding_mode="WaitForFirstConsumer",
            allow_volume_expansion=True,
            parameters={
                "type": "gp3",
                "fsType": "ext4",
            },
            opts=pulumi.ResourceOptions(
                provider=self.k8s_provider,
                depends_on=depends_on,
            ),
        )

    def _deploy_wikijs(self):
        """Deploy WikiJS using Helm chart."""
        # Prepare environment variables for S3
        env_vars = {
            "DB_TYPE": "postgres",
            "DB_HOST": self.db_host,
            "DB_PORT": str(self.db_port),
            "DB_USER": self.db_user,
            "DB_PASS": self.db_password,
            "DB_NAME": self.db_name,
            "STORAGE_BACKEND": "s3",
            "STORAGE_S3_BUCKET": self.s3_bucket_name,
            "STORAGE_S3_REGION": self.s3_region,
        }

        # Add S3 credentials if provided
        if self.s3_access_key_id:
            env_vars["STORAGE_S3_KEY_ID"] = self.s3_access_key_id
        if self.s3_secret_access_key:
            env_vars["STORAGE_S3_SECRET"] = self.s3_secret_access_key

        # Deploy WikiJS Helm chart from official repository
        self.wikijs_release = Chart(
            f"{self.name}-wikijs",
            ChartOpts(
                chart="wiki",
                version="2.0.0",
                fetch_opts=FetchOpts(
                    repo="https://charts.js.wiki",
                ),
                namespace="wikijs",
                create_namespace=True,
                values={
                    "image": {
                        "tag": "2.5.300",
                    },
                    "persistence": {
                        "enabled": True,
                        "storageClass": "ebs-sc",
                        "size": "10Gi",
                    },
                    "postgresql": {
                        "enabled": False,
                    },
                    "externalDatabase": {
                        "host": self.db_host,
                        "port": self.db_port,
                        "user": self.db_user,
                        "password": self.db_password,
                        "database": self.db_name,
                    },
                    "env": env_vars,
                    "service": {
                        "type": "ClusterIP",  # Ingress will handle external access
                    },
                    "ingress": {
                        "enabled": True,
                        "className": "alb",
                        "annotations": self._build_ingress_annotations(),
                        "hosts": [
                            {
                                "host": self.hostname or "",
                                "paths": [
                                    {
                                        "path": "/",
                                        "pathType": "Prefix",
                                    }
                                ],
                            }
                        ],
                    },
                    "replicaCount": 2,  # High availability
                },
            ),
            opts=pulumi.ResourceOptions(provider=self.k8s_provider),
        )

        # Export WikiJS service endpoint
        pulumi.export("wikijs_service_name", self.wikijs_release.resources)

    def _build_ingress_annotations(self):
        """Build ALB ingress annotations, including optional certificate."""
        annotations = {
            "kubernetes.io/ingress.class": "alb",
            "alb.ingress.kubernetes.io/scheme": "internet-facing",
            "alb.ingress.kubernetes.io/target-type": "ip",
            "alb.ingress.kubernetes.io/listen-ports": '[{"HTTP":80},{"HTTPS":443}]',
            "alb.ingress.kubernetes.io/ssl-redirect": "443",
            "alb.ingress.kubernetes.io/healthcheck-path": "/",
        }
        if self.certificate_arn:
            annotations["alb.ingress.kubernetes.io/certificate-arn"] = self.certificate_arn
        if self.alb_security_group_id:
            annotations["alb.ingress.kubernetes.io/security-groups"] = self.alb_security_group_id
        return annotations

    def create_ingress(self, alb_controller: pulumi.Resource = None, hostname: str = None):
        """Create Ingress resource for WikiJS.
        
        Args:
            alb_controller: AWS Load Balancer Controller resource to wait for
            hostname: Optional hostname for the ingress
        """
        depends_on = [self.wikijs_release]
        if alb_controller:
            depends_on.append(alb_controller)
        
        # Create Ingress for WikiJS
        ingress = k8s.networking.v1.Ingress(
            f"{self.name}-wikijs-ingress",
            metadata=k8s.meta.v1.ObjectMetaArgs(
                name=f"{self.name}-wikijs",
                namespace="wikijs",
                annotations={
                    "alb.ingress.kubernetes.io/scheme": "internet-facing",
                    "alb.ingress.kubernetes.io/target-type": "ip",
                    "alb.ingress.kubernetes.io/listen-ports": '[{"HTTP": 80}, {"HTTPS": 443}]',
                    "alb.ingress.kubernetes.io/ssl-redirect": "443",
                    "alb.ingress.kubernetes.io/healthcheck-path": "/",
                    "alb.ingress.kubernetes.io/healthcheck-protocol": "HTTP",
                    "alb.ingress.kubernetes.io/healthcheck-interval-seconds": "30",
                    "alb.ingress.kubernetes.io/healthcheck-timeout-seconds": "5",
                    "alb.ingress.kubernetes.io/healthy-threshold-count": "2",
                    "alb.ingress.kubernetes.io/unhealthy-threshold-count": "3",
                },
            ),
            spec=k8s.networking.v1.IngressSpecArgs(
                ingress_class_name="alb",
                rules=[
                    k8s.networking.v1.IngressRuleArgs(
                        host=hostname if hostname else None,
                        http=k8s.networking.v1.HTTPIngressRuleValueArgs(
                            paths=[
                                k8s.networking.v1.HTTPIngressPathArgs(
                                    path="/",
                                    path_type="Prefix",
                                    backend=k8s.networking.v1.IngressBackendArgs(
                                        service=k8s.networking.v1.IngressServiceBackendArgs(
                                            name="wikijs-wiki",
                                            port=k8s.networking.v1.ServiceBackendPortArgs(
                                                number=3000,
                                            ),
                                        ),
                                    ),
                                ),
                            ],
                        ),
                    ),
                ],
            ),
            opts=pulumi.ResourceOptions(
                provider=self.k8s_provider,
                depends_on=depends_on,
            ),
        )
        
        self.ingress = ingress
        return ingress

