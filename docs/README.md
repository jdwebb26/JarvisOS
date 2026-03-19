# Jarvis OS v5.1 — Documentation

> Start here if you're looking for how the system works, how to operate it, or where to find a specific topic.

---

## Quick start

| What you want | Where to go |
|--------------|-------------|
| **Understand the whole system at a glance** | [System Overview](overview/OVERVIEW.md) &nbsp;/&nbsp; [HTML version](overview/index.html) |
| **Operate the system day-to-day** | [Operating Guide](OPERATING_GUIDE.md) |
| **First time running this repo** | [Operator First Run](operator-first-run.md) |
| **Check if deployment is ready** | [Go-Live Checklist](operator_go_live_checklist.md) |

---

## Core references

| Document | What it covers |
|----------|---------------|
| [System Overview](overview/OVERVIEW.md) | Architecture, agents, channels, quant system, what's live, what's partial |
| [Operating Guide](OPERATING_GUIDE.md) | Full operator manual — services, health tools, workflows, troubleshooting |
| [Operations](operations.md) | Operator scripts, reply grammar, action packs, recovery procedures |
| [Agent Roster](agent_roster.md) | Agent roles, tool allowlists, ACP status, specialization matrix |
| [Channel Policy](channels.md) | Discord channel routing rules, quant lane fallback wiring |
| [Review Policy](review-policy.md) | Archimedes/Anton review hierarchy, approval gates |
| [Deployment](deployment.md) | Service installation, systemd setup, validation sequence |
| [External Lane Activation](external_lane_activation.md) | Backend lane status labels and activation probes |

---

## Specs

| Document | What it covers |
|----------|---------------|
| [Master Spec](spec/Jarvis_OS_v5_1_Master_Spec.md) | Complete v5.1 technical specification — architecture, doctrine, lanes, provider policy |
| [Quant Lanes Spec](spec/QUANT_LANES_OPERATING_SPEC_v3.5.1.md) | Quant lane operating spec — Atlas, Fish, Sigma, Pulse, Kitt, Executor |
| [v5.1 Freeze Notes](spec/V5_1_FREEZE_NOTES.md) | Freeze summary, post-v5.1 boundaries |

---

## Operational notes

| Document | What it covers |
|----------|---------------|
| [Operator First Run](operator-first-run.md) | Shortest path from checkout to first live use |
| [Go-Live Checklist](operator_go_live_checklist.md) | Gate script for lane readiness |
| [Runtime Regression Runbook](runtime-regression-runbook.md) | How to run and interpret the regression pack |

---

## Channel semantics (quick reference)

| Channel | Role | What lands there |
|---------|------|-----------------|
| **#review** | Operator action inbox | Review requests, approval requests, paper-trade approvals, pulse proposals |
| **#worklog** | Audit trail | Review completed, approval completed, lifecycle receipts |
| **#jarvis** | Escalations only | Failures, blocked tasks, alerts, factory summaries, warnings |
| **#todo** | Task intake | Human messages become queued tasks |

Full channel→agent→webhook mapping: [`config/agent_channel_map.json`](../config/agent_channel_map.json)

---

*Jarvis OS v5.1 · OpenClaw v2026.3.13 · [GitHub](https://github.com/jdwebb26/JarvisOS)*
