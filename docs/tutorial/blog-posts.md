# 1. The Multi-Tenant Blog App (CRUD & Rate Limiting)

In the Quickstart, we explored `/v1/hello` to see how tenant configuration can customize a greeting message.

Now, let's build a real-world multi-tenant feature: a **Multi-Tenant Blog Platform** with **per-tenant posting quotas and rate limiting**.

---

## 🏢 Setting the Scene: What is the App and Who are the Tenants?

Imagine you run a **Blogging Platform** where tech companies purchase subscriptions allowing their employees to write and publish articles:

| Tenant (Company) | Header (`X-Tenant-ID`) | Users (Employees) | Subscription Plan | Daily Posting Limit |
|---|---|---|---|---|
| **Spotify** | `spotify` | Alice (`alice@spotify.com`) | Starter Plan | **1 post / day** |
| **Airbnb** | `airbnb` | Bob (`bob@airbnb.com`) | Pro Plan | **5 posts / day** |
| **Netflix** | `netflix` | Carol (`carol@netflix.com`) | Enterprise Plan | **Unlimited** (`null`) |

```text
Our Multi-Tenant Blog App
 ├── Tenant: Spotify (X-Tenant-ID: spotify)
 │    └── User: Alice (X-User-ID: alice)   --> Publishes article (Spotify limit: 1/day)
 │
 ├── Tenant: Airbnb (X-Tenant-ID: airbnb)
 │    └── User: Bob (X-User-ID: bob)       --> Publishes article (Airbnb limit: 5/day)
 │
 └── Tenant: Netflix (X-Tenant-ID: netflix)
      └── User: Carol (X-User-ID: carol)   --> Publishes article (Netflix limit: Unlimited)
```

---

## Step 1: Define Feature Configuration in `tenants_config.json`

Instead of hardcoding company checks in code, each tenant defines its rate limit in `tenants_config.json` under `"features"."blog_posts"`:

```json
{
  "spotify": {
    "tenant_id": "spotify",
    "display_name": "Spotify",
    "is_active": true,
    "features": {
      "blog_posts": {
        "max_daily_posts": 1
      }
    }
  },
  "airbnb": {
    "tenant_id": "airbnb",
    "display_name": "Airbnb",
    "is_active": true,
    "features": {
      "blog_posts": {
        "max_daily_posts": 5
      }
    }
  },
  "netflix": {
    "tenant_id": "netflix",
    "display_name": "Netflix",
    "is_active": true,
    "features": {
      "blog_posts": {
        "max_daily_posts": null
      }
    }
  }
}
```

---

## Step 2: The Route Handler (Thin & Explicit)

In FastKitty, route handlers are deliberately **thin controllers**. They do not perform business logic, database queries, or rate-limit counting.

Notice how the router is protected with `require_active_tenant`, and the route handler injects `get_feature_config`:

```python
# api/routes/v1/blog_posts.py
from typing import Annotated
from fastapi import APIRouter, Body, Depends, status

from api.deps.db import get_blog_posts_service
from api.deps.tenancy import get_feature_config, require_active_tenant
from api.deps.user_data import get_user_data
from schemas.posts import BlogPostCreate, BlogPostResponse
from schemas.tenancy import FeatureConfig
from schemas.user_data import UserData
from services.blog_posts_service import BlogPostsService

router = APIRouter(
    tags=["Blog-Posts"],
    dependencies=[Depends(require_active_tenant)],  # Enforce active tenant router-wide
)


@router.post(
    "/blog-posts",
    name="blog_posts",  # Endpoint name matches the feature key in tenants_config.json
    status_code=status.HTTP_201_CREATED,
    response_model=BlogPostResponse,
)
async def create_blog_post(
    payload: Annotated[BlogPostCreate, Body()],
    feature_config: FeatureConfig | None = Depends(
        get_feature_config("blog_posts")
    ),  # Scoped to route name
    service: BlogPostsService = Depends(get_blog_posts_service),
    user_data: UserData = Depends(get_user_data),
) -> BlogPostResponse:
    # Pass feature config directly to the service layer (route remains ultra-thin)
    blog_post = await service.create_post(
        payload,
        user_id=user_data.user_id,
        feature_config=feature_config,
    )
    return BlogPostResponse.model_validate(blog_post)
```

---

### 💡 Why this design pattern is the standard:

1. **Router-Level Security (`dependencies=[Depends(require_active_tenant)]`)**:
   - By declaring `require_active_tenant` once on the `APIRouter`, every HTTP method (`GET`, `POST`, `PUT`, `DELETE`) associated with this router mandatorily requires a valid, active tenant.
   - Developers **never have to remember** to decorate or add parameters to each individual function — it is impossible to accidentally expose an un-tenanted endpoint.
   - Any missing header (`400`), unknown tenant (`404`), or deactivated tenant (`403`) is rejected at the front door before query execution or payload processing.

2. **Route Naming Contract (`name="blog_posts"`)**:
   - Just like `@router.get("/hello", name="greet")` in the quickstart, specifying `name="blog_posts"` on the decorator establishes a clear contract linking this endpoint directly to `"features": {"blog_posts": ...}` in `tenants_config.json`.
   - In FastKitty, `get_feature_config` inspects `request.scope["route"].name` by default. You can pass `Depends(get_feature_config("blog_posts"))` explicitly or even `Depends(get_feature_config())` to auto-resolve using the route's name!

3. **Function-Level Feature Scoping (`Depends(get_feature_config("blog_posts"))`)**:
   - Rather than dumping the entire tenant configuration into the route, injecting `get_feature_config("blog_posts")` in the function signature ensures the endpoint receives **only the configuration relevant to this specific API**.
   - Other feature flags, internal settings, or unrelated tenant data **do not get leaked** into this route or its service call.
   - The route remains thin and explicit, handing just the relevant config slice to `BlogPostsService`.

4. **When to inject `TenantConfig` directly**:
   - If an endpoint specifically needs broader tenant metadata — such as `tenant_config.display_name` to render a greeting — developers can still inject `tenant_config: TenantConfig = Depends(require_active_tenant)` directly in the function signature.
   - FastAPI's request-scoped memoization ensures that doing so incurs **zero duplicate lookups**.

---

## Step 3: The Service Layer (Business Logic & Quota Enforcement)

The service layer receives `feature_config`, inspects the tenant's daily quota, and enforces the rule before creating the record:

```python
# services/blog_posts_service.py
from datetime import datetime, timezone
from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.posts import BlogPost
from schemas.posts import BlogPostCreate
from schemas.tenancy import FeatureConfig


class BlogPostsService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_post(
        self,
        payload: BlogPostCreate,
        user_id: str,
        feature_config: FeatureConfig | None = None,
    ) -> BlogPost:
        # 1. Read quota from feature config (defaulting to 1 if not configured)
        max_daily_posts = (
            feature_config.get("max_daily_posts", 1) if feature_config else 1
        )

        # 2. If max_daily_posts is not None, enforce the limit
        if max_daily_posts is not None:
            today_start = datetime.now(timezone.utc).replace(
                hour=0, minute=0, second=0, microsecond=0
            )
            count_query = (
                select(func.count())
                .select_from(BlogPost)
                .where(BlogPost.created_at >= today_start)
            )
            posts_today = await self.session.scalar(count_query) or 0

            if posts_today >= max_daily_posts:
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail=f"Daily posting limit of {max_daily_posts} reached for this tenant.",
                )

        # 3. Create and persist post
        post = BlogPost(
            title=payload.title,
            content=payload.content,
            author=user_id,
        )
        self.session.add(post)
        await self.session.commit()
        await self.session.refresh(post)
        return post
```

---

## Step 4: Testing the Rate Limits

### 1. Alice at Spotify publishes their 1st post (Allowed)

```bash
curl -X POST http://127.0.0.1:8000/v1/blog-posts \
  -H "X-Tenant-ID: spotify" \
  -H "X-User-ID: alice" \
  -H "Content-Type: application/json" \
  -d '{"title": "Scaling Music Streaming", "content": "How we manage cache..."}'
```

**Response**: `201 Created`

---

### 2. Alice at Spotify tries to publish a 2nd post today (Blocked)

```bash
curl -X POST http://127.0.0.1:8000/v1/blog-posts \
  -H "X-Tenant-ID: spotify" \
  -H "X-User-ID: alice" \
  -H "Content-Type: application/json" \
  -d '{"title": "Second Article", "content": "More scaling notes..."}'
```

**Response**: `429 Too Many Requests`
```json
{
  "detail": "Daily posting limit of 1 reached for this tenant."
}
```

---

### 3. Bob at Airbnb publishes 3 posts on the same day (Allowed)

```bash
curl -X POST http://127.0.0.1:8000/v1/blog-posts \
  -H "X-Tenant-ID: airbnb" \
  -H "X-User-ID: bob" \
  -H "Content-Type: application/json" \
  -d '{"title": "Design Systems at Airbnb", "content": "Building UI at scale..."}'
```

**Response**: `201 Created`  
Airbnb's limit is 5, so their employees publish smoothly without being affected by Spotify's limit!

---

## Next Step

Now that we have business logic and rate limiting working, where does this data actually live on disk?

Let's look at how **all tenants must have database connection credentials in secrets**, which strategy FastKitty is running, and how storage isolation works:

👉 **[2. Tenant Secrets & Database Strategies](storage-and-secrets.md)**
