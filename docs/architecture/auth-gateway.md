# Auth as a Peer Concern: Upstream Gateways

FastKitty is intentionally **auth-agnostic**.

In modern cloud architecture, authentication is a peer concern — it belongs upstream at the API Gateway, not scattered across individual microservice routes.

---

## The Recommended Architecture

```
Client → API Gateway / BFF → Auth Service (Keycloak, Auth0, Okta, etc.)
                ↓ validated token
         fastkit(ty) service
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

FastKitty resolves the authenticated actor via `USER_DATA_SOURCE` in `.env`:

| Mode | Value in `.env` | How Identity is Resolved |
|---|---|---|
| **Header** | `USER_DATA_SOURCE=header` | Reads `X-User-ID`, `X-User-Email`, and `X-User-Roles` headers directly from the gateway. |
| **JWT** | `USER_DATA_SOURCE=jwt` | Decodes `Authorization: Bearer <token>` payload without signature re-validation (trusted internal network). |
| **Claims** | `USER_DATA_SOURCE=claims` | Reads `X-User-Claims` as a serialized JSON header. |

In route handlers, inject user identity simply with:

```python
from api.deps.user_data import get_user_data
from schemas.user_data import UserData

@router.get("/profile")
async def get_profile(user_data: UserData = Depends(get_user_data)):
    return {"user_id": user_data.user_id, "roles": user_data.roles}
```

> [!TIP]
> **Keep Tokens Lean**: Fat tokens with hundreds of claims go stale quickly and force synchronous verification. Pass just enough identity attributes to scope requests, and allow services to hydrate domain data from their own database.
