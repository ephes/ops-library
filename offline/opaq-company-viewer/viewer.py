"""Company HTML-only loopback viewer; TLS/authentication belongs to Traefik."""

import argparse
from functools import partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os
from pathlib import Path
import stat
from urllib.parse import urlsplit

ROUTES = {
    "/": "index.html",
    "/index.html": "index.html",
    "/retained-last-good.html": "retained-last-good.html",
    "/no-accepted.html": "no-accepted.html",
}
MAX_HTML = 2 * 1024 * 1024


class Viewer(BaseHTTPRequestHandler):
    timeout = 10

    def __init__(self, *args, root, **kwargs):
        self.root = Path(root)
        super().__init__(*args, **kwargs)

    def log_message(self, *_args):
        # Do not log URLs, client identities or Authorization headers.
        pass

    def end_headers(self):
        self.send_header("Cache-Control", "private, no-store")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "SAMEORIGIN")
        super().end_headers()

    def serve(self, *, head=False):
        try:
            name = ROUTES.get(urlsplit(self.path).path)
            if name is None:
                raise ValueError("unserved path")
            descriptor = os.open(
                self.root / name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
            )
            with os.fdopen(descriptor, "rb") as stream:
                info = os.fstat(stream.fileno())
                if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_HTML:
                    raise ValueError("bounded regular HTML required")
                content = stream.read(MAX_HTML + 1)
                if len(content) > MAX_HTML:
                    raise ValueError("HTML grew beyond limit")
        except (OSError, ValueError):
            self.send_error(404, "Not found")
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        if not head:
            self.wfile.write(content)

    def do_GET(self):
        self.serve()

    def do_HEAD(self):
        self.serve(head=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True)
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error("unprivileged port required")
    with ThreadingHTTPServer(
        ("127.0.0.1", args.port), partial(Viewer, root=args.root)
    ) as server:
        server.serve_forever()
