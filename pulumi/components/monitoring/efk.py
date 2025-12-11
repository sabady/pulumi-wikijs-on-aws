"""EFK stack (Elasticsearch, Fluent Bit, Kibana) for logs."""
import pulumi
import pulumi_kubernetes as k8s
from pulumi_kubernetes.helm.v3 import Chart, ChartOpts, FetchOpts


class EFKComponent:
    """Deploy Elasticsearch, Fluent Bit, and Kibana via Helm charts."""

    def __init__(self, name: str, kubeconfig: str, namespace: str = "logging"):
        self.name = name
        self.k8s_provider = k8s.Provider(
            f"{name}-efk-k8s",
            kubeconfig=kubeconfig,
        )

        # Elasticsearch
        self.elasticsearch = Chart(
            f"{self.name}-elasticsearch",
            ChartOpts(
                chart="elasticsearch",
                version="19.20.1",
                fetch_opts=FetchOpts(repo="https://helm.elastic.co"),
                namespace=namespace,
                create_namespace=True,
                values={
                    "replicas": 1,
                    "minimumMasterNodes": 1,
                    "persistence": {"enabled": True, "size": "20Gi"},
                },
            ),
            opts=pulumi.ResourceOptions(provider=self.k8s_provider),
        )

        # Kibana
        self.kibana = Chart(
            f"{self.name}-kibana",
            ChartOpts(
                chart="kibana",
                version="9.1.2",
                fetch_opts=FetchOpts(repo="https://helm.elastic.co"),
                namespace=namespace,
                values={
                    "elasticsearchHosts": "http://elasticsearch-master:9200",
                    "service": {"type": "ClusterIP"},
                },
            ),
            opts=pulumi.ResourceOptions(provider=self.k8s_provider, depends_on=[self.elasticsearch]),
        )

        # Fluent Bit
        self.fluentbit = Chart(
            f"{self.name}-fluent-bit",
            ChartOpts(
                chart="fluent-bit",
                version="0.46.7",
                fetch_opts=FetchOpts(repo="https://fluent.github.io/helm-charts"),
                namespace=namespace,
                values={
                    "config": {
                        "outputs": {
                            "elasticsearch.conf": "\n".join(
                                [
                                    "[OUTPUT]",
                                    "    Name es",
                                    "    Match *",
                                    "    Host elasticsearch-master",
                                    "    Port 9200",
                                    "    Index kubernetes_cluster",
                                    "    Type flb_type",
                                    "    Logstash_Format On",
                                ]
                            )
                        }
                    }
                },
            ),
            opts=pulumi.ResourceOptions(provider=self.k8s_provider, depends_on=[self.elasticsearch]),
        )

