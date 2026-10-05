# Auth as a Peer Concern: Upstream Gateways

FastKitty is intentionally **auth-agnostic**.

In modern cloud architecture, authentication is a peer concern — it belongs upstream at the API Gateway or Backend-for-Frontend (BFF), not scattered across individual microservice routes.

---

## The Recommended Architecture

```
Client → API Gateway / BFF → Auth Provider (Keycloak, Auth0, Okta, etc.)
                ↓ validated request with identity
         FastKitty service
```

A gateway validates credentials or tokens before requests reach your FastAPI service:
1. **Offline JWT validation** handles the common fast path.
2. **Server-side blocking checks** occur only when strictly necessary (e.g. forced revocation or high-stakes administrative operations).
3. By the time a request hits FastKitty, authentication is already complete.

---

## Why Keep Auth Upstream?

* **Multi-tenant auth is its own problem**: Tenant resolution, per-tenant token claims, and permission scoping belong in the auth layer, not scattered across service dependencies.
* **Vendor abstraction**: Your service never imports an Auth0 SDK or Keycloak client; it simply reads claims from a validated token or headers.
* **Independent evolution**: Add MFA, rotate signing keys, or swap identity providers without touching business logic.
* **No distributed bottleneck**: Auth happens on issuance; your FastKitty service stays stateless, lean, and fast.

---

## Identity & User Data Resolution in FastKitty

FastKitty resolves the authenticated actor via the `USER_DATA_SOURCE` environment variable in `.env`.

The value is a **JSON string** discriminated by the `"type"` field:

```bash
USER_DATA_SOURCE='{"type": "<header|jwt|claims>", ...}'
```

Regardless of the ingestion mode you choose, FastKitty maps the attributes into a uniform `UserData` model:

```python
class UserData(BaseModel):
    user_id: str
    email: str | None = None
    roles: list[str] | None = None
```

> [!IMPORTANT]
> **Understanding the JSON Configuration Values**:  
> In all configuration modes below, **the values you provide in the JSON string are the exact key names in your token or gateway headers** where FastKitty should extract the actual data.
> For instance, setting `"user_id_claim": "sub"` tells FastKitty: *"look for the `sub` key inside the JWT payload and use its value as `user_data.user_id`."* If your token stores the user ID in `"uid"`, simply set `"user_id_claim": "uid"`.

---

### Mode 1: Individual Gateway Headers (`type: "header"`)

The standard reverse proxy / API gateway pattern (Kong, Envoy, AWS API Gateway, Traefik). The gateway validates the client's token and injects verified identity into discrete HTTP headers before forwarding the request downstream.

#### Configuration Parameters

| Parameter | Type | Default | What It Configures |
|---|---|---|---|
| `type` | `str` | `"header"` | Discriminator specifying header ingestion mode. |
| `user_id_header` | `str` | `"X-User-ID"` | The **HTTP header name** containing the user ID (*required*). |
| `user_email_header` | `str \| null` | `"X-User-Email"` | The **HTTP header name** containing the user's email (*optional*). |
| `user_roles_header` | `str \| null` | `"X-User-Roles"` | The **HTTP header name** containing user roles (*optional*). |
| `roles_delimiter` | `str` | `","` | Delimiter string used to parse delimited roles (e.g., `"admin,editor"` → `["admin", "editor"]`). |

#### `.env` Example

```bash
USER_DATA_SOURCE='{"type": "header", "user_id_header": "X-User-ID", "user_email_header": "X-User-Email", "user_roles_header": "X-User-Roles", "roles_delimiter": ","}'
```

---

### Mode 2: Unverified JWT Claims (`type: "jwt"`)

Used when your gateway forwards the client's `Authorization: Bearer <token>` directly into a trusted private VPC. Because cryptographic signature verification was already performed at the ingress edge, FastKitty decodes the unverified JWT payload without signature re-verification overhead.

#### Configuration Parameters

| Parameter | Type | Default | What It Configures |
|---|---|---|---|
| `type` | `str` | `"jwt"` | Discriminator specifying JWT claim extraction mode. |
| `header_name` | `str` | `"Authorization"` | The **HTTP header name** containing the token. |
| `prefix` | `str \| null` | `"Bearer"` | Token prefix stripped before decoding (e.g., `"Bearer <token>"`). Set to `null` if no prefix. |
| `user_id_claim` | `str` | `"sub"` | The **JWT claim key** inside the token payload for user ID (*required*). |
| `user_email_claim` | `str \| null` | `"email"` | The **JWT claim key** inside the token payload for user email (*optional*). |
| `user_roles_claim` | `str \| null` | `"roles"` | The **JWT claim key** inside the token payload for user roles (*optional*, accepts a JSON list or comma-separated string). |

#### `.env` Example

```bash
USER_DATA_SOURCE='{"type": "jwt", "header_name": "Authorization", "prefix": "Bearer", "user_id_claim": "sub", "user_email_claim": "email", "user_roles_claim": "roles"}'
```

---

### Mode 3: Serialized Claims Header (`type: "claims"`)

Used when the gateway unpacks user claims and forwards them as a serialized JSON string in a single custom header (e.g., `X-User-Claims: {"id": "usr_123", "email": "alice@example.com", "roles": ["admin"]}`).

#### Configuration Parameters

| Parameter | Type | Default | What It Configures |
|---|---|---|---|
| `type` | `str` | `"claims"` | Discriminator specifying JSON claims header mode. |
| `header_name` | `str` | `"X-User-Claims"` | The **HTTP header name** containing the serialized JSON claims object. |
| `user_id_field` | `str` | `"id"` | The **JSON key** inside the claims object for user ID (*required*). |
| `user_email_field` | `str \| null` | `"email"` | The **JSON key** inside the claims object for user email (*optional*). |
| `user_roles_field` | `str \| null` | `"roles"` | The **JSON key** inside the claims object for user email (*optional*). |

#### `.env` Example

```bash
USER_DATA_SOURCE='{"type": "claims", "header_name": "X-User-Claims", "user_id_field": "id", "user_email_field": "email", "user_roles_field": "roles"}'
```

---

## Zero-Effort Swagger / OpenAPI Documentation

You never have to worry about documenting these dynamic headers manually in FastAPI. 

FastKitty dynamically constructs the Python function signature (`__signature__`) of `get_user_data` at application startup to mirror your exact configured `USER_DATA_SOURCE`:
* In **Header mode**, FastAPI inspects the dynamic signature and automatically generates the exact header parameters in `/docs` (Swagger UI) and `/redoc` with their configured header aliases (e.g. `X-User-ID`, `X-User-Email`), correctly marking required vs optional fields.
* In **JWT mode**, it automatically exposes the configured `Authorization` header.
* In **Claims mode**, it exposes the configured `X-User-Claims` header.

Your interactive API documentation always stays 100% in sync with your runtime configuration.

---

## Consuming User Identity in Route Handlers

Inject user identity into any FastAPI endpoint using the `get_user_data` dependency:

```python
from fastapi import APIRouter, Depends
from api.deps.user_data import get_user_data
from schemas.user_data import UserData

router = APIRouter()

@router.get("/profile")
async def get_profile(user_data: UserData = Depends(get_user_data)):
    return {
        "user_id": user_data.user_id,
        "email": user_data.email,
        "roles": user_data.roles,
    }
```

### Telemetry Integration

When `get_user_data` resolves an active user identity, FastKitty automatically enriches the active OpenTelemetry / Logfire span with tracing attributes:
* `user.id = user_data.user_id`
* `user.roles = user_data.roles`

This enables instant filtering and tracing by user identity in your observability dashboards.

---

> [!TIP]
> **Keep Tokens Lean**: Fat tokens with hundreds of claims go stale quickly and force synchronous verification. Pass just enough identity attributes to scope requests, and allow services to hydrate domain data from their own database.
