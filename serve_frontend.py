import argparse
import http.client
import http.server
import socketserver
import urllib.parse
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent
FRONTEND_DIR = PROJECT_ROOT / "frontend"
FRONTEND_DIST_DIR = FRONTEND_DIR / "dist"
DEFAULT_API_TARGET = "http://127.0.0.1:7800"

HOP_BY_HOP_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
}


class NoCacheHandler(http.server.SimpleHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def __init__(self, *args, directory: Path, api_target: str, **kwargs):
        parsed_target = urllib.parse.urlsplit(api_target)
        if parsed_target.scheme not in {"http", "https"}:
            raise ValueError(f"Unsupported API target scheme: {parsed_target.scheme or '<missing>'}")
        self._api_target = parsed_target
        super().__init__(*args, directory=str(directory), **kwargs)

    def end_headers(self):
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        super().end_headers()

    def do_GET(self):
        if self.path.startswith("/api"):
            self._proxy_request()
            return
        super().do_GET()

    def do_HEAD(self):
        if self.path.startswith("/api"):
            self._proxy_request(send_body=False)
            return
        super().do_HEAD()

    def do_POST(self):
        if self.path.startswith("/api"):
            self._proxy_request()
            return
        self.send_error(405, "Method not allowed")

    def do_PUT(self):
        if self.path.startswith("/api"):
            self._proxy_request()
            return
        self.send_error(405, "Method not allowed")

    def do_PATCH(self):
        if self.path.startswith("/api"):
            self._proxy_request()
            return
        self.send_error(405, "Method not allowed")

    def do_DELETE(self):
        if self.path.startswith("/api"):
            self._proxy_request()
            return
        self.send_error(405, "Method not allowed")

    def do_OPTIONS(self):
        if self.path.startswith("/api"):
            self._proxy_request()
            return
        self.send_response(204)
        self.send_header("Allow", "GET, HEAD, OPTIONS")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def send_head(self):
        original_path = self.path
        parsed = urllib.parse.urlsplit(original_path)
        requested_path = parsed.path or "/"
        translated = Path(self.translate_path(requested_path))
        if translated.exists():
            return super().send_head()
        if requested_path.startswith("/assets/") or Path(requested_path).suffix:
            return super().send_head()
        self.path = "/index.html"
        try:
            return super().send_head()
        finally:
            self.path = original_path

    def _proxy_request(self, send_body: bool = True):
        upstream_path = self._build_upstream_path()
        content_length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(content_length) if content_length > 0 else None
        connection_cls = http.client.HTTPSConnection if self._api_target.scheme == "https" else http.client.HTTPConnection
        connection = connection_cls(
            self._api_target.hostname,
            self._api_target.port,
            timeout=60,
        )
        upstream_headers = self._build_upstream_headers()

        try:
            connection.request(self.command, upstream_path, body=body, headers=upstream_headers)
            response = connection.getresponse()
            payload = response.read()
            self.send_response(response.status, response.reason)
            for header_name, header_value in response.getheaders():
                if header_name.lower() in HOP_BY_HOP_HEADERS or header_name.lower() == "content-length":
                    continue
                self.send_header(header_name, header_value)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            if send_body and self.command != "HEAD":
                self.wfile.write(payload)
        except OSError as exc:
            self.send_error(502, f"API upstream unreachable: {exc}")
        finally:
            connection.close()

    def _build_upstream_headers(self):
        forwarded = {}
        for header_name, header_value in self.headers.items():
            if header_name.lower() in HOP_BY_HOP_HEADERS:
                continue
            if header_name.lower() == "host":
                continue
            forwarded[header_name] = header_value
        forwarded["Host"] = self._api_target.netloc
        forwarded["X-Forwarded-Host"] = self.headers.get("Host", "")
        forwarded["X-Forwarded-Proto"] = "https" if self.request_version.endswith("HTTPS") else "http"
        forwarded["X-Forwarded-For"] = self.client_address[0]
        return forwarded

    def _build_upstream_path(self):
        parsed = urllib.parse.urlsplit(self.path)
        upstream_path = parsed.path.removeprefix("/api") or "/"
        if parsed.query:
            return f"{upstream_path}?{parsed.query}"
        return upstream_path


class ReusableTCPServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True


def main() -> int:
    parser = argparse.ArgumentParser(description="Serve the built frontend with disabled HTTP caching.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5500)
    parser.add_argument(
        "--api-target",
        default=DEFAULT_API_TARGET,
        help=f"Backend base URL used to proxy /api requests (default: {DEFAULT_API_TARGET})",
    )
    args = parser.parse_args()

    if not FRONTEND_DIR.exists():
        raise SystemExit(f"Frontend directory not found: {FRONTEND_DIR}")
    if not FRONTEND_DIST_DIR.exists():
        raise SystemExit(
            f"Built frontend not found: {FRONTEND_DIST_DIR}\n"
            "Please run `cd frontend && npm install && npm run build` first, "
            "or use `cd frontend && npm run dev` for development."
        )

    handler = lambda *handler_args, **handler_kwargs: NoCacheHandler(
        *handler_args,
        directory=FRONTEND_DIST_DIR,
        api_target=args.api_target,
        **handler_kwargs,
    )

    with ReusableTCPServer((args.host, args.port), handler) as httpd:
        print(f"Serving built frontend from: {FRONTEND_DIST_DIR}")
        print(f"Frontend URL: http://{args.host}:{args.port}/?v=latest")
        print(f"Proxying /api to: {args.api_target}")
        httpd.serve_forever()


if __name__ == "__main__":
    raise SystemExit(main())
