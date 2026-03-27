# Feature Plan: Tenant Secrets Provider

## Chunks
- [ ] feat/secret-schema-settings — Tenant secrets schema + settings + docs/examples
- [ ] feat/secret-providers — Secrets providers (file + AWS Secrets Manager) + provider factory
- [ ] feat/secret-service-deps — Tenancy secret service + dependency wiring
- [ ] feat/secret-tests — Tests for providers and factory (AWS mocked)

## Stack Hierarchy
feat/secret-schema-settings → main
feat/secret-providers → feat/secret-schema-settings
feat/secret-service-deps → feat/secret-providers
feat/secret-tests → feat/secret-service-deps
