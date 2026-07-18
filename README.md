# Autonomous Chaos Engineering with AI Agents
## Partial Implementation — Phases 3–5

### Project Overview
This project implements a closed-loop chaos engineering system using three AI agents
orchestrated via LangGraph. The system intentionally injects faults into a Kubernetes
cluster running Google Online Boutique, monitors system health via Prometheus, and
autonomously remediates failures.

---

### Architecture

```
┌─────────────────────────────────────────────────────┐
│                  LangGraph State Machine             │
│                                                      │
│  ┌──────────────┐   ┌──────────────┐   ┌──────────┐ │
│  │   Adversary  │──▶│  Remediation │──▶│ Sentinel │ │
│  │    Agent     │   │    Agent     │   │  Agent   │ │
│  └──────────────┘   └──────────────┘   └──────────┘ │
│         │                  │                 │        │
└─────────┼──────────────────┼─────────────────┼───────┘
          │                  │                 │
          ▼                  ▼                 ▼
    Chaos Mesh          kubectl /          Prometheus
    (fault inject)      Helm API           Metrics
```

---

### Phases Implemented

| Phase | Description | Status |
|-------|-------------|--------|
| Phase 1 | Prerequisites (Docker, kubectl, minikube, Helm) | ✅ Complete |
| Phase 2 | Kubernetes cluster + Online Boutique + Monitoring | ✅ Complete |
| Phase 3 | Chaos Mesh installation + first pod kill | ⚙️ In Progress |
| Phase 4 | Python venv + LangGraph + API keys | ⚙️ In Progress |
| Phase 5 | Adversary, Remediation, Sentinel agents | ⚙️ In Progress |
| Phase 6 | Full closed-loop Attack-Monitor-Heal loop | 🔜 Pending |

---

### Folder Structure

```
chaos_ai_project/
├── README.md
├── requirements.txt
├── .env.example
├── main.py                  # Entry point — runs the LangGraph loop
├── agents/
│   ├── adversary_agent.py   # Injects chaos via Chaos Mesh
│   ├── remediation_agent.py # Detects failures and heals
│   └── sentinel_agent.py    # Monitors Prometheus metrics
├── chaos/
│   ├── chaos_client.py      # Chaos Mesh API wrapper
│   └── experiments/
│       ├── pod_kill.yaml
│       ├── network_delay.yaml
│       └── cpu_stress.yaml
├── config/
│   └── settings.py          # Central config (namespaces, thresholds)
├── utils/
│   ├── prometheus_client.py # Prometheus query helpers
│   └── k8s_client.py        # Kubernetes API helpers
└── logs/
    └── .gitkeep
```

---

### Setup Instructions

#### 1. Prerequisites (already done in Phases 1–2)
```bash
minikube start
kubectl get pods   # verify Online Boutique is running
```

#### 2. Install Chaos Mesh (Phase 3)
```bash
helm repo add chaos-mesh https://charts.chaos-mesh.org
helm repo update
kubectl create ns chaos-mesh
helm install chaos-mesh chaos-mesh/chaos-mesh \
  --namespace chaos-mesh \
  --version 2.6.3 \
  --set chaosDaemon.runtime=docker \
  --set chaosDaemon.socketPath=/var/run/docker.sock
```

#### 3. Python environment (Phase 4)
```bash
python3 -m venv chaos-env
source chaos-env/bin/activate
pip install -r requirements.txt
```

#### 4. Configure API keys
```bash
cp .env.example .env
# Edit .env and add your API keys
```

#### 5. Run the agent system (Phase 5)
```bash
python main.py
```

---

### Environment Variables
See `.env.example` for all required keys.

---

### Agent Descriptions

**Adversary Agent** — Reads the current cluster state and decides which chaos
experiment to inject. Uses Chaos Mesh CRDs applied via kubectl. Targets: pod kills,
network delays, CPU stress.

**Remediation Agent** — Watches for pods in CrashLoopBackOff or Failed state and
takes corrective action: pod restarts, rollbacks, or scaling.

**Sentinel Agent** — Continuously queries Prometheus for key SLIs (error rate,
latency, pod restarts) and decides whether the system has recovered or needs
escalation.
