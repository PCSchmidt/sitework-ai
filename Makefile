# Developer UX targets (docs/07 §4). Run from repo root.

COMPOSE := docker compose -f docker/docker-compose.yml

REPLAY_COMPOSE := docker compose -f docker/docker-compose.replay.yml

.PHONY: up down eval calib test iac report docs-check schema-export agent-eval tracking-eval replay-up replay-down showcase showcase-agent

# Captions shown on each camera's card in the dashboard's Cameras tab (make showcase).
DOCK_NOTE = A forklift and a pedestrian share a warehouse floor. The camera is handheld and drifts up to 65 px, so every frame is motion-compensated back onto the frame the calibration was made on. Calibration: level-camera method (depth lines fit to 1.2 px); scale comes from the forklift's wheel track and the worker's height, so distances carry roughly +/-8% uncertainty.
AISLE_NOTE = A pedestrian walks through a forklift-only cross-aisle. Tripod shot with no floor lines to measure, so the calibration is deliberately unverified: it fails the 2 px quality gate and the camera runs in zone-only mode. Zone rules fire; distance and speed rules stay off rather than trusting estimated meters.
YARD_NOTE = A backhoe digging, filmed from a panning camera. Detection and tracking only: uncalibrated, so no ground positions, zones, or rules. Known limitation on display: the COCO-trained detector has no excavator class, so the machine itself is rarely boxed and only the operator in the cab is detected reliably.

up:        ## docker compose up --build (full stack, simulated feeds)
	$(COMPOSE) up --build

down:      ## stop the local stack
	$(COMPOSE) down

replay-up:   ## $0 public demo stack: postgres + api + ui + fixture replay, no GPU/LLM (docs/12 M6)
	$(REPLAY_COMPOSE) up --build

replay-down: ## stop the replay demo stack
	$(REPLAY_COMPOSE) down

showcase:  ## record the 3 demo clips for the dashboard's camera player (GPU; docs/12 M7)
	rm -rf build/showcase-evidence
	uv run python -m pipelines.vision.record --camera-id dock_north_01 --clip assets/clips/forklift_workers_interaction_1080p.mp4 --evidence-dir build/showcase-evidence --note "$(DOCK_NOTE)"
	uv run python -m pipelines.vision.record --camera-id warehouse_aisle_01 --clip assets/clips/worker_walking_aisle_1080p.mp4 --evidence-dir build/showcase-evidence --note "$(AISLE_NOTE)"
	uv run python -m pipelines.vision.record --camera-id yard_excavator_01 --clip assets/clips/excavator_site_01_1080p.mp4 --evidence-dir build/showcase-evidence --note "$(YARD_NOTE)"

showcase-agent: ## run the real prime-agent + Band-3 gate on the recorded incidents (LLM cost ~$0.002 each)
	uv run python -m scripts.showcase_agent --evidence-dir build/showcase-evidence --out ui/public/showcase --rerun

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
