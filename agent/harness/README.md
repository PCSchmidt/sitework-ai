# Harness state (placeholder)

Prime Agent's **Continual Harness** can persist sub-agent specifications, memories, and refined
policies as durable state, so a specialist role is defined once and reused across sessions.
The original design (docs/05 §2) planned to register the trajectory-inspector,
compliance-auditor, and shift-synthesizer roles here.

**That never happened, and this folder is intentionally empty.** As built, `agent/worker.py`
starts one `prime-agent` RPC process per incident and sends it a self-contained prompt from
`agent/prompts/`. No harness specs are registered, and nothing from this folder is mounted.

The harness state the agent container does use is the host's own `~/.prime` directory (for
prime-agent's model/provider authentication), mounted at `/home/node/.prime` via
`docker-compose.yml` (override with `PRIME_HARNESS_DIR`).

If harness sub-agent specs are ever added, they belong here, and docs/05 §2 describes what
each would contain.
