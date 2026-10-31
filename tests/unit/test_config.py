import pytest

from medagent.core.config import Settings


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("http://localhost:3000", ["http://localhost:3000"]),
        ("http://a.test, http://b.test", ["http://a.test", "http://b.test"]),
        ('["http://a.test"]', ["http://a.test"]),
    ],
)
def test_cors_origins_accept_csv_and_json(
    monkeypatch: pytest.MonkeyPatch, raw: str, expected: list[str]
) -> None:
    monkeypatch.setenv("API_CORS_ORIGINS", raw)
    assert Settings(_env_file=None).api_cors_origins == expected  # type: ignore[call-arg]


def test_defaults_match_the_vector_column() -> None:
    from medagent.db.models import EMBEDDING_DIM

    assert Settings(_env_file=None).embedding_dim == EMBEDDING_DIM  # type: ignore[call-arg]
