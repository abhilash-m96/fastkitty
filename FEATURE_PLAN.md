# Feature Plan: Test Coverage Baseline

## Chunks
- [x] feat/test-foundation — Pytest dependencies, test config, shared fixtures, and app/client helpers
- [ ] feat/core-unit-tests — Unit tests for schemas, user-data parsing, DB URI/session wiring, services, and provider factories
- [ ] feat/provider-tests — Tests for file and external-provider adapters with mocked Consul and Vault clients
- [ ] feat/api-tests — Route-level tests for hello and blog-post endpoints, including tenant enforcement and user scoping

## Stack Hierarchy
feat/test-foundation → main
feat/core-unit-tests → feat/test-foundation
feat/provider-tests → feat/core-unit-tests
feat/api-tests → feat/provider-tests
