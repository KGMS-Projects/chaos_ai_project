"""
utils/prometheus_client.py
Thin wrapper around the Prometheus HTTP API.
Used by the Sentinel agent to query SLIs.
"""

import requests
from datetime import datetime
from config.settings import PROMETHEUS_URL


class PrometheusClient:
    """Query Prometheus for key Online Boutique SLIs."""

    def __init__(self, base_url: str = PROMETHEUS_URL):
        self.base_url = base_url.rstrip("/")

    # ── Core query helpers ────────────────────────────────────────────────────

    def query(self, promql: str) -> list[dict]:
        """Run an instant PromQL query and return the result vector."""
        try:
            resp = requests.get(
                f"{self.base_url}/api/v1/query",
                params={"query": promql, "time": datetime.utcnow().isoformat()},
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()
            if data["status"] == "success":
                return data["data"]["result"]
            return []
        except requests.RequestException as e:
            print(f"[PrometheusClient] Query failed: {e}")
            return []

    def scalar(self, promql: str, default: float = 0.0) -> float:
        """Return the first scalar value from a PromQL query."""
        results = self.query(promql)
        if results:
            return float(results[0]["value"][1])
        return default

    # ── SLI methods (used by Sentinel agent) ─────────────────────────────────

    def get_http_error_rate(self) -> float:
        """
        Fraction of HTTP requests returning 5xx in the last 2 minutes.
        Returns a value between 0.0 and 1.0.
        """
        promql = (
            "sum(rate(http_requests_total{status=~'5..'}[2m])) / "
            "sum(rate(http_requests_total[2m]))"
        )
        return self.scalar(promql)

    def get_p99_latency_ms(self) -> float:
        """99th-percentile request latency in milliseconds."""
        promql = (
            "histogram_quantile(0.99, "
            "sum(rate(http_request_duration_seconds_bucket[2m])) by (le)) * 1000"
        )
        return self.scalar(promql)

    def get_pod_restart_count(self, namespace: str = "default") -> int:
        """Total pod restarts in the target namespace over the last 5 minutes."""
        promql = (
            f"sum(increase(kube_pod_container_status_restarts_total"
            f"{{namespace='{namespace}'}}[5m]))"
        )
        return int(self.scalar(promql))

    def get_all_slis(self, namespace: str = "default") -> dict:
        """Collect all SLIs in one call — used as the Sentinel snapshot."""
        return {
            "error_rate":     self.get_http_error_rate(),
            "p99_latency_ms": self.get_p99_latency_ms(),
            "pod_restarts":   self.get_pod_restart_count(namespace),
            "timestamp":      datetime.utcnow().isoformat(),
        }

    def is_healthy(
        self,
        error_rate_threshold: float = 0.05,
        latency_threshold_ms: float = 2000,
        restart_threshold: int = 3,
        namespace: str = "default",
    ) -> tuple[bool, dict]:
        """
        Returns (healthy: bool, slis: dict).
        healthy=True means all SLIs are within thresholds.
        """
        slis = self.get_all_slis(namespace)
        healthy = (
            slis["error_rate"]     <= error_rate_threshold
            and slis["p99_latency_ms"] <= latency_threshold_ms
            and slis["pod_restarts"]   <= restart_threshold
        )
        return healthy, slis
