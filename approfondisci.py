#!/usr/bin/env python3
"""
Approfondimento on-demand: data una news/argomento, genera un KIT EDITORIALE
completo (articolo + SEO + social + immagini) e lo invia via email.

Uso:
    python approfondisci.py "James Stuart e il graphic design Taqwacore"
oppure con la variabile d'ambiente:
    ARTICLE_TOPIC="..." python approfondisci.py

Riusa il motore di daily_research.py (stessa sessione NotebookLM, stessa email).
"""

import os
import sys
from datetime import date
from pathlib import Path

# Riusa le funzioni gia' pronte
from daily_research import run, send_email

NB = None


def main():
    global NB
    topic = " ".join(sys.argv[1:]).strip() or os.environ.get("ARTICLE_TOPIC", "").strip()
    if not topic:
        sys.exit('Uso: python approfondisci.py "argomento della news"')

    today = date.today().isoformat()
    mode = os.environ.get("RESEARCH_MODE", "fast")
    timeout = int(os.environ.get("RESEARCH_TIMEOUT", "600"))
    lang = os.environ.get("REPORT_LANGUAGE", "it")

    # 1. auth
    auth = run(["auth", "check", "--test", "--json"], capture_json=True)
    if auth.get("status") != "ok":
        raise RuntimeError(f"auth non valida: {auth}")
    print("Auth OK", flush=True)

    # 2. notebook dedicato a questo articolo
    nb = run(["create", f"Articolo {today} — {topic[:40]}", "--json"], capture_json=True)
    NB = nb.get("id") or nb.get("notebook", {}).get("id")
    print(f"Notebook: {NB}", flush=True)

    # 3. ricerca mirata sull'argomento
    query = (
        f"Approfondisci con dettagli, contesto, dichiarazioni e dati il seguente "
        f"argomento di arte/design/cultura visiva: {topic}. "
        f"Cerca piu' fonti possibili, con fatti concreti, nomi e numeri, e link."
    )
    run([
        "source", "add-research", query,
        "-n", NB, "--mode", mode, "--import-all", "--cited-only",
        "--timeout", str(timeout), "--json",
    ], capture_json=True, timeout=timeout * 2 + 60, retries=1, retry_wait=30)

    # 4. genera il kit editoriale
    instr = Path(__file__).parent / "article_instructions.txt"
    run([
        "generate", "report", "-n", NB, "--format", "custom",
        "--prompt-file", str(instr), "--language", lang,
        "--wait", "--timeout", "600", "--json",
    ], capture_json=True, timeout=720, retries=2, retry_wait=30)

    out = Path(f"articolo-{today}.md")
    run(["download", "report", str(out), "-n", NB, "--latest", "--force"])
    body = out.read_text(encoding="utf-8")
    print(f"Kit scaricato: {out} ({len(body)} char)", flush=True)

    # 5. email
    send_email(f"📝 Articolo pronto — {topic[:70]}", body, out)


if __name__ == "__main__":
    try:
        main()
    finally:
        if NB and os.environ.get("KEEP_NOTEBOOK", "") not in ("1", "true", "yes"):
            try:
                run(["delete", "-n", NB, "-y"])
                print(f"Notebook {NB} cancellato", flush=True)
            except Exception as e:
                print(f"(cleanup fallito, ignoro: {e})", flush=True)
