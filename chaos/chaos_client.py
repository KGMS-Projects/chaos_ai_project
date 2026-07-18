"""
chaos/chaos_client.py
Chaos Mesh API wrapper.
Applies and deletes ChaosExperiment CRDs via kubectl subprocess calls.
Also supports direct YAML application for Chaos Mesh v2.6.
"""

import os
import subprocess
import yaml
from pathlib import Path
from config.settings import (
    CHAOS_EXPERIMENTS_DIR,
    CHAOS_EXPERIMENT_CATALOGUE,
    TARGET_NAMESPACE,
)


class ChaosMeshClient:
    """
    Wraps Chaos Mesh experiment lifecycle:
      inject()  → apply a chaos YAML
      cleanup() → delete the chaos resource
    """

    def __init__(self, namespace: str = TARGET_NAMESPACE):
        self.namespace = namespace
        self.experiments_dir = Path(CHAOS_EXPERIMENTS_DIR)
        self._active_experiment: str | None = None

    # ── Core actions ──────────────────────────────────────────────────────────

    def inject(self, experiment_name: str, target_service: str) -> bool:
        """
        Apply a chaos experiment YAML after substituting the target service.

        Args:
            experiment_name: key in CHAOS_EXPERIMENT_CATALOGUE
            target_service:  app label of the target microservice

        Returns:
            True if kubectl apply succeeded.
        """
        if experiment_name not in CHAOS_EXPERIMENT_CATALOGUE:
            print(f"[ChaosMesh] Unknown experiment: {experiment_name}")
            return False

        yaml_file = self.experiments_dir / CHAOS_EXPERIMENT_CATALOGUE[experiment_name]
        if not yaml_file.exists():
            print(f"[ChaosMesh] YAML not found: {yaml_file}")
            return False

        # Load, patch target service, write to a temp file
        with open(yaml_file) as f:
            spec = yaml.safe_load(f)

        # Inject the chosen target service into the label selector.
        # RFC 1123: names must be lowercase alphanumeric or '-', no underscores.
        safe_name = f"{experiment_name}-{target_service}".replace("_", "-")
        try:
            spec["spec"]["selector"]["labelSelectors"]["app"] = target_service
            spec["metadata"]["name"] = safe_name
        except KeyError:
            # cpu_stress may not have a service selector; still fix the name
            spec["metadata"]["name"] = safe_name

        tmp_path = f"/tmp/chaos_{experiment_name}_{target_service}.yaml"
        with open(tmp_path, "w") as f:
            yaml.dump(spec, f)

        result = self._kubectl_apply(tmp_path)
        if result:
            self._active_experiment = spec["metadata"]["name"]
            print(f"[ChaosMesh] ✓ Injected '{experiment_name}' on '{target_service}'")
        return result

    def cleanup(self, experiment_name: str = None) -> bool:
        """
        Delete the active chaos experiment (or a named one).
        Call this after the recovery window to stop the fault.
        """
        name = experiment_name or self._active_experiment
        if not name:
            print("[ChaosMesh] No active experiment to clean up.")
            return False

        cmd = ["kubectl", "delete", "podchaos,networkchaos,stresschaos",
               name, "-n", self.namespace, "--ignore-not-found"]
        result = subprocess.run(cmd, capture_output=True, text=True)
        success = result.returncode == 0
        if success:
            print(f"[ChaosMesh] ✓ Cleaned up experiment '{name}'")
            self._active_experiment = None
        else:
            print(f"[ChaosMesh] Cleanup failed: {result.stderr}")
        return success

    def cleanup_all(self) -> None:
        """Remove ALL chaos resources in the namespace (safety reset)."""
        for kind in ["podchaos", "networkchaos", "stresschaos"]:
            subprocess.run(
                ["kubectl", "delete", kind, "--all", "-n", self.namespace,
                 "--ignore-not-found"],
                capture_output=True,
            )
        print("[ChaosMesh] All chaos experiments removed.")

    # ── Private helpers ───────────────────────────────────────────────────────

    def _kubectl_apply(self, yaml_path: str) -> bool:
        result = subprocess.run(
            ["kubectl", "apply", "-f", yaml_path],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            print(f"[ChaosMesh] kubectl apply failed:\n{result.stderr}")
        return result.returncode == 0
