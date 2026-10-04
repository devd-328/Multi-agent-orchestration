import asyncio
import json

from orchestration import __version__
from orchestration.api.app import create_app


def _request_json(path: str) -> tuple[int, dict[str, object]]:
    application = create_app()
    status: dict[str, int] = {}
    chunks: list[bytes] = []

    async def receive() -> dict[str, object]:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: dict[str, object]) -> None:
        if message["type"] == "http.response.start":
            status["code"] = int(message["status"])
        elif message["type"] == "http.response.body":
            body = message.get("body", b"")
            if isinstance(body, bytes):
                chunks.append(body)

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "headers": [],
        "client": ("127.0.0.1", 50000),
        "server": ("127.0.0.1", 8000),
        "root_path": "",
    }
    asyncio.run(application(scope, receive, send))
    return status["code"], json.loads(b"".join(chunks))


def test_health_returns_status_and_version() -> None:
    status, body = _request_json("/health")
    assert status == 200
    assert body == {"status": "ok", "version": __version__}
