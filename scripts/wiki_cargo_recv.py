import sys
from http.server import BaseHTTPRequestHandler, HTTPServer

OUT = sys.argv[1]
N = int(sys.argv[2])
got = []


class H(BaseHTTPRequestHandler):
    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(n)
        name = self.path.strip("/") or "body"
        with open(OUT + "." + name, "wb") as f:
            f.write(body)
        got.append(name)
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.end_headers()

    def log_message(self, *a):
        pass


srv = HTTPServer(("127.0.0.1", 8765), H)
while len(got) < N:
    srv.handle_request()
print("received", got)
