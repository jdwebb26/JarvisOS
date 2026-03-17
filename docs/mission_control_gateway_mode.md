# Mission Control Gateway Mode

Mission Control is an operator-side read model. Jarvis/OpenClaw remains the source of truth for execution, approvals, tasks, sessions, routing, and runtime state.

## Local install on this machine

- Install path: `/tmp/mission-control`
- Startup command:

```bash
cd /tmp/mission-control
PORT=3010 pnpm dev
```

## Env required for this machine

The verified local `.env` uses:

```bash
PORT=3010
AUTH_USER=admin
AUTH_PASS=JarvisMissionControl-2026-03-14
API_KEY=mc_local_jarvis_20260314_live
MC_ALLOWED_HOSTS=localhost,127.0.0.1
OPENCLAW_HOME=/home/rollan/.openclaw
OPENCLAW_GATEWAY_HOST=127.0.0.1
OPENCLAW_GATEWAY_PORT=18792
OPENCLAW_GATEWAY_TOKEN=<from ~/.openclaw/openclaw.json>
OPENCLAW_MEMORY_DIR=/home/rollan/.openclaw/workspace/jarvis-v5/state/logs
NEXT_PUBLIC_GATEWAY_HOST=127.0.0.1
NEXT_PUBLIC_GATEWAY_PORT=18792
NEXT_PUBLIC_GATEWAY_CLIENT_ID=openclaw-control-ui
```

`OPENCLAW_MEMORY_DIR` is the important Jarvis-side operator bridge. It makes Mission Control's Memory Browser read the live Jarvis `state/logs` folder directly, so operator snapshot, handoff, state export, doctor, validate, and smoke outputs stay source-owned.

## Jarvis read-model sync

Mission Control's task/review/activity surfaces are sqlite-backed. They do not natively read Jarvis JSON state, so use the one-way sync:

```bash
cd /home/rollan/.openclaw/workspace/jarvis-v5
python3 scripts/mission_control_sync.py \
  --mission-control-root /tmp/mission-control \
  --knowledge-base-dir /tmp/mission-control/.data/jarvis-read-model
```

What it does:

- rebuilds live Jarvis read-model JSON
- projects `task_board.json` into Mission Control `tasks`
- projects pending review/approval work into Mission Control `notifications` and `activities`
- projects distinct backends/reviewers into Mission Control `agents`
- mirrors key Jarvis JSON into a knowledge folder for debugging

This sync is read-only with respect to Jarvis/OpenClaw. Mission Control becomes a convenience projection, not the authority.

## What is live after sync

- Task board:
  - Source: `state/logs/task_board.json`
  - Mission Control surface: `/api/tasks`
- Review inbox / approvals:
  - Source: `state/logs/review_inbox.json`
  - Mission Control surfaces: `/api/notifications`, `/api/activities`
- Operator snapshot / handoff / state export:
  - Source: `state/logs/operator_snapshot.json`, `state/logs/operator_handoff_pack.json`, `state/logs/state_export.json`
  - Mission Control surface: Memory Browser via `OPENCLAW_MEMORY_DIR`
- Sessions / channel activity:
  - Source: live OpenClaw gateway plus `~/.openclaw/agents/jarvis/sessions`
  - Mission Control surfaces: `/api/sessions`, `/api/channels`
- Runtime health / doctor / validation:
  - Source: gateway health plus `state/logs/doctor_report.json`, `state/logs/validate_report.json`, `state/logs/smoke_test_report.json`
  - Mission Control surfaces: `/api/diagnostics`, `/api/status?action=overview`, Memory Browser

## Verification

Gateway connectivity:

```bash
curl -sS -H 'x-api-key: mc_local_jarvis_20260314_live' \
  http://127.0.0.1:3010/api/diagnostics
```

Expected:

- `gateway.configured = true`
- `gateway.reachable = true`

Task projection:

```bash
curl -sS -H 'x-api-key: mc_local_jarvis_20260314_live' \
  'http://127.0.0.1:3010/api/tasks?limit=5'
```

Review/approval projection:

```bash
curl -sS -H 'x-api-key: mc_local_jarvis_20260314_live' \
  'http://127.0.0.1:3010/api/notifications?recipient=anton'
curl -sS -H 'x-api-key: mc_local_jarvis_20260314_live' \
  'http://127.0.0.1:3010/api/notifications?recipient=operator'
```

Operator snapshot via memory browser:

```bash
curl -sS -H 'x-api-key: mc_local_jarvis_20260314_live' \
  'http://127.0.0.1:3010/api/memory?action=content&path=operator_snapshot.json'
```

Sessions / channels:

```bash
curl -sS -H 'x-api-key: mc_local_jarvis_20260314_live' \
  http://127.0.0.1:3010/api/sessions
curl -sS -H 'x-api-key: mc_local_jarvis_20260314_live' \
  http://127.0.0.1:3010/api/channels
```

## Known limits

- The task/review projection is one-way and refresh-on-sync, not streaming.
- Mission Control's native task editing remains its own surface; do not treat it as authoritative for Jarvis task state.
- Browser action state, autoresearch outputs, routing/provider visibility, and doctor/smoke details are source-owned in Jarvis logs and should be inspected through the Memory Browser or the mirrored JSON, not rewritten into Mission Control-local authority tables.
