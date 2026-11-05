"""A tiny local HTTP server for fetch tests. No real network.

    server.route("/robots.txt", body="User-agent: *\\nDisallow: /private")
    server.route("/flaky", Reply(503), Reply(503), Reply(200, "ok"))   # one reply per call
    url = server.url("/flaky")              # http://127.0.0.1:<port>/flaky
    url = server.url("/flaky", host="localhost")   # same server, different host name

The last reply in a route repeats. server.requests records (host, path, headers).
"""

import threading
import time
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


@dataclass
class Reply:
    status: int = 200
    body: bytes | str = b""
    headers: dict[str, str] = field(default_factory=dict)
    delay: float = 0.0  # seconds before answering

    def payload(self) -> bytes:
        return self.body.encode("utf-8") if isinstance(self.body, str) else self.body


@dataclass
class SeenRequest:
    host: str
    path: str
    headers: dict[str, str]


class FixtureServer:
    def __init__(self) -> None:
        self.routes: dict[str, list[Reply]] = {}
        self.requests: list[SeenRequest] = []
        self._lock = threading.Lock()
        server = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                host = self.headers.get("Host", "").split(":")[0]
                with server._lock:
                    server.requests.append(SeenRequest(host, self.path, dict(self.headers)))
                    replies = server.routes.get(self.path)
                    reply = (
                        (replies.pop(0) if len(replies) > 1 else replies[0]) if replies else None
                    )
                if reply is None:
                    reply = Reply(404, "not found")
                if reply.delay:
                    time.sleep(reply.delay)
                try:
                    self.send_response(reply.status)
                    headers = {"Content-Type": "text/html; charset=utf-8", **reply.headers}
                    for k, v in headers.items():
                        self.send_header(k, v)
                    data = reply.payload()
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                except (BrokenPipeError, ConnectionResetError):
                    pass  # client gave up (timeout tests)

            def log_message(self, *args: object) -> None:
                pass

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.httpd.daemon_threads = True
        self.port = self.httpd.server_address[1]
        self._thread = threading.Thread(
            target=self.httpd.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True
        )

    def start(self) -> "FixtureServer":
        self._thread.start()
        return self

    def stop(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()

    def route(self, path: str, *replies: Reply, body: bytes | str | None = None) -> None:
        if body is not None:
            replies = (Reply(200, body),)
        self.routes[path] = list(replies)

    def url(self, path: str, host: str = "127.0.0.1") -> str:
        return f"http://{host}:{self.port}{path}"

    def hits(self, path: str) -> int:
        return sum(r.path == path for r in self.requests)


class FakeClock:
    """Stands in for time.monotonic/time.sleep so rate-limit tests run instantly."""

    def __init__(self) -> None:
        self.now = 1000.0
        self.sleeps: list[float] = []

    def clock(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds
