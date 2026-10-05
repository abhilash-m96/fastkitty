## Description

<!-- Provide a brief summary of the changes introduced by this pull request -->

## Type of Change

- [ ] 🐛 Bug fix (non-breaking change which fixes an issue)
- [ ] ✨ New feature (non-breaking change which adds functionality)
- [ ] 💥 Breaking change (fix or feature that would cause existing functionality to not work as expected)
- [ ] 📝 Documentation update
- [ ] 🧹 Maintenance / Refactor / Chore

## Tenancy Architectural Checks

- [ ] Tenancy remains explicit and decoupled from business logic
- [ ] No hardcoded `tenant_id` string checks (`if tenant_id == ...`) in services or routes
- [ ] Route handlers remain thin and delegate to service classes
- [ ] Quotas and tier flags are declared in `tenants_config.json` and consumed via `feature_config`

## Verification

- [ ] `uv run pytest` passes (all unit and integration tests)
- [ ] `uv run ruff check .` passes without lint errors
- [ ] `uv run mkdocs build --strict` passes without broken links
