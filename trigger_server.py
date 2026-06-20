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
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

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
        print(f"Ricevuta richiesta GET: {self.path}", flush=True)
        u = urlparse(self.path)
        if u.path.rstrip("/") != "/cerca-news":
            print(f"Path non trovato: {u.path}", flush=True)
            return self._send(404, "🔍", "Non trovato", "Pagina inesistente.")
        token = parse_qs(u.query).get("token", [""])[0]
        if not TOKEN or token != TOKEN:
            print("Accesso negato: token non valido", flush=True)
            return self._send(403, "⛔", "Accesso negato", "Token non valido.")
        print("Avvio di notebooklm-research.service in corso...", flush=True)
        try:
            subprocess.run(
                ["systemctl", "--no-block", "start", "notebooklm-research.service"], check=True
            )
            self._send(
                200,
                "✅",
                "Ricerca avviata!",
                "Le nuove news compariranno nel database tra circa 2 minuti. "
                "Puoi chiudere questa pagina.",
            )
        except Exception as e:
            print(f"Errore durante l'avvio del servizio: {e}", flush=True)
            self._send(500, "❌", "Errore di sistema", f"Impossibile avviare il servizio: {e}")

    def log_message(self, format, *args):
        # Log standard HTTP formatting to stderr
        msg = format % args
        sys.stderr.write(f"{self.client_address[0]} - - [{self.log_date_time_string()}] {msg}\n")


if __name__ == "__main__":
    print(f"Avvio server trigger sulla porta {PORT}...", flush=True)
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
