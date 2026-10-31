from fastapi.testclient import TestClient

from medagent.main import app


def test_health_returns_ok() -> None:
    response = TestClient(app).get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_root_redirects_to_the_docs() -> None:
    response = TestClient(app).get("/", follow_redirects=False)
    assert response.status_code == 307
    assert response.headers["location"] == "/docs"
    followed = TestClient(app).get("/")
    assert followed.status_code == 200
    assert "MedAgent API" in followed.text  # landed on the Swagger page


def test_favicon_is_an_empty_204_instead_of_a_404() -> None:
    response = TestClient(app).get("/favicon.ico")
    assert response.status_code == 204
    assert response.content == b""


def test_root_and_favicon_are_not_listed_in_the_api_documentation() -> None:
    paths = TestClient(app).get("/openapi.json").json()["paths"]
    assert "/" not in paths
    assert "/favicon.ico" not in paths
