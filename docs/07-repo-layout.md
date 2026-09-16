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
│   ├── vision/                       # detector.py, tracker.py, rules.py, pipeline.py
│   ├── geometry/                     # homography, calibrate.py (manual calibration tool)
│   └── schemas/                      # Pydantic v2 single source of truth
├── agent/
│   ├── worker.py                     # queue consumer, RPC driver
│   ├── prime_adapter.py              # ALL prime-agent invocation (pin + contract test target)
│   ├── worker_fallback.py            # LiteLLM agent-loop fallback (ADR-005)
│   ├── prompts/                      # operating policies for root + specialists
│   └── harness/                      # sub-agent specs, memories (mounted into /root/.prime)
├── api/                              # FastAPI app (REST + WS), asyncpg
├── ui/                               # React + Vite + Tailwind dashboard, canvas site map
├── evaluation/
│   ├── benchmark_models.py           # FPS/latency/VRAM matrix
│   ├── eval_tracking.py              # MOTA/IDF1 vs ground truth
│   └── generate_report.py            # emits docs/benchmarks.md table
├── deploy/
│   ├── terraform/
│   │   ├── modules/                  # broker, container-service, storage, db
│   │   └── environments/{aws,gcp,azure}/   # main.tf, variables.tf, *.tfvars.example
│   └── helm/                         # optional cloud-agnostic K8s chart (stretch; descoped from M6)
├── assets/clips/                     # pinned demo clips + licenses
├── data/manifests/                   # dataset versions, licenses, SHA256
├── tests/                            # unit / integration / contract tests
└── .github/workflows/                # ci.yaml, iac-check.yaml, eval.yaml (manual)
```

## 2. Conventions

- **Python 3.11+**, `uv` for env management, `ruff` (lint+format), `mypy` on `pipelines/schemas`
  and `agent/`, `pytest`.
- **TypeScript** (React dashboard): `pnpm`, eslint + prettier, vitest.
- **Schemas:** everything crossing a process boundary is a Pydantic model in `pipelines/schemas`;
  TS types generated from exported JSON Schema. No hand-rolled dicts across the boundary.
- **Agent invocation:** only `agent/prime_adapter.py` may touch prime-agent. Exact pinned version in
  `Dockerfile.agent`. Golden-session contract test guards upgrades. Local Windows/Git Bash dev runs
  the agent **only in its Linux container** (prime-agent install.sh targets macOS/Linux).
- **Base images:** pin patch-level tags (e.g. `python:3.11.11-slim-bookworm`,
  `node:20.18-bookworm-slim`); upgrades are deliberate PRs, not `latest` drift.
- **Git:** conventional commits; main protected; PRs require green CI.

## 3. CI Workflows

| Workflow | Trigger | Jobs |
| --- | --- | --- |
| `ci.yaml` | PR/push | ruff + mypy + pytest (unit); ui lint/vitest; `docker compose config` validity; schema compat check |
| `iac-check.yaml` | PR touching `deploy/` | `terraform fmt -check` + `terraform validate` across aws/gcp/azure envs (no apply, ever) |
| `eval.yaml` | manual dispatch | headless benchmark run on self-hosted GPU runner; posts summary; artifact: `docs/benchmarks.md` diff |
| `contract-agent.yaml` | PR touching `agent/` | golden RPC session replay against pinned prime-agent version (feasibility guard, F1). Created immediately after the M3.0 spike — the spike's golden session is the fixture |

## 4. Make targets (developer UX)

```makefile
make up      # docker compose up --build (full stack, simulated feeds)
make eval    # headless benchmark + eval harness
make calib   # launch manual homography calibration tool
make test    # unit + integration + contract tests
make iac     # terraform fmt -check && validate for all three clouds
make report  # regenerate docs/benchmarks.md + shift-report samples
```
