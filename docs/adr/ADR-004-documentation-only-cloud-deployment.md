# ADR-004: Deliver Cloud as Validated IaC + Runbooks, Not Live Infrastructure

**Status:** Accepted

## Context
The goal is a portfolio demonstration of deployability, not an operated service. Always-on cloud
GPU (or even modest always-on agent infra) contradicts the cost principles; free-tier hosting covers
the public demo via telemetry replay.

## Decision
- Author complete Terraform for AWS (from the existing ECS Fargate + SQS + EFS spec), GCP, Azure.
- CI runs `terraform fmt -check` + `terraform validate` only. `apply` never runs in automation;
  runbooks show `plan` and keep `apply`/`destroy` commented with COST WARNING blocks.
- Public demo uses the simulated-live replay pattern (fixtures replayed over WebSockets).

**Built 2026-09-18 (M6):** `scripts/replay_demo.py` + `docker/docker-compose.replay.yml`
(`make replay-up`) -- postgres + api + ui + a pure-Python replay service, no GPU vision container
and no LLM call, verified end to end against a live Postgres/API. See docs/12-roadmap.md's M6 entry.

## Consequences
+ Zero cloud burn; multi-cloud literacy demonstrated; honest claims in README.
- No proof-by-execution of the cloud topology — mitigated by the local compose stack exercising the
  identical container images and contracts.
