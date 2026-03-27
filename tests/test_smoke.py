from fastapi.testclient import TestClient


def test_test_client_fixture_bootstraps_app(client: TestClient) -> None:
    assert client is not None
