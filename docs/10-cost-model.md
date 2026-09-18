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
  Per-incident estimate: ~15–30 K tokens ⇒ **~$0.001–$0.005 per incident**. **Measured (spike-01 +
  M3 eval, 2026-09-17):** real runs ran 43.5–56.2 K tokens/incident, above this estimate, but cost
  stayed in the $0.0018–0.0019 band (still inside the $0.001–0.005 target) because GLM-Flash-class
  cache-read pricing absorbed the token overshoot — see `docs/spikes/spike-01-prime-agent-headless.md`
  Finding 6. Budget by the token estimate loosely; the cost estimate held up in practice.
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
| DB | Aurora Serverless v2, 0.5 ACU floor | Cloud SQL, smallest custom tier | PG Flexible, B1ms burstable |
| **Idle/mo** | **~$50–65** (Aurora floor + EFS/S3) | **~$55–75** (Cloud SQL floor; excl. Filestore) | **~$20–40** (PG Flexible + Files) |

> **DB idle floor correction (M6, realizing the Terraform surfaced this):** this row previously
> said "Aurora Serverless v2 (paused)" / "Cloud SQL Serverless" -- both wrong. Aurora Serverless
> **v1** could auto-pause to ~$0; **v2** (what `deploy/terraform/environments/aws/db.tf` actually
> provisions, since v1 doesn't support PostgreSQL in most regions) has no pause capability, only a
> minimum-ACU floor that runs continuously (~$0.12/ACU-hr, so 0.5 ACU ≈ $44/mo before storage).
> GCP Cloud SQL has no "serverless" product at all -- only fixed/custom machine tiers that run
> continuously; `db-custom-1-3840` (1 vCPU/3.75 GB, what `environments/gcp/main.tf` provisions) is
> the smallest viable size, not free when idle. Azure's PostgreSQL Flexible Server Burstable tier
> (`B_Standard_B1ms`, what `environments/azure/main.tf` provisions) is genuinely the cheapest of
> the three -- burstable CPU credits, not scale-to-zero, but a real, small always-on floor rather
> than a large one. None of the three clouds offers a true $0-when-idle managed Postgres; this is
> a real constraint of "always-on relational DB," not a gap specific to one cloud. Figures above
> are reasoned estimates from each provider's published per-unit pricing, not measured spend (no
> environment here is ever applied, per ADR-004) -- treat them as directional, not exact.

> **GCP Filestore caveat:** Filestore BASIC_HDD has a 1 TiB minimum (~$180/mo) which breaks the
> scale-to-zero idle claim. The GCP guide documents alternatives (smallest Zonal tier, or
> harness state on GCS via gcsfuse with cold-start resync). Until chosen, treat GCP idle as
> ~$235–255/mo if Filestore is used as drawn (the ~$55-75/mo Cloud SQL floor above, plus
> Filestore's ~$180/mo), ~$55–75/mo otherwise (Cloud SQL floor only, once Filestore is swapped
> for the gcsfuse alternative).

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
