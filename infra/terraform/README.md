# Infrastructure (Phase 8)

Terraform for AWS. Planned modules:

| Module | Resources |
|---|---|
| `network` | VPC, public/private subnets, security groups |
| `registry` | ECR repository for `medagent-api` |
| `database` | RDS PostgreSQL 16 with pgvector |
| `service` | ECS Fargate cluster, service, ALB, autoscaling (or App Runner) |
| `secrets` | Secrets Manager entries for API keys |
| `ci_oidc` | IAM OIDC provider + deploy role for GitHub Actions |
| `budget` | AWS Budgets alert |

State: S3 backend + DynamoDB lock table (bootstrap once by hand).
Variables: copy `terraform.tfvars.example` to `terraform.tfvars` (git-ignored).
