"""
config/settings.py
Central configuration for the Chaos AI system.
All tuneable parameters live here — agents import from this module.
"""

import os
from dotenv import load_dotenv

load_dotenv()

# ── LLM ──────────────────────────────────────────────────────────────────────
OPENAI_API_KEY      = os.getenv("OPENAI_API_KEY", "")
ANTHROPIC_API_KEY   = os.getenv("ANTHROPIC_API_KEY", "")
LLM_MODEL           = "claude-sonnet-4-6"          # model used by all agents
LLM_TEMPERATURE     = 0.2                           # low = more deterministic

# ── Kubernetes ────────────────────────────────────────────────────────────────
KUBECONFIG          = os.getenv("KUBECONFIG", os.path.expanduser("~/.kube/config"))
TARGET_NAMESPACE    = os.getenv("TARGET_NAMESPACE", "default")
CHAOS_NAMESPACE     = os.getenv("CHAOS_MESH_NAMESPACE", "chaos-mesh")

# ── Prometheus ────────────────────────────────────────────────────────────────
PROMETHEUS_URL      = os.getenv("PROMETHEUS_URL", "http://localhost:9090")

# SLI thresholds — Sentinel raises an alert if these are breached
SLI_ERROR_RATE_THRESHOLD   = 0.05   # 5%  HTTP 5xx rate
SLI_LATENCY_P99_MS         = 2000   # 2 s p99 latency
SLI_POD_RESTART_THRESHOLD  = 3      # restarts in the last 5 min

# ── Chaos Mesh ────────────────────────────────────────────────────────────────
CHAOS_EXPERIMENTS_DIR = os.path.join(os.path.dirname(__file__), "../chaos/experiments")

# Catalogue of injectable experiments (name → yaml file)
CHAOS_EXPERIMENT_CATALOGUE = {
    "pod_kill":      "pod_kill.yaml",
    "network_delay": "network_delay.yaml",
    "cpu_stress":    "cpu_stress.yaml",
}

# Microservices in Online Boutique that are valid chaos targets
CHAOS_TARGET_SERVICES = [
    "cartservice",
    "productcatalogservice",
    "currencyservice",
    "paymentservice",
    "shippingservice",
    "recommendationservice",
    "checkoutservice",
    "frontend",
]

# ── Agent loop ────────────────────────────────────────────────────────────────
MAX_CHAOS_ROUNDS             = int(os.getenv("MAX_CHAOS_ROUNDS", 3))
RECOVERY_TIMEOUT_SECONDS     = int(os.getenv("RECOVERY_TIMEOUT_SECONDS", 120))
SENTINEL_POLL_INTERVAL       = int(os.getenv("SENTINEL_POLL_INTERVAL_SECONDS", 10))
