# ADR-002: Message Broker — Redis Streams locally, cloud-native queues in reference architecture

**Status:** Accepted

## Context
Telemetry (high-rate) and triggers (rare) need a broker. Local dev must be $0; the cloud reference
architecture must map to managed primitives without schema changes.

## Decision
- Local: Redis Streams (XADD consumer groups, 5-min ring retention). Enough throughput, zero cost,
  trivial docker compose dependency.
- Cloud (documented only): AWS SQS (+DLQ) for triggers, MSK if telemetry scale demands; GCP Pub/Sub
  push; Azure Service Bus (+KEDA scaling). Same JSON payloads; the adapter layer abstracts transport.
- Kafka is the documented upgrade path if camera count makes Redis retention/persistence inadequate.

## Consequences
+ $0 local; clean per-cloud runbooks; schemas independent of transport.
- Two transport implementations to keep honest (thin, contract-tested).
