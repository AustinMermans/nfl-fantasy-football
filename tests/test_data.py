from io import BytesIO
from urllib.error import HTTPError, URLError
from urllib.request import Request

import pytest

from nfl_fantasy_football import data


class Response(BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


def test_download_retries_connection_failures_atomically(monkeypatch, tmp_path) -> None:
    calls: list[Request] = []
    sleeps: list[float] = []

    def fake_urlopen(request: Request, timeout: int):
        calls.append(request)
        assert timeout == 120
        if len(calls) < 3:
            raise URLError(ConnectionResetError("reset"))
        return Response(b"complete payload")

    monkeypatch.setattr(data, "urlopen", fake_urlopen)
    monkeypatch.setattr(data.time, "sleep", sleeps.append)
    destination = tmp_path / "asset.parquet"

    data._download(
        "https://example.test/asset.parquet",
        destination,
        attempts=3,
        base_delay_seconds=0.5,
    )

    assert destination.read_bytes() == b"complete payload"
    assert not destination.with_suffix(".parquet.tmp").exists()
    assert len(calls) == 3
    assert sleeps == [0.5, 1.0]
    assert calls[0].get_header("User-agent") == (
        "nfl-fantasy-football-data-refresh/0.1"
    )


def test_download_does_not_retry_nontransient_http_errors(
    monkeypatch, tmp_path
) -> None:
    calls = 0

    def fake_urlopen(request: Request, timeout: int):
        nonlocal calls
        calls += 1
        raise HTTPError(request.full_url, 404, "Not Found", {}, None)

    monkeypatch.setattr(data, "urlopen", fake_urlopen)

    with pytest.raises(HTTPError):
        data._download("https://example.test/missing", tmp_path / "missing.parquet")

    assert calls == 1
