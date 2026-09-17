# AWS Deployment Guide — SiteWatch AI Cognitive Worker

**Deployable reference architecture.** This runbook documents a complete, syntactically valid
deployment. Per ADR-004, `terraform apply` is never executed in CI; every provisioning step ends
with `plan` only. The canonical Terraform for this guide exists as a reviewed specification:
*SiteWatch AI — AWS ECS Fargate & EFS Terraform Configuration* (repo root PDF), covering
`variables.tf`, `sqs.tf`, `efs.tf`, `security_iam.tf`, `main.tf`, `outputs.tf`.

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
  on the incident queue (least privilege).
- Egress restricted to HTTPS 443 (LLM APIs, AWS services) and NFS 2049 (EFS). Private subnets,
  no public IP.
- EFS Access Point enforces POSIX `uid/gid 1000`; transit encryption enabled; IA lifecycle at 30 days.
- Queue `visibility_timeout_seconds=300` > max agent turn timeout; redrive `maxReceiveCount=3`.

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
terraform init
terraform plan -out=tfplan                      # review: queue, DLQ, EFS, roles, Fargate service
# COST WARNING: applying provisions an always-on Fargate task + EFS (~$10-15/mo idle floor).
# terraform apply tfplan                        # commented per ADR-004 — deliberate manual action only
```

## 4. Container Image Publication

```bash
aws ecr create-repository --repository-name sitewatch-ai/prime-agent-worker
aws ecr get-login-password | docker login --username AWS --password-stdin <acct>.dkr.ecr.<region>.amazonaws.com
docker build -f docker/Dockerfile.agent -t sitewatch-ai/prime-agent-worker:1.0.0 .   # pinned prime-agent version
docker tag sitewatch-ai/prime-agent-worker:1.0.0 <acct>.dkr.ecr.<region>.amazonaws.com/sitewatch-ai/prime-agent-worker:1.0.0
docker push <acct>.dkr.ecr.<region>.amazonaws.com/sitewatch-ai/prime-agent-worker:1.0.0
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

```bash
QUEUE_URL=$(aws sqs get-queue-url --queue-name sitewatch-ai-incident-queue-production --query QueueUrl --output text)
python scripts/smoke_test_telemetry.py --queue "$QUEUE_URL"   # injects one synthetic TriggerEvent
# EXPECT: worker logs show RPC session; result.json validated; incident row in Aurora;
#         DLQ depth remains 0; agent_runs row created with token accounting.
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
