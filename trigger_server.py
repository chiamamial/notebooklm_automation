#!/usr/bin/env python3
"""
Mini "ricevitore" web: quando viene chiamato l'indirizzo
    /cerca-news?token=XXX
avvia la ricerca news (notebooklm-research.service) e mostra una pagina di
conferma. Pensato per essere chiamato da un pulsante Notion ("Apri link").

Variabili d'ambiente: TRIGGER_TOKEN (obbligatoria), TRIGGER_PORT (default 8765)
"""

import os
import subprocess
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs

TOKEN = os.environ.get("TRIGGER_TOKEN", "")
PORT = int(os.environ.get("TRIGGER_PORT", "8765"))

PAGE = """<!doctype html><html lang="it"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title></head>
<body style="font-family:system-ui,sans-serif;max-width:460px;margin:64px auto;
text-align:center;color:#1a1a1a;line-height:1.5">
<div style="font-size:48px">{emoji}</div>
<h1 style="font-size:22px">{title}</h1>
<p style="color:#555">{msg}</p>
</body></html>"""


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, emoji, title, msg):
        body = PAGE.format(emoji=emoji, title=title, msg=msg).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        u = urlparse(self.path)
        if u.path.rstrip("/") != "/cerca-news":
            return self._send(404, "🔍", "Non trovato", "Pagina inesistente.")
        token = parse_qs(u.query).get("token", [""])[0]
        if not TOKEN or token != TOKEN:
            return self._send(403, "⛔", "Accesso negato", "Token non valido.")
        subprocess.run(["systemctl", "--no-block", "start", "notebooklm-research.service"])
        self._send(200, "✅", "Ricerca avviata!",
                   "Le nuove news compariranno nel database tra circa 2 minuti. "
                   "Puoi chiudere questa pagina.")

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    HTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
