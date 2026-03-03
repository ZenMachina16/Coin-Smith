"""
Coin Smith — Web Server (stdlib only, no Flask dependency)

Serves:
  GET  /api/health           → { "ok": true }
  POST /api/build            → run cli.py on submitted fixture JSON, return report
  GET  /*                    → static files from web/dist/
"""

import http.server
import json
import os
import subprocess
import sys
import tempfile
import urllib.parse
from pathlib import Path

PORT = int(os.environ.get("PORT", 3000))
REPO_ROOT = Path(__file__).parent.resolve()
STATIC_DIR = REPO_ROOT / "web" / "dist"
PYTHON_BIN = REPO_ROOT / "venv" / "bin" / "python"
CLI_SCRIPT = REPO_ROOT / "cli.py"


class CoinSmithHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        # Suppress default request logs to stderr (keep it clean)
        pass

    # ── routing ───────────────────────────────────────────────────────────────

    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path

        if path == "/api/health":
            self._json(200, {"ok": True})
        elif path.startswith("/api/"):
            self._json(404, {"ok": False, "error": "Not found"})
        elif path.startswith("/fixtures/"):
            self._serve_fixture(path)
        else:
            self._serve_static(path)

    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path

        if path == "/api/build":
            self._handle_build()
        else:
            self._json(404, {"ok": False, "error": "Not found"})

    def do_OPTIONS(self):
        self.send_response(200)
        self._cors_headers()
        self.end_headers()

    # ── API handlers ──────────────────────────────────────────────────────────

    def _handle_build(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)

        try:
            fixture = json.loads(body)
        except json.JSONDecodeError as exc:
            self._json(400, {
                "ok": False,
                "error": {"code": "INVALID_JSON", "message": str(exc)}
            })
            return

        # Write fixture to a temp file and run cli.py
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, prefix="coinsmith_fixture_"
        ) as fxf:
            json.dump(fixture, fxf)
            fixture_path = fxf.name

        output_path = fixture_path.replace(".json", "_out.json")

        try:
            result = subprocess.run(
                [str(PYTHON_BIN), str(CLI_SCRIPT), fixture_path, output_path],
                capture_output=True,
                text=True,
                timeout=30,
            )
            with open(output_path, "r") as f:
                report = json.load(f)

            status = 200 if report.get("ok") else 400
            self._json(status, report)

        except subprocess.TimeoutExpired:
            self._json(504, {
                "ok": False,
                "error": {"code": "TIMEOUT", "message": "Builder timed out"}
            })
        except Exception as exc:
            self._json(500, {
                "ok": False,
                "error": {"code": "SERVER_ERROR", "message": str(exc)}
            })
        finally:
            for path in [fixture_path, output_path]:
                try:
                    os.unlink(path)
                except FileNotFoundError:
                    pass

    # ── static file serving ───────────────────────────────────────────────────

    def _serve_fixture(self, path: str):
        """Serve a fixture JSON file from the repo's fixtures/ directory."""
        filename = path.split("/fixtures/", 1)[-1]
        # Basic path traversal guard
        if ".." in filename or "/" in filename:
            self._json(400, {"error": "Bad request"})
            return
        file_path = REPO_ROOT / "fixtures" / filename
        if not file_path.exists() or not file_path.suffix == ".json":
            self._json(404, {"error": "Fixture not found"})
            return
        data = file_path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self._cors_headers()
        self.end_headers()
        self.wfile.write(data)

    def _serve_static(self, path: str):
        if path == "/" or not path:
            path = "/index.html"

        file_path = STATIC_DIR / path.lstrip("/")

        # SPA fallback: any unknown route → index.html
        if not file_path.exists() or file_path.is_dir():
            file_path = STATIC_DIR / "index.html"

        if not file_path.exists():
            self._json(404, {"error": "Not found"})
            return

        ext = file_path.suffix.lower()
        mime_types = {
            ".html": "text/html; charset=utf-8",
            ".js":   "application/javascript",
            ".css":  "text/css",
            ".json": "application/json",
            ".svg":  "image/svg+xml",
            ".png":  "image/png",
            ".ico":  "image/x-icon",
            ".woff2": "font/woff2",
            ".woff":  "font/woff",
        }
        content_type = mime_types.get(ext, "application/octet-stream")

        data = file_path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self._cors_headers()
        self.end_headers()
        self.wfile.write(data)

    # ── helpers ───────────────────────────────────────────────────────────────

    def _json(self, status: int, payload: dict):
        body = json.dumps(payload, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self._cors_headers()
        self.end_headers()
        self.wfile.write(body)

    def _cors_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")


def main():
    server = http.server.ThreadingHTTPServer(("127.0.0.1", PORT), CoinSmithHandler)
    url = f"http://127.0.0.1:{PORT}"
    print(url, flush=True)
    sys.stderr.write(f"Coin Smith server running at {url}\n")
    server.serve_forever()


if __name__ == "__main__":
    main()
