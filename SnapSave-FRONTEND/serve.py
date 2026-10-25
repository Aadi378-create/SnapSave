#!/usr/bin/env python3
"""No-cache static file server for SnapSave frontend development."""
import http.server
import os
from pathlib import Path
from urllib.parse import unquote,urlsplit

PORT = 3000

class NoCacheHandler(http.server.SimpleHTTPRequestHandler):
    PUBLIC_FILES={'index.html','admin.html','common.js','phone-login.js','phone-login.css','conversation.js','conversation.css','config.js','404.html','QR.jpeg','favicon.ico'}
    PUBLIC_FILES.update({'assets/vendor/fontawesome/LICENSE.txt','assets/vendor/fonts/outfit-OFL.txt','assets/vendor/fonts/plusjakartasans-OFL.txt','assets/vendor/fonts/jetbrainsmono-OFL.txt'})
    def send_head(self):
        try:
            host=urlsplit('//'+self.headers.get('Host','')).hostname
            if host not in {'localhost','127.0.0.1'} or len(self.headers.get_all('Host',[]))!=1:
                self.send_error(400,'Invalid Host');return None
            path=unquote(urlsplit(self.path).path).lstrip('/') or 'index.html'
            root=Path(self.directory).resolve();target=(root/path).resolve()
            public=path in self.PUBLIC_FILES or (path.startswith('assets/') and target.suffix.lower() in {'.png','.jpg','.jpeg','.webp','.gif','.svg','.ico','.css','.js','.woff','.woff2','.ttf'})
            if not public or not target.is_relative_to(root) or not target.is_file() or any(part.startswith('.') for part in Path(path).parts):
                self.send_error(404);return None
        except (ValueError,OSError):
            self.send_error(404);return None
        return super().send_head()

    def end_headers(self):
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('X-Frame-Options','DENY')
        self.send_header('Referrer-Policy','strict-origin-when-cross-origin')
        self.send_header('Content-Security-Policy',"frame-ancestors 'none'; base-uri 'self'; object-src 'none'")
        super().end_headers()

    def log_message(self, format, *args):
        print(f"[Frontend] {self.address_string()} - {format % args}")

if __name__=='__main__':
    from functools import partial
    handler=partial(NoCacheHandler,directory=str(Path(__file__).resolve().parent))
    with http.server.ThreadingHTTPServer(("127.0.0.1", PORT), handler) as httpd:
        print(f"[Frontend] Serving at http://127.0.0.1:{PORT}")
        httpd.serve_forever()
