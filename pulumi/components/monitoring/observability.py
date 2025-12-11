"""Prometheus and Grafana via kube-prometheus-stack."""
import pulumi
import pulumi_kubernetes as k8s
from pulumi_kubernetes.helm.v3 import Chart, ChartOpts, FetchOpts


class ObservabilityComponent:
    """Deploy kube-prometheus-stack for metrics and dashboards."""

    def __init__(self, name: str, kubeconfig: str, namespace: str = "monitoring", grafana_admin_password=None):
        self.name = name
        self.k8s_provider = k8s.Provider(
            f"{name}-obs-k8s",
            kubeconfig=kubeconfig,
        )
        self.chart = Chart(
            f"{self.name}-kube-prometheus",
            ChartOpts(
                chart="kube-prometheus-stack",
                version="61.4.0",
                fetch_opts=FetchOpts(repo="https://prometheus-community.github.io/helm-charts"),
                namespace=namespace,
                create_namespace=True,
                values={
                    "grafana": {
                        "adminPassword": grafana_admin_password,
                        "service": {"type": "ClusterIP"},
                    },
                    "prometheus": {
                        "service": {"type": "ClusterIP"},
                    },
                },
            ),
            opts=pulumi.ResourceOptions(provider=self.k8s_provider),
        )

