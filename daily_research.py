#!/usr/bin/env python3
"""
Deep research giornaliera con NotebookLM -> report Markdown -> email.

Flusso:
  1. crea un notebook "Daily Research <data>"
  2. lancia una web research (deep/fast) e importa le fonti citate
  3. genera un report (briefing-doc) e lo scarica in Markdown
  4. invia il report via email (Gmail SMTP)
  5. (opzionale) cancella il notebook per non accumulare

L'autenticazione NotebookLM e' letta dal CLI tramite la variabile
NOTEBOOKLM_AUTH_JSON (contenuto di storage_state.json) oppure dal file
~/.notebooklm/profiles/default/storage_state.json in locale.

Variabili d'ambiente:
  RESEARCH_QUERY        domanda fissa (oppure usa il file prompt.txt)
  RESEARCH_MODE         "deep" (default) | "fast"
  RESEARCH_TIMEOUT      secondi per fase (default 1800)
  REPORT_LANGUAGE       lingua del report (default "it")
  KEEP_NOTEBOOK         "1" per NON cancellare il notebook (default: cancella)
  RESEND_API_KEY        API key di Resend (https://resend.com/api-keys)
  MAIL_FROM             mittente (default: onboarding@resend.dev)
  MAIL_TO               destinatario (obbligatorio)
"""

import os
import sys
import json
import base64
import urllib.request
import urllib.error
import subprocess
from datetime import date
from pathlib import Path

NB = None  # id del notebook creato (per cleanup)


def run(args, capture_json=False, timeout=None):
    """Esegue il CLI notebooklm; opzionalmente parsa l'output JSON."""
    cmd = ["notebooklm", "--quiet"] + args
    print("» " + " ".join(cmd), flush=True)
    res = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if res.returncode != 0:
        sys.stderr.write(res.stdout + "\n" + res.stderr + "\n")
        raise RuntimeError(f"comando fallito ({res.returncode}): {' '.join(args)}")
    if capture_json:
        return json.loads(res.stdout)
    return res.stdout


def get_query():
    q = os.environ.get("RESEARCH_QUERY", "").strip()
    if q:
        return q
    pf = Path(__file__).parent / "prompt.txt"
    if pf.exists():
        return pf.read_text(encoding="utf-8").strip()
    sys.exit("ERRORE: nessuna domanda. Imposta RESEARCH_QUERY o crea prompt.txt")


def md_to_html(md):
    """Conversione minimale Markdown -> HTML (titoli, grassetto, liste)."""
    import re
    html_lines = []
    for line in md.splitlines():
        if line.startswith("### "):
            html_lines.append(f"<h3>{line[4:]}</h3>")
        elif line.startswith("## "):
            html_lines.append(f"<h2>{line[3:]}</h2>")
        elif line.startswith("# "):
            html_lines.append(f"<h1>{line[2:]}</h1>")
        elif line.strip().startswith(("- ", "* ")):
            html_lines.append(f"<li>{line.strip()[2:]}</li>")
        elif line.strip() == "":
            html_lines.append("<br>")
        else:
            html_lines.append(f"<p>{line}</p>")
    html = "\n".join(html_lines)
    html = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", html)
    return f'<div style="font-family:sans-serif;max-width:680px;margin:auto">{html}</div>'


def send_email(subject, markdown_body, attachment_path):
    api_key = os.environ.get("RESEND_API_KEY")
    to = os.environ.get("MAIL_TO")
    if not api_key or not to:
        print("(RESEND_API_KEY/MAIL_TO non impostate: salto l'invio email)")
        print(f"--- {subject} ---")
        print(markdown_body[:500] + ("..." if len(markdown_body) > 500 else ""))
        return
    sender = os.environ.get("MAIL_FROM", "onboarding@resend.dev")

    attachment = base64.b64encode(Path(attachment_path).read_bytes()).decode()
    payload = {
        "from": sender,
        "to": [to],
        "subject": subject,
        "html": md_to_html(markdown_body),
        "attachments": [
            {"filename": Path(attachment_path).name, "content": attachment}
        ],
    }
    req = urllib.request.Request(
        "https://api.resend.com/emails",
        data=json.dumps(payload).encode(),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "daily-research/1.0",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = json.loads(resp.read())
        print(f"Email inviata a {to} (id: {body.get('id')})", flush=True)
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"Resend errore {e.code}: {e.read().decode()}")


def main():
    global NB
    today = date.today().isoformat()
    query = get_query()
    mode = os.environ.get("RESEARCH_MODE", "deep")
    timeout = int(os.environ.get("RESEARCH_TIMEOUT", "1800"))
    lang = os.environ.get("REPORT_LANGUAGE", "it")  # lingua del report

    # 1. verifica auth (chiamata di rete reale)
    auth = run(["auth", "check", "--test", "--json"], capture_json=True)
    if auth.get("status") != "ok":
        raise RuntimeError(f"auth non valida: {auth}")
    print("Auth OK", flush=True)

    # 2. crea notebook
    nb = run(["create", f"Daily Research {today}", "--json"], capture_json=True)
    NB = nb.get("id") or nb.get("notebook", {}).get("id")
    print(f"Notebook: {NB}", flush=True)

    # 3. web research + import fonti citate
    run([
        "source", "add-research", query,
        "-n", NB, "--mode", mode, "--import-all", "--cited-only",
        "--timeout", str(timeout), "--json",
    ], capture_json=True, timeout=timeout * 2 + 120)

    # 4. report + download markdown
    run([
        "generate", "report", "-n", NB, "--format", "briefing-doc",
        "--language", lang,
        "--append", "Scrivi il report interamente in italiano.",
        "--wait", "--timeout", "600", "--json",
    ], capture_json=True, timeout=720)

    out = Path(f"report-{today}.md")
    run(["download", "report", str(out), "-n", NB, "--latest", "--force"])
    body = out.read_text(encoding="utf-8")
    print(f"Report scaricato: {out} ({len(body)} char)", flush=True)

    # 5. email
    first_line = body.lstrip("# ").splitlines()[0] if body.strip() else "Daily Research"
    send_email(f"🧠 Daily Research {today} — {first_line[:80]}", body, out)


if __name__ == "__main__":
    try:
        main()
    finally:
        # cleanup notebook (a meno che KEEP_NOTEBOOK=1)
        if NB and os.environ.get("KEEP_NOTEBOOK", "") not in ("1", "true", "yes"):
            try:
                run(["delete", "-n", NB, "-y"])
                print(f"Notebook {NB} cancellato", flush=True)
            except Exception as e:
                print(f"(cleanup fallito, ignoro: {e})", flush=True)
