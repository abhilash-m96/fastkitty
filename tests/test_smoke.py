"""Basic smoke coverage for test bootstrap and client setup."""

from fastapi.testclient import TestClient


def test_test_client_fixture_bootstraps_app(client: TestClient) -> None:
    """Verify the shared client fixture can construct the FastAPI app."""
    assert client is not None
