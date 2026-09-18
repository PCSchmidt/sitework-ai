# Developer UX targets (docs/07 §4). Run from repo root.

COMPOSE := docker compose -f docker/docker-compose.yml

REPLAY_COMPOSE := docker compose -f docker/docker-compose.replay.yml

.PHONY: up down eval calib test iac report docs-check schema-export agent-eval tracking-eval replay-up replay-down

up:        ## docker compose up --build (full stack, simulated feeds)
	$(COMPOSE) up --build

down:      ## stop the local stack
	$(COMPOSE) down

replay-up:   ## $0 public demo stack: postgres + api + ui + fixture replay, no GPU/LLM (docs/12 M6)
	$(REPLAY_COMPOSE) up --build

replay-down: ## stop the replay demo stack
	$(REPLAY_COMPOSE) down

test:      ## unit + integration + contract tests
	uv run pytest

docs-check: ## M0.5 doc-consistency checks
	uv run python scripts/check_docs.py

schema-export: ## export Pydantic JSON Schemas to schemas/
	uv run python -m pipelines.schemas.export

eval:      ## headless benchmark + eval harness (GPU)
	uv run python evaluation/benchmark_models.py

agent-eval: ## run the seeded incident set against the real prime-agent CLI (docs/09 §3)
	uv run python -m evaluation.agent_eval

tracking-eval: ## MOTA/IDF1 on the MOT17 mirror (docs/09 §4, M5)
	uv run python -m evaluation.eval_tracking

calib:     ## launch manual homography calibration tool
	uv run python -m pipelines.geometry.calibrate

iac:       ## terraform fmt -check && validate for all three clouds
	@for env in aws gcp azure; do \
		terraform -chdir=deploy/terraform/environments/$$env fmt -check && \
		terraform -chdir=deploy/terraform/environments/$$env init -backend=false -input=false >/dev/null && \
		terraform -chdir=deploy/terraform/environments/$$env validate || exit 1; \
	done

report:    ## regenerate docs/benchmarks.md + shift-report samples
	uv run python evaluation/generate_report.py
