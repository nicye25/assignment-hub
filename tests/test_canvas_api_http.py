"""Wire-level test: the real canvasapi library talking to a local fake Canvas server.

Verifies what unit fakes can't: query-string encoding (include[]=submission),
the Authorization header, and Link-header pagination.
"""
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

import pytest

from aggregator.fetchers.base import FetchError
from aggregator.fetchers.canvas_api import CanvasApiFetcher

COURSES = [{"id": 9, "name": "Probability Theory", "course_code": "STAT GU4203"}]
PAGE1 = [{"id": 1, "name": "HW 1", "due_at": "2026-10-06T03:59:59Z", "course_id": 9,
          "html_url": "https://x/1", "submission_types": ["online_upload"],
          "submission": {"workflow_state": "submitted"}}]
PAGE2 = [{"id": 2, "name": "HW 2", "due_at": "2026-10-13T03:59:59Z", "course_id": 9,
          "html_url": "https://x/2", "submission_types": ["online_upload"],
          "submission": {"workflow_state": "unsubmitted"}}]


@pytest.fixture
def server():
    seen = []
    state = {"reject_token": False}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, status, body, headers=()):
            data = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            for k, v in headers:
                self.send_header(k, v)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            url = urlparse(self.path)
            q = parse_qs(url.query)
            seen.append((url.path, q, self.headers.get("Authorization")))
            if state["reject_token"]:
                return self._send(401, {"errors": [{"message": "Invalid access token."}]},
                                  [("WWW-Authenticate", 'Bearer realm="canvas-lms"')])
            base = f"http://127.0.0.1:{self.server.server_port}"
            if url.path == "/api/v1/courses":
                return self._send(200, COURSES)
            if url.path == "/api/v1/courses/9/assignments":
                if q.get("page") == ["2"]:
                    return self._send(200, PAGE2)
                nxt = f'<{base}/api/v1/courses/9/assignments?page=2&per_page=100>; rel="next"'
                return self._send(200, PAGE1, [("Link", nxt)])
            self._send(404, {"errors": [{"message": "not found"}]})

    httpd = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_port}", seen, state
    httpd.shutdown()


def test_real_library_against_fake_server(server):
    base, seen, _ = server
    with pytest.warns(UserWarning):  # canvasapi warns about plain http
        items = CanvasApiFetcher(base, "secret-token").fetch()

    assert [(a.uid, a.submitted) for a in items] == [("canvas:9:1", True), ("canvas:9:2", False)]
    assert all(auth == "Bearer secret-token" for _, _, auth in seen)

    courses_q = next(q for path, q, _ in seen if path == "/api/v1/courses")
    assert courses_q["enrollment_state"] == ["active"]
    assert courses_q["enrollment_type"] == ["student"]
    first_assignments_q = next(q for path, q, _ in seen if path.endswith("/assignments"))
    assert first_assignments_q["include[]"] == ["submission"]


def test_rejected_token_becomes_clear_fetch_error(server):
    base, _, state = server
    state["reject_token"] = True
    with pytest.warns(UserWarning), pytest.raises(FetchError, match="invalid, expired, or revoked"):
        CanvasApiFetcher(base, "bad").fetch()
