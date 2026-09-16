# 10 — Cost Model

Design principle: **$0 is the default state of every environment.** Video never leaves the LAN;
cloud spend exists only if someone deliberately provisions it (and the reference architecture
exists precisely so they don't have to).

## 1. Development (actual spend: ~$0 + LLM)

| Item | Approach | Cost |
| --- | --- | --- |
| Compute | Local workstation GPU | $0 |
| Streaming | MediaMTX looping MP4s | $0 |
| Broker/DB | Redis + Postgres in Docker | $0 |
| Vision models | open weights, local TensorRT | $0 |
| LLM calls | tier-1 flash/free models; T3 escalation only | **$3–$10 one-off during dev** |

## 2. LLM Spend Mechanics

- Trigger gating: LLM touches only TriggerEvents (< 5 per 10-min clip), never frames.
- Tier-1 workers (GLM-Flash class): ~$0.08–$0.15/M input tokens (or free endpoints).
  Per-incident estimate: ~15–30 K tokens ⇒ **~$0.001–$0.005 per incident**.
- Prompt caching: identical harness/system prompts across incidents ⇒ cache-hit pricing on
  recurrent tokens.
- Heartbeats: watchdog at 60 s with tiny contexts on free tier ⇒ ~$0. **Deployment-specific
  assumption:** on paid-only providers this is ~1.4 k calls/day of tiny contexts — flag it in the
  runbooks and prefer free-tier endpoints for T2.
- Escalations (tier-3): ≤ 15% of incidents by target, adds ≤ ~$0.02/incident worst case.

**Hard caps:** `--autonomous-max-turns 8`, `--autonomous-max-tokens 50000`,
`--autonomous-timeout-ms 120000` per incident (verified prime-agent flags); per-day incident
budget alarm in `worker.py` (e.g., 500 incidents/day ⇒ pause queue + page).

## 3. Portfolio Demo Hosting ($0/mo pattern)

"Simulated live": run heavy inference locally once; dump tracklets/telemetry to timestamped
fixtures; cloud backend replays them over WebSockets on demand. "Trigger Incident Audit" is an
on-demand agent call: fractions of a cent per click.

| Component | Tool | Cost |
| --- | --- | --- |
| Dashboard UI | Vercel / Cloudflare Pages | $0 |
| Replay API | Cloud Run / Fly.io scale-to-zero | $0–$2/mo |
| Telemetry | Upstash Redis free tier | $0 |
| DB | Neon Postgres free tier | $0 |
| Video | none (replay fixtures) | $0 |

## 4. Reference Architecture BOM (documented, not provisioned)

Scenario A — Staging/idle (scale-to-zero):

| | AWS | GCP | Azure |
| --- | --- | --- | --- |
| Agent compute | Fargate 0.5 task, on-demand ~$0.05/h while processing | Cloud Run scale-to-zero | Container Apps scale-to-zero |
| Broker | SQS (per-request) | Pub/Sub | Service Bus basic |
| Storage | EFS + S3 (GBs) | Filestore + GCS | Azure Files + Blob |
| DB | Aurora Serverless v2 (paused) | Cloud SQL Serverless | PG Flexible (burst) |
| **Idle/mo** | **~$5–15** (EFS+storage floor) | **~$5–10** (see Filestore note) | **~$5–15** |

> **GCP Filestore caveat:** Filestore BASIC_HDD has a 1 TiB minimum (~$180/mo) which breaks the
> scale-to-zero idle claim. The GCP guide documents alternatives (smallest Zonal tier, or
> harness state on GCS via gcsfuse with cold-start resync). Until chosen, treat GCP idle as
> ~$185–240/mo if Filestore is used as drawn, ~$5–10 otherwise.

Scenario B — Production-style (10 continuous streams, edge GPU on-prem, cloud slow path):

| | Est./mo | Notes |
| --- | --- | --- |
| Cloud agent compute | ~$10–30 | queue-driven, not always-on |
| Broker + DB + storage | ~$40–80 | MSK/PubSub-Pro tier drives the delta |
| Egress | ~$0 | video stays on edge; telemetry JSON only |
| LLM (10 sites × 200 incidents/day, tier-1) | **~$20–60** | with caching + escalation caps |
| **Scenario B total** | **~$70–170** | LLM + infra combined (storage/DB/broker floor included) |

## 5. Billing Guardrails (for anyone who does provision)

1. Budgets with alerts at $5 and $15 (AWS Budgets / GCP Budget / Azure Cost Management), SMS+email.
2. All resources tagged `ttl=4h`, `project=sitewatch-ai`; scheduled `aws-nuke`/script teardown.
3. `terraform apply` commented in runbooks with COST WARNING blocks; `destroy` documented first.
4. Auto-shutdown Lambda/Function if spend > $20 in cycle (documented pattern).
5. No NAT gateways (top surprise-bill source) — VPC endpoints/private egress documented instead.
