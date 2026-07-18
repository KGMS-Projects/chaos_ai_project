"""
agents/remediation_agent.py

Remediation Agent — Phase 5
────────────────────────────
Takes corrective action when the Sentinel flags degraded or critical health.

Responsibilities:
  1. Receives the Sentinel's assessment + cluster snapshot.
  2. Uses an LLM to pick the best remediation action.
  3. Executes the action via K8sClient.
  4. Verifies recovery after action.
  5. Returns updated state with remediation record.
"""

import json
import time
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage
from utils.k8s_client import K8sClient
from utils.prometheus_client import PrometheusClient
from chaos.chaos_client import ChaosMeshClient
from config.settings import (
    ANTHROPIC_API_KEY,
    LLM_MODEL,
    LLM_TEMPERATURE,
    TARGET_NAMESPACE,
    SLI_ERROR_RATE_THRESHOLD,
    SLI_LATENCY_P99_MS,
    SLI_POD_RESTART_THRESHOLD,
)


# ── Clients ───────────────────────────────────────────────────────────────────

llm          = ChatAnthropic(
    model=LLM_MODEL,
    temperature=LLM_TEMPERATURE,
    anthropic_api_key=ANTHROPIC_API_KEY,
)
k8s          = K8sClient()
prom         = PrometheusClient()
chaos_client = ChaosMeshClient()

# ── System prompt ─────────────────────────────────────────────────────────────

REMEDIATION_SYSTEM_PROMPT = """
You are the Remediation Agent in a chaos engineering system.
Your job is to choose and execute the most appropriate healing action
for a Kubernetes cluster that has been degraded by a chaos experiment.

Available remediation actions:
  - restart_pod         : Delete a specific pod (Kubernetes restarts it)
  - restart_deployment  : Rolling restart of an entire deployment
  - scale_up            : Temporarily scale a deployment to 2 replicas
  - cleanup_chaos       : Remove the active chaos experiment (stop the fault)
  - no_action           : System is recovering on its own; wait

Decision rules:
  1. If the chaos experiment is still active, ALWAYS cleanup_chaos first.
  2. If pods are CrashLoopBackOff, use restart_deployment.
  3. If SLIs are breached but pods look fine, try cleanup_chaos + wait.
  4. Scale up only if restart fails to restore health within 60 seconds.

Respond ONLY with valid JSON:
  {{
    "actions": ["<action1>", "<action2>"],
    "target_service": "<service name or null>",
    "rationale": "<two sentences max>"
  }}
Actions should be ordered — they will be executed in sequence.
"""


# ── Action executor ───────────────────────────────────────────────────────────

def execute_action(action: str, target_service: str | None) -> bool:
    """Execute a single remediation action. Returns True on success."""
    print(f"  [Remediation] Executing: {action}" +
          (f" on {target_service}" if target_service else ""))

    if action == "cleanup_chaos":
        return chaos_client.cleanup()

    if action == "restart_pod":
        if not target_service:
            print("  [Remediation] No target service for restart_pod; skipping.")
            return False
        pod_names = k8s.get_pod_names_for_service(target_service)
        if not pod_names:
            return False
        return k8s.delete_pod(pod_names[0])

    if action == "restart_deployment":
        if not target_service:
            return False
        return k8s.restart_deployment(target_service)

    if action == "scale_up":
        if not target_service:
            return False
        return k8s.scale_deployment(target_service, replicas=2)

    if action == "no_action":
        print("  [Remediation] No action taken — monitoring recovery passively.")
        return True

    print(f"  [Remediation] Unknown action: {action}")
    return False


# ── Agent node (called by LangGraph) ─────────────────────────────────────────

def remediation_node(state: dict) -> dict:
    """
    LangGraph node for the Remediation agent.
    Called when Sentinel verdict is 'degraded' or 'critical'.
    """
    print("\n[RemediationAgent] 🔧 Starting remediation...")

    assessment     = state.get("sentinel_assessment", {})
    last_injection = state.get("last_injection", {})
    cluster_snap   = k8s.cluster_snapshot()
    unhealthy_pods = k8s.get_unhealthy_pods()

    user_message = f"""
Sentinel assessment:
{json.dumps(assessment, indent=2)}

Last chaos injection:
{json.dumps(last_injection, indent=2)}

Current cluster snapshot:
{json.dumps(cluster_snap, indent=2)}

Unhealthy pods right now:
{json.dumps(unhealthy_pods, indent=2)}

Decide the remediation action sequence.
"""

    # ── LLM decides the action plan ───────────────────────────────────────────
    try:
        response = llm.invoke([
            SystemMessage(content=REMEDIATION_SYSTEM_PROMPT),
            HumanMessage(content=user_message),
        ])
        raw = response.content.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        plan = json.loads(raw)
    except (json.JSONDecodeError, KeyError) as e:
        print(f"[RemediationAgent] LLM parse error ({e}), using safe fallback.")
        plan = {
            "actions":        ["cleanup_chaos", "restart_deployment"],
            "target_service": last_injection.get("target"),
            "rationale":      "Fallback plan: clean up chaos then restart deployment.",
        }

    actions        = plan.get("actions", [])
    target_service = plan.get("target_service")
    rationale      = plan.get("rationale", "")

    print(f"[RemediationAgent] Plan: {actions} on '{target_service}'")
    print(f"[RemediationAgent] Rationale: {rationale}")

    # ── Execute actions in sequence ───────────────────────────────────────────
    results = []
    for action in actions:
        ok = execute_action(action, target_service)
        results.append({"action": action, "success": ok})
        time.sleep(5)   # brief pause between sequential actions

    # ── Verify recovery ───────────────────────────────────────────────────────
    print("[RemediationAgent] ⏳ Waiting 30s for pods to stabilise...")
    time.sleep(30)

    healthy, slis = prom.is_healthy(
        error_rate_threshold=SLI_ERROR_RATE_THRESHOLD,
        latency_threshold_ms=SLI_LATENCY_P99_MS,
        restart_threshold=SLI_POD_RESTART_THRESHOLD,
        namespace=TARGET_NAMESPACE,
    )

    status = "recovered" if healthy else "still_degraded"
    print(f"[RemediationAgent] Post-remediation status: {status.upper()}")

    remediation_record = {
        "round":          state.get("round", 1),
        "plan":           plan,
        "actions_taken":  results,
        "post_slis":      slis,
        "status":         status,
    }

    return {
        **state,
        "remediation_record": remediation_record,
        "phase":              "next_round",
    }
