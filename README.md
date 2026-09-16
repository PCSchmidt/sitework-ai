# SiteWatch AI (`sitework-ai`)

Autonomous industrial safety & fleet telemetry: a hybrid deterministic/probabilistic
computer-vision system for warehouses and construction sites.

- **Fast path (deterministic):** detection → tracking → homography → geometric rules, ≤500 ms alerts, zero LLM cost.
- **Slow path (event-driven):** containerized Prime Agent worker that verifies kinematics and writes audit-grade incident records.

## Quickstart

```bash
make up     # docker compose up --build (full local stack, simulated feeds)
make test   # unit + integration + contract tests
```

## Documentation

The design suite lives in [docs/](docs/) — start with [PLAN.md](PLAN.md), then
[docs/01-vision-and-scope.md](docs/01-vision-and-scope.md) and the ADRs in [docs/adr/](docs/adr/).
Roadmap and current status: [docs/12-roadmap.md](docs/12-roadmap.md).

License: [MIT](LICENSE).
