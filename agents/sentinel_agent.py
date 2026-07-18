"""
agents/sentinel_agent.py

Sentinel Agent — Phase 5
────────────────────────
Continuously monitors Prometheus SLIs after a chaos injection
and decides whether the system has recovered or needs remediation.

Responsibilities:
  1. Polls Prometheus every N seconds for SLI metrics.
  2. Uses an LLM to interpret the metrics and classify system health.
  3. Returns verdict: "healthy" | "degraded" | "critical"
  4. Signals the LangGraph loop to continue, remediate, or finish.
"""

import time
import json
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage
from utils.prometheus_client import PrometheusClient
from utils.k8s_client import K8sClient
from config.settings import (
    ANTHROPIC_API_KEY,
    LLM_MODEL,
    LLM_TEMPERATURE,
    SENTINEL_POLL_INTERVAL,
    RECOVERY_TIMEOUT_SECONDS,
    SLI_ERROR_RATE_THRESHOLD,
    SLI_LATENCY_P99_MS,
    SLI_POD_RESTART_THRESHOLD,
    TARGET_NAMESPACE,
)


# ── Clients ───────────────────────────────────────────────────────────────────

llm        = ChatAnthropic(
    model=LLM_MODEL,
    temperature=LLM_TEMPERATURE,
    anthropic_api_key=ANTHROPIC_API_KEY,
)
prom       = PrometheusClient()
k8s        = K8sClient()

# ── System prompt ─────────────────────────────────────────────────────────────

SENTINEL_SYSTEM_PROMPT = """
You are the Sentinel Agent in a chaos engineering system.
Your job is to analyse Prometheus SLI metrics and Kubernetes pod state,
then classify the system health after a chaos injection.

SLI thresholds (from system config):
  - HTTP error rate   : must be < {error_threshold:.0%}
  - P99 latency       : must be < {latency_threshold} ms
  - Pod restarts (5m) : must be < {restart_threshold}

Classify the system as one of:
  "healthy"   → all SLIs within threshold, pods recovering
  "degraded"  → 1–2 SLIs breached, system struggling but alive
  "critical"  → multiple SLIs breached, immediate remediation needed

Respond ONLY with valid JSON:
  {{"verdict": "<healthy|degraded|critical>", "summary": "<two sentences max>",
    "action": "<none|restart_pod|restart_deployment|scale_up>"}}
""".format(
    error_threshold=SLI_ERROR_RATE_THRESHOLD,
    latency_threshold=SLI_LATENCY_P99_MS,
    restart_threshold=SLI_POD_RESTART_THRESHOLD,
)


# ── Agent node (called by LangGraph) ─────────────────────────────────────────

def sentinel_node(state: dict) -> dict:
    """
    LangGraph node for the Sentinel agent.
    Polls until recovery or timeout, then returns a verdict.
    """
    print("\n[SentinelAgent] 👁️  Monitoring system health...")

    last_injection = state.get("last_injection", {})
    round_num      = state.get("round", 1)
    start_time     = time.time()
    readings       = []

    # ── Poll loop ─────────────────────────────────────────────────────────────
    while time.time() - start_time < RECOVERY_TIMEOUT_SECONDS:
        elapsed = int(time.time() - start_time)
        healthy, slis = prom.is_healthy(
            error_rate_threshold=SLI_ERROR_RATE_THRESHOLD,
            latency_threshold_ms=SLI_LATENCY_P99_MS,
            restart_threshold=SLI_POD_RESTART_THRESHOLD,
            namespace=TARGET_NAMESPACE,
        )
        pod_state = k8s.cluster_snapshot()
        readings.append({**slis, "elapsed_s": elapsed, "k8s_healthy": healthy})

        print(
            f"  [{elapsed:3d}s] error={slis['error_rate']:.1%}  "
            f"p99={slis['p99_latency_ms']:.0f}ms  "
            f"restarts={slis['pod_restarts']}  "
            f"{'✅' if healthy else '⚠️ '}"
        )

        if healthy:
            print(f"[SentinelAgent] ✅ System recovered after {elapsed}s")
            break

        time.sleep(SENTINEL_POLL_INTERVAL)

    # ── Ask LLM to interpret the readings ────────────────────────────────────
    user_message = f"""
Chaos injection that triggered this monitoring window:
{json.dumps(last_injection, indent=2)}

SLI readings during recovery window ({len(readings)} polls):
{json.dumps(readings, indent=2)}

Current Kubernetes cluster state:
{json.dumps(pod_state, indent=2)}

Classify system health and recommend an action.
"""

    try:
        response = llm.invoke([
            SystemMessage(content=SENTINEL_SYSTEM_PROMPT),
            HumanMessage(content=user_message),
        ])
        raw = response.content.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        assessment = json.loads(raw)
    except (json.JSONDecodeError, KeyError) as e:
        print(f"[SentinelAgent] LLM parse error ({e}), defaulting to degraded.")
        assessment = {
            "verdict": "degraded",
            "summary": "Could not parse LLM response. Flagging for remediation.",
            "action":  "restart_pod",
        }

    verdict = assessment["verdict"]
    print(f"[SentinelAgent] Verdict: {verdict.upper()} — {assessment['summary']}")

    # Determine next phase
    next_phase = "remediate" if verdict in ("degraded", "critical") else "next_round"

    return {
        **state,
        "sentinel_assessment": assessment,
        "sli_readings":        readings,
        "phase":               next_phase,
    }
