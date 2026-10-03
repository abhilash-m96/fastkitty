# Setup & Run (Local / Docker)

FastKitty is designed to be spun up in less than 60 seconds. Choose between letting your AI coding assistant scaffold your service automatically, or running the database and API manually.

---

## Fast Track: Build with Your AI Coding Assistant 🤖

FastKitty is **agent-native**. It ships with:
- **`AGENTS.md`**: An embedded Multi-Tenant Service Architect protocol that guides AI coding assistants.
- **`SERVICE_SPEC.md`**: A persistent living specification of your service domain, models, and endpoints.

### The Recommended Workflow:
1. Clone this repository and open the folder in **Cursor**, **Antigravity**, **Claude Code**, **GitHub Copilot**, or **Windsurf**.
2. In the AI chat, prompt:
   > *"I want to build a [service-name, e.g. billing-service]. Guide me through setup."*
3. The **FastKitty Service Architect** will greet you, walk you through key architectural choices (tenancy strategy, config/secrets, models, and endpoints) one question at a time, recommend best practices from our knowledge base, and scaffold models, services, thin routes, and 100% passing tests for you.

---

## Manual Setup: Local Development with Docker PostgreSQL (Recommended)

This option runs a local multi-tenant PostgreSQL 16 container while running the FastAPI application natively with `uv` on your host machine for instantaneous code reloading.

### 1. Start the PostgreSQL service
Start PostgreSQL with the multi-tenant databases pre-configured:

```bash
docker compose up -d postgres
```

This starts PostgreSQL 16 on `localhost:5432` and automatically runs [`docker/init-db.sh`](https://github.com/abhilash-m96/fastkitty/blob/main/docker/init-db.sh) to initialize `tenant_1`, `tenant_2`, and `fastkitty_shared` databases.

### 2. Install dependencies & configure environment
Install dependencies using `uv` and create your local environment file:

```bash
uv sync
cp .env.example .env
```

### 3. Run database migrations
Apply multi-tenant Alembic migrations across your databases:

```bash
uv run alembic upgrade head
```

### 4. Run the API with auto-reload
Launch the FastAPI server:

```bash
uv run uvicorn main:app --reload
```

The API is now live at `http://localhost:8000`.  
Open the interactive Swagger UI at `http://localhost:8000/docs`.

---

## Option B: Full Containerized Stack

To run both PostgreSQL and the FastKitty API completely inside Docker:

```bash
docker compose up --build -d
```

PostgreSQL boots, tenant databases are created, migrations run automatically on startup, and the API is live at `http://localhost:8000` with live code volume mounts.

---

## Next Step

Now that FastKitty is running, let's see multi-tenancy in action with the dynamic Greet endpoint:  
👉 **[2. The Greet Endpoint (Dynamic Hello)](dynamic-hello.md)**
