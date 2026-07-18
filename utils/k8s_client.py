"""
utils/k8s_client.py
Kubernetes API helpers used by Remediation and Adversary agents.
Wraps the official kubernetes-python client for common operations.
"""

from kubernetes import client, config as k8s_config
from kubernetes.client.rest import ApiException
from config.settings import KUBECONFIG, TARGET_NAMESPACE


class K8sClient:
    """Thin wrapper around the Kubernetes Python client."""

    def __init__(self, namespace: str = TARGET_NAMESPACE):
        self.namespace = namespace
        try:
            k8s_config.load_kube_config(config_file=KUBECONFIG)
        except Exception:
            # Fallback: in-cluster config (if running inside a pod)
            k8s_config.load_incluster_config()

        self.core   = client.CoreV1Api()
        self.apps   = client.AppsV1Api()

    # ── Pod queries ───────────────────────────────────────────────────────────

    def list_pods(self) -> list[dict]:
        """Return simplified pod info for all pods in the namespace."""
        pods = self.core.list_namespaced_pod(self.namespace)
        result = []
        for pod in pods.items:
            restarts = sum(
                cs.restart_count
                for cs in (pod.status.container_statuses or [])
            )
            result.append({
                "name":      pod.metadata.name,
                "phase":     pod.status.phase,
                "restarts":  restarts,
                "labels":    pod.metadata.labels or {},
            })
        return result

    def get_unhealthy_pods(self) -> list[dict]:
        """Return pods that are not Running or have restart count > 2."""
        all_pods = self.list_pods()
        return [
            p for p in all_pods
            if p["phase"] not in ("Running", "Succeeded") or p["restarts"] > 2
        ]

    def get_pod_names_for_service(self, service_label: str) -> list[str]:
        """Get pod names matching app=<service_label>."""
        pods = self.core.list_namespaced_pod(
            self.namespace,
            label_selector=f"app={service_label}",
        )
        return [p.metadata.name for p in pods.items]

    # ── Remediation actions ───────────────────────────────────────────────────

    def delete_pod(self, pod_name: str) -> bool:
        """
        Delete a pod by name — Kubernetes will recreate it automatically.
        This is the primary remediation action (force restart).
        """
        try:
            self.core.delete_namespaced_pod(pod_name, self.namespace)
            print(f"[K8sClient] Deleted pod {pod_name} (will be recreated)")
            return True
        except ApiException as e:
            print(f"[K8sClient] Failed to delete pod {pod_name}: {e}")
            return False

    def restart_deployment(self, deployment_name: str) -> bool:
        """
        Trigger a rollout restart of a Deployment.
        Equivalent to: kubectl rollout restart deployment/<name>
        """
        import datetime
        try:
            patch = {
                "spec": {
                    "template": {
                        "metadata": {
                            "annotations": {
                                "kubectl.kubernetes.io/restartedAt":
                                    datetime.datetime.utcnow().isoformat()
                            }
                        }
                    }
                }
            }
            self.apps.patch_namespaced_deployment(
                deployment_name, self.namespace, patch
            )
            print(f"[K8sClient] Rollout restart triggered for {deployment_name}")
            return True
        except ApiException as e:
            print(f"[K8sClient] Restart failed for {deployment_name}: {e}")
            return False

    def scale_deployment(self, deployment_name: str, replicas: int) -> bool:
        """Scale a deployment to the given number of replicas."""
        try:
            self.apps.patch_namespaced_deployment_scale(
                deployment_name,
                self.namespace,
                {"spec": {"replicas": replicas}},
            )
            print(f"[K8sClient] Scaled {deployment_name} to {replicas} replica(s)")
            return True
        except ApiException as e:
            print(f"[K8sClient] Scale failed for {deployment_name}: {e}")
            return False

    # ── Cluster snapshot ──────────────────────────────────────────────────────

    def cluster_snapshot(self) -> dict:
        """
        Returns a dict summarising the current cluster state.
        Passed to LLM agents as context.
        """
        pods = self.list_pods()
        return {
            "total_pods":    len(pods),
            "running":       sum(1 for p in pods if p["phase"] == "Running"),
            "not_running":   sum(1 for p in pods if p["phase"] != "Running"),
            "high_restarts": [p for p in pods if p["restarts"] > 2],
            "pods":          pods,
        }
