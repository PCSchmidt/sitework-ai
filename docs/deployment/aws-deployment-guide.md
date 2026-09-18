# AWS Deployment Guide — SiteWatch AI Cognitive Worker

**Deployable reference architecture.** This runbook documents a complete, syntactically valid
deployment. Per ADR-004, `terraform apply` is never executed in CI; every provisioning step ends
with `plan` only. The Terraform lives at `deploy/terraform/environments/aws/`, realized from
*SiteWatch AI — AWS ECS Fargate & EFS Terraform Configuration* (repo root PDF) as
`variables.tf`, `sqs.tf`, `efs.tf`, `security_iam.tf`, `main.tf`, `outputs.tf`, plus `db.tf` (M6
addition -- the PDF spec covered only the agent worker's own ECS/SQS/EFS topology, not the
delivery-plane database the architecture table below already promised; `db.tf` closes that gap
with a real Aurora Serverless v2 cluster). `terraform fmt -check` + `terraform validate` pass for
real (verified against a locally-installed terraform, matching `iac-check.yaml`'s CI steps).

## 1. Architecture Mapping

| Component | AWS Primitive | Operational Role |
| --- | --- | --- |
| Cognitive agent worker | **ECS on Fargate** | Containerized Prime Agent (Node supervisor + headless IPython REPL + sub-agent pool), event-driven |
| Incident ingestion | **Amazon SQS + DLQ** | Buffers TriggerEvents from the edge vision filter; 300 s visibility timeout sized to max agent turn time; DLQ retains malformed payloads 14 days |
| Persistent agent state | **Amazon EFS + Access Point** | Mounts at `/home/node/.prime` — harness memory, refined sub-agent specs, session trees survive restarts |
| Evidence clips | **Amazon S3** | Trigger-time clip segments referenced by incidents |
| Telemetry/relational DB | **Aurora Serverless (PostgreSQL)** | Incidents, KPIs, `agent_runs` audit |
| Secrets & identity | **Secrets Manager + IAM** | LLM provider keys injected at runtime; separate execution vs task roles |
| Edge vision (future) | IoT Greengrass / on-prem GPU | Fast path stays local to the site; only JSON telemetry crosses the WAN |

Key spec invariants (from the PDF, mirrored in `deploy/terraform/environments/aws/`):
- Task role grants only `sqs:ReceiveMessage/DeleteMessage/GetQueueAttributes/ChangeMessageVisibility`
  on the incident queue, and `s3:GetObject/PutObject` scoped to the clips bucket (least privilege).
- Egress restricted to HTTPS 443 (LLM APIs, AWS services), NFS 2049 (EFS), and Postgres 5432
  (Aurora, `db.tf`). Private subnets, no public IP.
- EFS Access Point enforces POSIX `uid/gid 1000`; transit encryption enabled; IA lifecycle at 30 days.
- Queue `visibility_timeout_seconds=300` > max agent turn timeout; redrive `maxReceiveCount=3`.
- Aurora Serverless v2 scales 0.5-2.0 ACU (`db.tf`) -- toward-$0 idle floor, matching
  docs/10-cost-model.md's Scenario A row.

## 2. Prerequisites

```bash
aws-cli >= 2.15          # aws --version
terraform >= 1.5.0       # terraform -version
docker >= 24             # docker --version
aws configure            # admin-equivalent credentials for the deployment account
```

## 3. Infrastructure Provisioning

```bash
cd deploy/terraform/environments/aws
cp terraform.tfvars.example terraform.tfvars   # set vpc_id, private_subnet_ids, agent_image_uri
export TF_VAR_db_master_password="$(openssl rand -base64 24)"   # never in the tfvars file
terraform init
terraform plan -out=tfplan                      # review: queue, DLQ, EFS, S3, Aurora, roles, Fargate service
# COST WARNING: applying provisions an always-on Fargate task + EFS + Aurora Serverless v2
# (~$10-15/mo idle floor for compute/storage; Aurora's 0.5 ACU floor adds ~$45-50/mo more).
# terraform apply tfplan                        # commented per ADR-004 — deliberate manual action only
```

## 4. Container Image Publication

```bash
# "agent-worker", not "prime-agent-worker" -- prime-agent is the vendored CLI
# this container runs (docker/vendor/README.md), not this repo's own image name;
# matches the ECS container name in deploy/terraform/environments/aws/main.tf.
aws ecr create-repository --repository-name sitewatch-ai/agent-worker
aws ecr get-login-password | docker login --username AWS --password-stdin <acct>.dkr.ecr.<region>.amazonaws.com
docker build -f docker/Dockerfile.agent -t sitewatch-ai/agent-worker:1.0.0 .   # pinned prime-agent version inside
docker tag sitewatch-ai/agent-worker:1.0.0 <acct>.dkr.ecr.<region>.amazonaws.com/sitewatch-ai/agent-worker:1.0.0
docker push <acct>.dkr.ecr.<region>.amazonaws.com/sitewatch-ai/agent-worker:1.0.0
# Set agent_image_uri in terraform.tfvars to the pushed URI above.
```

## 5. Secrets & Identity

```bash
aws secretsmanager create-secret --name sitewatch-ai/llm/openrouter \
  --secret-string '{"OPENAI_BASE_URL":"https://openrouter.ai/api/v1","OPENAI_API_KEY":"<key>"}'
```
Grant the ECS **execution role** `secretsmanager:GetSecretValue` scoped to this ARN; keys land in
container env at task start. The **task role** carries only the SQS policy above. Budget guardrails:
AWS Budgets at $5/$15 with email+SMS; all resources tagged `project=sitewatch-ai`, `ttl=4h` for any
non-persistent experiment; no NAT gateway (use interface VPC endpoints for SQS/EFS/ECR).

## 6. Smoke Test

**Honest gap:** `scripts/smoke_test.py` (docs/09 §6, M4 exit criterion S1) is real, tested, and
green -- but it drives the local docker-compose stack (Redis Streams + Postgres), not SQS +
Aurora. No cloud-native equivalent exists yet; the steps below are the manual verification a real
AWS deployment would need, not an automated script this repo ships.

```bash
# Queue name follows ${project_name}-incident-queue-${environment} (main.tf/sqs.tf);
# "reference" is terraform.tfvars.example's default -- substitute your actual environment.
QUEUE_URL=$(aws sqs get-queue-url --queue-name sitewatch-ai-incident-queue-reference --query QueueUrl --output text)

# Inject one synthetic TriggerEvent (pipelines/schemas/models.py's shape) by hand:
aws sqs send-message --queue-url "$QUEUE_URL" --message-body "$(uv run python -c '
from pipelines.schemas import TriggerEvent, Severity, TriggerMetrics, CalibrationQuality
print(TriggerEvent(
    event_id="evt_aws_smoke", trigger_ts=1000.0, camera_id="dock_north_01",
    rule_id="proximity_forklift_pedestrian", severity_hint=Severity.HIGH,
    metrics=TriggerMetrics(min_distance_m=1.2, duration_s=2.0, closing_speed_mps=1.8),
    involved_track_ids=[42, 77], track_window_ref="incidents/evt_aws_smoke/tracks.jsonl",
    cooldown_key="dock_north_01:proximity:evt_aws_smoke",
    calibration_quality=CalibrationQuality(rms_px=1.0, valid=True),
).model_dump_json())')"

# EXPECT (CloudWatch Logs, /ecs/sitewatch-ai-worker-reference): RPC session starts, result.json
# validated, incident row appears in Aurora, DLQ depth stays 0, agent_runs row created with token
# accounting -- same pass criteria scripts/smoke_test.py checks locally, verified by hand here.
aws sqs get-queue-attributes --queue-url "$QUEUE_URL" --attribute-names ApproximateNumberOfMessages
```

## 7. Teardown & Cost Safety

```bash
# Full teardown (documented FIRST in this runbook by policy):
cd deploy/terraform/environments/aws
# terraform destroy -target=aws_ecs_service.agent_service   # stop compute first
# terraform destroy                                         # then storage/queues/network
aws budgets delete-budget --account-id <acct> --budget-name sitewatch-ai-5usd   # after confirming clean
```
Standing rules: scale `desired_count=0` when idle; CloudWatch log retention 30 days; EFS IA
lifecycle on; alert if `ApproximateAgeOfOldestMessage` exceeds 1 h (agent stuck).
