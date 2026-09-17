# 07 — Repository Layout, Conventions & CI

## 1. Layout

```text
sitework-ai/
├── PLAN.md                           # this planning suite's master plan
├── project_concepts_ideas.md         # original Gemini conversation (provenance)
├── docs/                             # architecture + deployment + ADR suite (see PLAN.md index)
│   ├── deployment/{aws,gcp,azure}-deployment-guide.md
│   ├── adr/ADR-00*.md
│   └── spikes/                       # time-boxed feasibility spikes (M3.0)
├── config/
│   ├── cameras.yaml                  # RTSP URLs / MediaMTX mock feeds
│   ├── zones.yaml                    # ground-plane polygons + rule bindings
│   └── rules.yaml                    # rule ids, descriptions, compliance citations
├── docker/
│   ├── Dockerfile.vision             # CUDA/TensorRT runtime, GStreamer, OpenCV
│   ├── Dockerfile.agent              # Node + Python 3.11, prime-agent, pinned version
│   ├── Dockerfile.web                # FastAPI backend
│   └── docker-compose.yml            # one-command local full stack
├── pipelines/
│   ├── ingestion/                    # MP4→RTSP streamer config, MediaMTX setup, frame source
│   ├── vision/                       # detector.py, tracker.py, rules.py, pipeline.py, evidence.py
│   ├── geometry/                     # homography, vanishing_point.py, calibrate.py (manual tool)
│   ├── broker/                       # Redis Streams retention/consumer-group hardening
│   └── schemas/                      # Pydantic v2 single source of truth
├── agent/
│   ├── worker.py                     # queue consumer, RPC driver, Band-3 gate wiring
│   ├── prime_adapter.py              # ALL prime-agent invocation (pin + contract test target)
│   ├── band3.py                      # recomputation cross-check gate (docs/06 §3)
│   ├── worker_fallback.py            # LiteLLM agent-loop fallback (ADR-005; not activated -- M3.0
│   │                                  # spike was a Conditional GO)
│   ├── prompts/                      # per-incident prompt templates (root_policy.md,
│   │                                  # trajectory_inspector.md, generic_classification.md)
│   └── harness/                      # sub-agent specs, memories (mounted into the agent
│                                      # container's non-root home, e.g. /home/node/.prime)
├── api/                              # FastAPI app (REST + WS), asyncpg
├── ui/                               # React + Vite + Tailwind dashboard, canvas site map
├── evaluation/
│   ├── benchmark_models.py           # FPS/latency/VRAM matrix
│   ├── eval_tracking.py              # MOTA/IDF1 vs ground truth
│   ├── build_seed_incidents.py       # generates the hand-labeled agent eval fixtures
│   ├── agent_eval.py                 # runs the seeded set against AgentWorker; scores pass rate
│   ├── fixtures/incidents/           # seeded TriggerEvent + tracks.jsonl + expected.json set
│   └── generate_report.py            # emits docs/benchmarks.md table
├── deploy/
│   ├── terraform/
│   │   ├── modules/                  # broker, container-service, storage, db
│   │   └── environments/{aws,gcp,azure}/   # main.tf, variables.tf, *.tfvars.example
│   └── helm/                         # optional cloud-agnostic K8s chart (stretch; descoped from M6)
├── assets/clips/                     # pinned demo clips + licenses
├── data/manifests/                   # dataset versions, licenses, SHA256
├── scripts/                          # check_docs.py, smoke_test.py, record_golden_session.py
├── tests/                            # unit / integration / contract tests; fixtures/ holds the
│                                      # captured golden prime-agent RPC session
└── .github/workflows/                # ci.yaml, iac-check.yaml, contract-agent.yaml, eval.yaml
                                       # (manual)
```

## 2. Conventions

- **Python 3.11+**, `uv` for env management, `ruff` (lint+format), `mypy` on `pipelines/` and
  `agent/` (`pyproject.toml`'s `[tool.mypy] files`), `pytest`.
- **TypeScript** (React dashboard): `pnpm`, eslint + prettier, vitest.
- **Schemas:** everything crossing a process boundary is a Pydantic model in `pipelines/schemas`;
  TS types generated from exported JSON Schema. No hand-rolled dicts across the boundary.
- **Agent invocation:** only `agent/prime_adapter.py` may touch prime-agent. Exact pinned version in
  `Dockerfile.agent`. Golden-session contract test guards upgrades. Local Windows/Git Bash dev runs
  the agent **only in its Linux container** (prime-agent install.sh targets macOS/Linux).
- **Base images:** pin patch-level tags (e.g. `python:3.11.11-slim-bookworm`,
  `node:22.11-bookworm-slim` -- bumped from an initial `node:20` guess once spike-01 found
  prime-agent's own `engines.node` requires `>=22.8.0`); upgrades are deliberate PRs, not `latest`
  drift.
- **Git:** conventional commits; main protected; PRs require green CI.

## 3. CI Workflows

| Workflow | Trigger | Jobs |
| --- | --- | --- |
| `ci.yaml` | PR/push | ruff + mypy + pytest (unit); ui lint/vitest; `docker compose config` validity; schema compat check |
| `iac-check.yaml` | PR touching `deploy/` | `terraform fmt -check` + `terraform validate` across aws/gcp/azure envs (no apply, ever) |
| `eval.yaml` | manual dispatch | headless benchmark run on self-hosted GPU runner; posts summary; artifact: `docs/benchmarks.md` diff |
| `contract-agent.yaml` | PR/push touching `agent/`, the contract test, or its fixtures | replays a real, captured `prime-agent` RPC transcript (`tests/fixtures/golden_prime_agent_session.jsonl`, `scripts/record_golden_session.py`) against `PrimeAdapter` (feasibility guard, F1). Does not drive the live CLI -- prime-agent still isn't installable in CI (private-registry gap, spike-01 Finding 1); this catches adapter-side regressions, not prime-agent protocol drift. Built 2026-09-17, after the M3 eval set closed M3 |

## 4. Make targets (developer UX)

```makefile
make up         # docker compose up --build (full stack, simulated feeds)
make eval       # headless benchmark + eval harness
make agent-eval # run the seeded incident set against the real prime-agent CLI (docs/09 §3)
make calib      # launch manual homography calibration tool
make test       # unit + integration + contract tests
make iac        # terraform fmt -check && validate for all three clouds
make report     # regenerate docs/benchmarks.md + shift-report samples
```
