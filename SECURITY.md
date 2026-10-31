# Security & data policy

- **Secrets** live in `.env` (local) and AWS Secrets Manager / GitHub OIDC (cloud). Never in git.
  pre-commit and CI run gitleaks.
- **Patient data:** this project stores synthetic data only. Logs and traces must not contain names,
  emails, phone numbers or free-text symptoms linked to a person (PII masking in `guardrails/`).
- **Medical safety:** responses carry a disclaimer; red-flag symptoms trigger an emergency
  response instead of advice.
- **Reporting:** open a private security advisory on GitHub instead of a public issue.
