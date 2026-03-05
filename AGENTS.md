# Agentic PR Workflow — Stacked PRs with git-town

## Rules

1. Never write code before the chunk plan is proposed, reviewed, and approved by the human and persisted to FEATURE_PLAN.md.
2. One branch = one concern. No exceptions.
3. Branches must be stacked on each other — not all branching off main.
4. If a chunk feels too big, split it further.
5. Verify git-town is installed before starting: `git town version`
6. FEATURE_PLAN.md is your source of truth. Re-read it at the start of every chunk.

---

## Step 1 — Understand the Full Scope

- Read the full feature requirement before doing anything.
- Identify every change needed end-to-end.
- Do not write a single line of code until the full scope is clear.

---

## Step 2 — Propose the Chunk Plan

Break the feature into small, logical, ordered layers and **present them to the human for review.**

Each chunk must:
- Represent exactly one concern
- Be independently readable and reviewable
- Build on top of the previous chunk

**Example for a new REST API endpoint:**

| Order | Branch | Contains |
|-------|--------|----------|
| 1 | `feat/db-schema` | Schema + migrations only |
| 2 | `feat/validators` | Request/response validators only |
| 3 | `feat/service-layer` | Business logic only |
| 4 | `feat/controller` | Route handlers only |

Adapt to the nature of the work. This is an example, not a rigid template. Present your proposed chunks and **wait for the human to confirm, adjust, or reject the plan before proceeding.**

---

## Step 3 — Write the Finalised Plan

Once the human approves the chunk plan, immediately write it to `FEATURE_PLAN.md` in the repo root:

```markdown
# Feature Plan: <feature-name>

## Chunks
- [ ] feat/db-schema — Schema + migrations
- [ ] feat/validators — Request/response validators
- [ ] feat/service-layer — Business logic
- [ ] feat/controller — Route handlers
- [ ] feat/tests — Tests

## Stack Hierarchy
feat/db-schema → main
feat/validators → feat/db-schema
feat/service-layer → feat/validators
feat/controller → feat/service-layer
feat/tests → feat/controller
```

Commit this file before writing any code:
```bash
git add FEATURE_PLAN.md
git commit -m "plan: add feature plan for <feature-name>"
```
---

## Step 4 — Work Through Each Chunk (repeat per chunk)

**At the start of every chunk, re-read FEATURE_PLAN.md before doing anything else.**
This is mandatory — do not rely on memory.

**4a. Identify the next uncompleted chunk from FEATURE_PLAN.md.**

**4b. Propose what will go into this chunk to the human and wait for confirmation before coding.**

**4c. Create the chunk branch:**

For the first chunk, branch off `main`:
```bash
git town hack feat/<first-chunk-name>
```

For all subsequent chunks, stack on top of the current branch:
```bash
git town append feat/<chunk-name>
```

**4d. Implement only this chunk's concern. Do not bleed work from other chunks.**

**4e. Commit:**
```bash
git add .
git commit -m "<what this chunk does>"
```

**4f. Raise a PR targeting the immediate parent:**
```bash
git town propose
```
First chunk targets `main`. Every subsequent chunk targets the chunk above it.

**4g. Mark the chunk as done in FEATURE_PLAN.md:**
```markdown
- [x] feat/db-schema — Schema + migrations
```

Commit the update:
```bash
git add FEATURE_PLAN.md
git commit -m "plan: mark feat/db-schema as done"
```

**4h. Confirm with the human before moving to the next chunk.**

---

## Step 5 — Mid-Stack Changes

If a review requires changes to a branch in the middle of the stack:

1. Re-read FEATURE_PLAN.md to reorient on the full stack hierarchy.

2. Navigate to the branch using the visual switcher:
```bash
git town switch
```
Or step through the stack with `git town up` / `git town down`.

3. Make and commit the fix.

4. Propagate the fix down to all child branches:
```bash
git town sync --stack
```

> `git town sync` (no flag) only pulls from parents into the current branch.
> `git town sync --stack` propagates changes downward through all children.

---

## Step 6 — Cleanup

Once all chunks are done and all PRs are raised, delete `FEATURE_PLAN.md`:
```bash
git rm FEATURE_PLAN.md
git commit -m "plan: remove feature plan for <feature-name>"
```

---

## Quick Reference

| Action | Command |
|--------|---------|
| First chunk branch (off main) | `git town hack feat/<n>` |
| Stack next chunk on top | `git town append feat/<n>` |
| Raise PR to immediate parent | `git town propose` |
| Sync current branch from parents | `git town sync` |
| Propagate changes down the stack | `git town sync --stack` |
| Visual stack navigator | `git town switch` |
| Move one level up/down | `git town up` / `git town down` |
| View full stack | `git town status` |

---

## Never Do This

- ❌ Start coding before the human approves the chunk plan
- ❌ Start a chunk without re-reading FEATURE_PLAN.md first
- ❌ Put more than one concern in a branch
- ❌ Branch all chunks off `main` directly — stack them on each other
- ❌ Create an empty root feature branch — start with real code
- ❌ Skip `git town sync --stack` after a mid-stack fix
- ❌ Move to the next chunk without human confirmation


# Repository Guidelines

## Project Structure & Module Organization
- `main.py` defines the FastAPI app entrypoint.
- `api/routes/` contains HTTP route handlers; versioned routes live under `api/routes/v1/`.
- `api/deps/` holds dependency wiring (tenancy, DB session, user data).
- `services/` contains business logic; keep HTTP concerns out of services.
- `models/` holds SQLAlchemy models; `schemas/` contains Pydantic request/response models.
- `config/` contains settings and tenancy provider wiring; `db/` contains session/engine setup.
- `tenants_config.json` and `tenants_secrets.json` are local tenancy config inputs.

## Build, Test, and Development Commands
- `uv sync` installs dependencies into the local environment.
- `uv run uvicorn main:app --reload` runs the API locally with auto-reload.
- OpenAPI docs are available at `http://localhost:8000/docs` in dev mode.

## Coding Style & Naming Conventions
- Python 3.12 is required (see `pyproject.toml`).
- Use clear, explicit naming: `snake_case` for functions/vars, `PascalCase` for classes.
- Route handlers should be thin; put logic in `services/` and keep data shapes in `schemas/`.
- `ruff` is listed as a dependency; if adding linting/formatting, prefer Ruff conventions.
- Follow SOLID and the Zen of Python. Keep changes DRY and avoid redundant code or logic.
- If DRY conflicts with separation of concerns, choose separation of concerns to preserve clear, business-aligned module boundaries.

## Security & Configuration Notes
- Tenancy is resolved from `X-Tenant-ID` headers; user identity can come from headers or JWT.
- Keep secrets out of source control; use `.env` for local settings and update `.env.example` if added.
