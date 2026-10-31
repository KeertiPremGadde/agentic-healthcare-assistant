# Changelog

Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), versions follow `v0.<phase>.<patch>`.

## [Unreleased]

### Added
- Phase 0 foundation: project layout, uv/ruff/mypy/pytest, FastAPI `/health`, docker-compose
  (Postgres + pgvector), Dockerfile, CI/CD workflows, docs (plan, architecture diagrams, ADRs).
- Phase 1 data layer: SQLAlchemy 2.0 models (Doctor, DoctorSchedule, Patient, Appointment),
  Alembic initial migration (enables `vector` extension), idempotent synthetic seed
  (`scripts/seed.py`), pure timezone-aware `availability`/`validation` services, thin repository,
  `CLINIC_TIMEZONE` / `SLOT_MINUTES` settings, unit + integration tests, `docs/learning/phase1.md`.
