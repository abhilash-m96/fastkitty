# Setup & Run (Local / Docker)

FastKitty is designed to be spun up in less than 60 seconds. Choose between running the database in Docker while keeping the API local (recommended for fast iteration), or running the entire containerized stack.

---

## Option A: Local Development with Docker PostgreSQL (Recommended)

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
