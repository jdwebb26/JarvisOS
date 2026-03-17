# ShadowBroker Deployment Contract

ShadowBroker is an external OSINT sidecar for Jarvis 5.2.

Jarvis uses it for:
- evidence-backed operator visibility
- world-ops sidecar collection
- research support

ShadowBroker is not:
- runtime truth
- approval truth
- promotion truth
- routing legality truth

## Required environment

- `JARVIS_SHADOWBROKER_BASE_URL`
- `JARVIS_SHADOWBROKER_API_KEY` (if the service requires auth)
- `JARVIS_SHADOWBROKER_TIMEOUT_SECONDS`
- `JARVIS_SHADOWBROKER_VERIFY_SSL`

Optional:
- `JARVIS_SHADOWBROKER_STALE_SNAPSHOT_SECONDS`

## Expected endpoint shape

Health endpoint:
- `GET <base_url>/healthz`
- healthy when HTTP status is `< 400`

Snapshot endpoint:
- `GET <base_url>/snapshot`
- expected payload:

```json
{
  "snapshot_id": "shadowbroker_snapshot_123",
  "events": [
    {
      "event_id": "event_1",
      "title": "Example event",
      "summary": "Example summary",
      "region": "global",
      "event_type": "threat_intel",
      "risk_posture": "medium",
      "url": "https://example.invalid/event/1"
    }
  ]
}
```

`events` must be a list. Jarvis will classify malformed payloads as degraded and will not fabricate success.

## Runtime statuses

- `blocked_shadowbroker_not_configured`
- `blocked_shadowbroker_invalid_config`
- `degraded_shadowbroker_unreachable`
- `degraded_shadowbroker_bad_payload`
- `healthy`

## What blocked and degraded mean

`blocked_shadowbroker_not_configured`
- no base URL configured
- Jarvis sidecar remains available, but ShadowBroker-backed coverage is unavailable

`blocked_shadowbroker_invalid_config`
- base URL or timeout config is invalid
- fix local deployment config before operator use

`degraded_shadowbroker_unreachable`
- service cannot be reached or health check fails
- do not claim live ShadowBroker coverage

`degraded_shadowbroker_bad_payload`
- endpoint responded, but the snapshot contract was malformed
- do not trust the feed until the upstream payload is fixed

## What Jarvis can still do without ShadowBroker

Jarvis can still:
- run repo-native tasking
- preserve approvals/promotions/routing policy
- use other sidecar inputs such as RSS/Atom and SearXNG if configured

Jarvis must not claim:
- real-time global coverage
- healthy ShadowBroker coverage
- operator-ready ShadowBroker lane

unless config and health checks are actually green now.

## How to verify

Bootstrap:
- `python3 scripts/bootstrap.py`

Validate:
- `python3 scripts/validate.py`

Smoke:
- `python3 scripts/smoke_test.py`

Focused checks:
- doctor report includes a `shadowbroker:` line
- `shadowbroker_summary` in status/state export/operator snapshot reflects:
  - configured
  - healthy
  - backend status
  - latest snapshot age
  - latency
  - recent event counts
  - degraded reason when not healthy
