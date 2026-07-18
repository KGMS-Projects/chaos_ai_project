"""
agents/adversary_agent.py

Adversary Agent — Phase 5
─────────────────────────
Decides WHAT chaos to inject and WHERE, then calls Chaos Mesh to do it.

Responsibilities:
  1. Receives the current cluster snapshot as context.
  2. Uses an LLM (Claude) to choose an experiment + target service.
  3. Applies the chosen experiment via ChaosMeshClient.
  4. Returns an updated LangGraph state with the injection record.
"""

import json
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage
from chaos.chaos_client import ChaosMeshClient
from config.settings import (
    ANTHROPIC_API_KEY,
    LLM_MODEL,
    LLM_TEMPERATURE,
    CHAOS_EXPERIMENT_CATALOGUE,
    CHAOS_TARGET_SERVICES,
)


# ── LLM setup ─────────────────────────────────────────────────────────────────

llm = ChatAnthropic(
    model=LLM_MODEL,
    temperature=LLM_TEMPERATURE,
    anthropic_api_key=ANTHROPIC_API_KEY,
)

chaos_client = ChaosMeshClient()

# ── System prompt ─────────────────────────────────────────────────────────────

ADVERSARY_SYSTEM_PROMPT = """
You are the Adversary Agent in a chaos engineering system.
Your job is to select the next fault injection experiment to test system resilience.

Available experiments:
- pod_kill      : Kills one pod of a target service (tests restart recovery)
- network_delay : Adds 500ms latency to a service (tests timeout handling)
- cpu_stress    : Maxes out CPU on a service (tests resource throttling)

Available target services:
{services}

Rules:
- Do NOT target the same service twice in a row (check history).
- Prefer services that have NOT been tested yet.
- Vary the experiment type — don't only kill pods.
- Respond ONLY with valid JSON in this exact format:
  {{"experiment": "<name>", "target": "<service>", "reason": "<one sentence>"}}
- No extra text, no markdown, no code fences.
""".format(services="\n".join(f"  - {s}" for s in CHAOS_TARGET_SERVICES))


# ── Agent node (called by LangGraph) ─────────────────────────────────────────

def adversary_node(state: dict) -> dict:
    """
    LangGraph node function for the Adversary agent.

    Args:
        state: LangGraph shared state dict containing:
               - cluster_snapshot (dict)
               - chaos_history    (list of past injections)
               - round            (int, current round number)

    Returns:
        Updated state with 'last_injection' populated.
    """
    print("\n[AdversaryAgent] 🎯 Deciding next chaos experiment...")

    cluster_snapshot = state.get("cluster_snapshot", {})
    chaos_history    = state.get("chaos_history", [])
    round_num        = state.get("round", 1)

    # Build the user message with current context
    user_message = f"""
Current cluster state (round {round_num}):
{json.dumps(cluster_snapshot, indent=2)}

Previous injections (do not repeat same service/experiment back-to-back):
{json.dumps(chaos_history[-3:], indent=2) if chaos_history else "None yet"}

Choose the next chaos experiment to inject.
"""

    # Call the LLM
    try:
        response = llm.invoke([
            SystemMessage(content=ADVERSARY_SYSTEM_PROMPT),
            HumanMessage(content=user_message),
        ])
        raw = response.content.strip()

        # Strip markdown fences if present (defensive)
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]

        decision = json.loads(raw)
        experiment = decision["experiment"]
        target     = decision["target"]
        reason     = decision["reason"]

    except (json.JSONDecodeError, KeyError) as e:
        # Fallback if LLM returns unexpected format
        print(f"[AdversaryAgent] LLM parse error ({e}), using fallback.")
        experiment = "pod_kill"
        target     = "cartservice"
        reason     = "Fallback: default experiment"

    print(f"[AdversaryAgent] → Injecting '{experiment}' on '{target}': {reason}")

    # Apply the chaos experiment
    success = chaos_client.inject(experiment, target)

    # Record the injection in history
    injection_record = {
        "round":      round_num,
        "experiment": experiment,
        "target":     target,
        "reason":     reason,
        "success":    success,
    }

    return {
        **state,
        "last_injection": injection_record,
        "chaos_history":  chaos_history + [injection_record],
        "phase":          "monitor",   # signal next node: Sentinel
    }
