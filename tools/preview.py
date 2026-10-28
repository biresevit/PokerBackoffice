"""Local-only preview using real customer data; never deploy this server."""
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlsplit, parse_qsl
import argparse
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "api"))
from backoffice.app import Request, handle
from backoffice.store import Context


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=4280)
    parser.add_argument("--customer-id", type=int, default=14004)
    args = parser.parse_args()

    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *a, **kw):
            super().__init__(*a, directory=str(ROOT / "frontend"), **kw)

        def dispatch(self):
            if self.headers.get("Host") not in (f"127.0.0.1:{args.port}", f"localhost:{args.port}"):
                self.send_error(403, "Loopback host required")
                return
            parsed = urlsplit(self.path)
            if parsed.path.startswith("/api/"):
                # Local mutations still require the custom header, preventing
                # cross-origin forms from using this loopback development server.
                size = int(self.headers.get("Content-Length", "0"))
                if size > 2 * 1024 * 1024:
                    self.send_error(413)
                    return
                result = handle(Request(self.command, parsed.path, dict(self.headers),
                    dict(parse_qsl(parsed.query)), self.rfile.read(size)),
                    local_context=Context(args.customer_id, "local", "preview", "operator"))
                self.send_response(result.status)
                for key, value in result.headers.items():
                    self.send_header(key, value)
                self.end_headers()
                self.wfile.write(result.body)
            elif self.command == "GET":
                super().do_GET()
            else:
                self.send_error(405)

        do_GET = do_POST = do_PUT = do_DELETE = dispatch

    print(f"Local preview: http://127.0.0.1:{args.port}", flush=True)
    ThreadingHTTPServer(("127.0.0.1", args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
