#!/usr/bin/env python3
"""
Deep research giornaliera con NotebookLM -> report Markdown -> email.

Flusso:
  1. crea un notebook "Daily Research <data>"
  2. lancia una web research (deep/fast) e importa le fonti citate
  3. genera un report editoriale e lo scarica in Markdown
  4. invia il report via email (Resend API)
  5. (opzionale) cancella il notebook per non accumulare

L'autenticazione NotebookLM e' letta dal CLI tramite la variabile
NOTEBOOKLM_AUTH_JSON (contenuto di storage_state.json) oppure dal file
~/.notebooklm/profiles/default/storage_state.json in locale.

Variabili d'ambiente:
  RESEARCH_QUERY        domanda fissa (oppure usa il file prompt.txt)
  RESEARCH_MODE         "fast" (default) | "deep"
  RESEARCH_TIMEOUT      tetto secondi per fase (default 600)
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

# Risolve l'eseguibile "notebooklm": prima nel venv corrente (stesso bin di
# python, utile sotto systemd dove il PATH e' minimale), poi dal PATH.
_VENV_BIN = os.path.join(os.path.dirname(sys.executable), "notebooklm")
NOTEBOOKLM_BIN = _VENV_BIN if os.path.exists(_VENV_BIN) else "notebooklm"


def run(args, capture_json=False, timeout=None, retries=0, retry_wait=30):
    """Esegue il CLI notebooklm; opzionalmente parsa JSON e ritenta su errore.

    L'API e' non ufficiale e ogni tanto fallisce in modo transitorio:
    con retries>0 il comando viene ritentato qualche volta prima di arrendersi.
    """
    import time
    cmd = [NOTEBOOKLM_BIN, "--quiet"] + args
    last_err = "?"
    for attempt in range(retries + 1):
        print("» " + " ".join(cmd[:4]) + (" ..." if len(cmd) > 4 else ""), flush=True)
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            last_err = f"timeout dopo {timeout}s"
            sys.stderr.write(last_err + "\n")
        else:
            if res.returncode == 0:
                return json.loads(res.stdout) if capture_json else res.stdout
            last_err = f"exit {res.returncode}"
            sys.stderr.write((res.stdout or "") + "\n" + (res.stderr or "") + "\n")
        if attempt < retries:
            print(f"  ↻ tentativo {attempt + 1} fallito ({last_err}), riprovo tra {retry_wait}s...", flush=True)
            time.sleep(retry_wait)
    raise RuntimeError(f"comando fallito ({last_err}): {args[0]} {args[1] if len(args) > 1 else ''}")


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
    import html as _html

    def fmt(text):
        # sanitizza poi applica il grassetto **...**
        text = _html.escape(text)
        return re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)

    out, in_list = [], False
    def close_list():
        nonlocal in_list
        if in_list:
            out.append("</ul>")
            in_list = False

    for line in md.splitlines():
        s = line.strip()
        if s.startswith(("- ", "* ")):
            if not in_list:
                out.append("<ul>")
                in_list = True
            out.append(f"<li>{fmt(s[2:])}</li>")
            continue
        close_list()
        if line.startswith("### "):
            out.append(f"<h3>{fmt(line[4:])}</h3>")
        elif line.startswith("## "):
            out.append(f"<h2>{fmt(line[3:])}</h2>")
        elif line.startswith("# "):
            out.append(f"<h1>{fmt(line[2:])}</h1>")
        elif s == "":
            continue
        else:
            out.append(f"<p>{fmt(line)}</p>")
    close_list()
    body = "\n".join(out)
    return f'<div style="font-family:sans-serif;max-width:680px;margin:auto;line-height:1.5">{body}</div>'


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
    mode = os.environ.get("RESEARCH_MODE", "fast")
    timeout = int(os.environ.get("RESEARCH_TIMEOUT", "600"))  # tetto per fase (s)
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

    # 3. web research + import fonti citate (con retry: API non ufficiale)
    run([
        "source", "add-research", query,
        "-n", NB, "--mode", mode, "--import-all", "--cited-only",
        "--timeout", str(timeout), "--json",
    ], capture_json=True, timeout=timeout * 2 + 60, retries=1, retry_wait=30)

    # 4. report editoriale custom + download markdown
    instr_file = Path(__file__).parent / "report_instructions.txt"
    run([
        "generate", "report", "-n", NB, "--format", "custom",
        "--prompt-file", str(instr_file),
        "--language", lang,
        "--wait", "--timeout", "600", "--json",
    ], capture_json=True, timeout=720, retries=2, retry_wait=30)

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
