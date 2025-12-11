"""KEDA deployment for event-driven autoscaling."""
import pulumi
import pulumi_kubernetes as k8s
from pulumi_kubernetes.helm.v3 import Chart, ChartOpts, FetchOpts


class KedaComponent:
    """Deploy KEDA via Helm."""

    def __init__(self, name: str, kubeconfig: str, namespace: str = "keda"):
        self.name = name
        self.k8s_provider = k8s.Provider(
            f"{name}-keda-k8s",
            kubeconfig=kubeconfig,
        )
        self.chart = Chart(
            f"{self.name}-keda",
            ChartOpts(
                chart="keda",
                version="2.14.2",
                fetch_opts=FetchOpts(repo="https://kedacore.github.io/charts"),
                namespace=namespace,
                create_namespace=True,
            ),
            opts=pulumi.ResourceOptions(provider=self.k8s_provider),
        )

