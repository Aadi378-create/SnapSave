#!/usr/bin/env python3
"""No-cache static file server for SnapSave frontend development."""
import http.server
import os

PORT = 3000

class NoCacheHandler(http.server.SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        super().end_headers()

    def log_message(self, format, *args):
        print(f"[Frontend] {self.address_string()} - {format % args}")

os.chdir(os.path.dirname(os.path.abspath(__file__)))

with http.server.HTTPServer(("127.0.0.1", PORT), NoCacheHandler) as httpd:
    print(f"[Frontend] Serving at http://127.0.0.1:{PORT}")
    print(f"[Frontend] Cache-Control: no-store (always fresh)")
    httpd.serve_forever()
