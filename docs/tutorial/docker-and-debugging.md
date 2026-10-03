# Docker & Interactive Debugging (`pdb`)

FastKitty's Docker configuration includes full support for interactive step-through debugging using Python's standard `breakpoint()` and `pdb`.

The `api` container in `docker-compose.yml` runs with `stdin_open: true` and `tty: true`, enabling you to attach your terminal directly to a paused execution thread.

---

## 1. Add a Breakpoint

Drop `breakpoint()` (or `import pdb; pdb.set_trace()`) anywhere in your route, dependency, or service code:

```python
# services/blog_posts_service.py
async def create_post(
    self,
    payload: BlogPostCreate,
    user_id: str,
    feature_config: FeatureConfig | None = None,
) -> BlogPost:
    breakpoint()  # <--- Execution pauses here inside the service layer
    max_daily_posts = feature_config.get("max_daily_posts", 1) if feature_config else 1
    ...
```

---

## 2. Trigger the Code

Send an HTTP request that hits the breakpoint:

```bash
curl -X POST http://127.0.0.1:8000/v1/blog-posts \
  -H "X-Tenant-ID: spotify" \
  -H "X-User-ID: alice" \
  -H "Content-Type: application/json" \
  -d '{"title": "Debugging in Docker", "content": "Testing pdb..."}'
```

The request will pause awaiting debugger input.

---

## 3. Attach to the Container

In another terminal, attach directly to the running container:

```bash
docker attach fastkitty-api
```

You are now in the live `(Pdb)` prompt:
- `n` — step to next line
- `s` — step into function
- `c` — continue execution
- `p feature_config` — evaluate and print expression
- `l` — list surrounding code

> [!TIP]
> **Detaching without stopping the container**:  
> Press **`Ctrl+P`** followed by **`Ctrl+Q`** to detach your terminal while leaving the container running.

---

## 4. Interactive Container Shell

To inspect files or test Python code inside the container environment:

```bash
# Open interactive bash shell
docker compose exec -it api bash

# Open Python REPL inside container environment
docker compose exec -it api python
```

---

## Next Step

Ready to understand how FastKitty organizes its codebase and keeps components lean and testable?  
👉 **[Architecture: Project Structure & Component Cleanliness](../architecture/project-structure.md)**
