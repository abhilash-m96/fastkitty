# Contributing to FastKitty 😼

First off, thank you for considering contributing to FastKitty! It's people like you that make FastKitty an awesome foundation for the FastAPI community.

---

## 🛠️ Development Setup

FastKitty uses [`uv`](https://docs.astral.sh/uv/) as its fast Python package manager and project tool.

### 1. Clone the repository
```bash
git clone https://github.com/abhilash-m96/fastkitty.git
cd fastkitty
```

### 2. Install dependencies & virtual environment
```bash
uv sync
```

### 3. Setup local environment
```bash
cp .env.example .env
```

### 4. Start local multi-tenant PostgreSQL (Docker)
```bash
docker compose up -d postgres
```

### 5. Run database migrations
```bash
uv run alembic upgrade head
```

---

## 🧪 Running Tests & Checks

Before submitting a pull request, ensure all checks pass:

```bash
# Run pytest test suite
uv run pytest

# Check code formatting & linting with Ruff
uv run ruff check .

# Verify documentation builds without broken links
uv run mkdocs build --strict
```

---

## 🚀 Pull Request Guidelines

1. **Create a branch**: Use descriptive branch names:
   - `feat/feature-name`
   - `fix/bug-fix`
   - `docs/documentation-update`
   - `chore/maintenance`
2. **Follow Architectural Principles**: FastKitty enforces clean architectural boundaries:
   - Route handlers must remain thin.
   - Tenancy is explicit via dependency injection.
   - Behavioral divergence must be driven by `tenants_config.json` rather than hardcoded `tenant_id` checks.
3. **Write Tests**: Every new route, model, or service method must include automated tests in `tests/`.
4. **Open a PR**: Open a pull request against `main`. Fill in the PR template with context and verification details.

---

## 💬 Community & Discussions

Feel free to open an issue for bugs or start a thread in GitHub Discussions for feature requests and architectural debates.
