"""
main.py
Entry point for the Autonomous Chaos Engineering system.

LangGraph state machine:
  [START]
     │
     ▼
  adversary  ──▶  sentinel  ──▶  remediation (if degraded/critical)
     ▲                │                │
     │                └──── healthy ───┘
     │                         │
     └──── next round ─────────┘
     │
  [END] (after MAX_CHAOS_ROUNDS)

Run:
  source chaos-env/bin/activate
  python main.py
"""

import json
import time
from langgraph.graph import StateGraph, END
from typing import TypedDict, Any

from agents.adversary_agent    import adversary_node
from agents.sentinel_agent     import sentinel_node
from agents.remediation_agent  import remediation_node
from utils.k8s_client          import K8sClient
from chaos.chaos_client        import ChaosMeshClient
from config.settings           import MAX_CHAOS_ROUNDS


# ── Shared state schema ───────────────────────────────────────────────────────

class ChaosState(TypedDict):
    round:                int
    phase:                str
    cluster_snapshot:     dict
    chaos_history:        list
    last_injection:       dict
    sentinel_assessment:  dict
    sli_readings:         list
    remediation_record:   dict
    experiment_log:       list


# ── Router: decides the next node based on state["phase"] ────────────────────

def route(state: ChaosState) -> str:
    phase     = state.get("phase", "attack")
    round_num = state.get("round", 1)

    if phase == "monitor":
        return "sentinel"

    if phase == "remediate":
        return "remediation"

    if phase == "next_round":
        if round_num >= MAX_CHAOS_ROUNDS:
            return END
        # Route through prepare so it increments round + refreshes snapshot
        return "prepare"

    return END


# ── Pre-node: refresh cluster snapshot and bump round ────────────────────────

def prepare_round(state: ChaosState) -> ChaosState:
    """Refresh cluster state at the start of each round."""
    k8s = K8sClient()
    round_num = state.get("round", 0) + 1
    print(f"\n{'='*60}")
    print(f"  ROUND {round_num} of {MAX_CHAOS_ROUNDS}")
    print(f"{'='*60}")
    snapshot = k8s.cluster_snapshot()
    return {
        **state,
        "round":            round_num,
        "phase":            "attack",
        "cluster_snapshot": snapshot,
    }


# ── Build the LangGraph ───────────────────────────────────────────────────────

def build_graph() -> Any:
    graph = StateGraph(ChaosState)

    # Nodes
    graph.add_node("prepare",     prepare_round)
    graph.add_node("adversary",   adversary_node)
    graph.add_node("sentinel",    sentinel_node)
    graph.add_node("remediation", remediation_node)

    # Edges
    graph.set_entry_point("prepare")
    graph.add_edge("prepare", "adversary")

    # Conditional routing after each agent.
    # The path map tells LangGraph every possible return value of route().
    path_map = {
        "sentinel":    "sentinel",
        "remediation": "remediation",
        "prepare":     "prepare",   # next_round goes back through prepare to bump counter
        END:           END,
    }
    graph.add_conditional_edges("adversary",   route, path_map)
    graph.add_conditional_edges("sentinel",    route, path_map)
    graph.add_conditional_edges("remediation", route, path_map)

    return graph.compile()


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print("\n🌪️  Autonomous Chaos Engineering System — Starting\n")
    print(f"   Max rounds : {MAX_CHAOS_ROUNDS}")
    print(f"   LLM model  : claude-sonnet-4-6")
    print()

    # Safety: clear any leftover chaos experiments before starting
    chaos = ChaosMeshClient()
    chaos.cleanup_all()
    time.sleep(3)

    # Initial state
    initial_state: ChaosState = {
        "round":               0,
        "phase":               "attack",
        "cluster_snapshot":    {},
        "chaos_history":       [],
        "last_injection":      {},
        "sentinel_assessment": {},
        "sli_readings":        [],
        "remediation_record":  {},
        "experiment_log":      [],
    }

    # Build and run the graph
    app    = build_graph()
    result = app.invoke(initial_state)

    # ── Final report ──────────────────────────────────────────────────────────
    print("\n" + "="*60)
    print("  EXPERIMENT COMPLETE")
    print("="*60)
    print(f"  Rounds completed : {result.get('round', 0)}")
    print(f"  Injections made  : {len(result.get('chaos_history', []))}")
    print()
    print("Chaos history:")
    for entry in result.get("chaos_history", []):
        status = "✅" if entry.get("success") else "❌"
        print(f"  {status} Round {entry['round']}: {entry['experiment']} "
              f"on {entry['target']} — {entry['reason']}")

    # Save full log to file
    log_path = "logs/experiment_results.json"
    with open(log_path, "w") as f:
        json.dump(result, f, indent=2, default=str)
    print(f"\nFull log saved to: {log_path}")

    # Final safety cleanup
    chaos.cleanup_all()


if __name__ == "__main__":
    main()
