#!/usr/bin/env python3
"""
Approfondimento on-demand: data una news/argomento, genera un KIT EDITORIALE
completo (articolo + SEO + social + immagini).

Uso da riga di comando (invia il kit via email):
    python approfondisci.py "James Stuart e il graphic design Taqwacore"

La funzione genera_kit(topic) -> markdown e' riusata anche dal controllore
Notion (notion_watcher.py).
"""

import os
import re
import sys
from datetime import date
from pathlib import Path

from daily_research import run, send_email


def pulisci(md):
    """Forza il formato KANRI sull'output di NotebookLM (che spesso devia)."""
    md = md.replace("\\*", "*").replace("\\_", "_")  # togli escape
    lines = md.splitlines()
    out, titolo_rimosso = [], False
    for ln in lines:
        st = ln.strip()
        # rimuovi un eventuale titolo "# ..." in cima (vietato dal formato)
        if not titolo_rimosso and st.startswith("# ") and not st.startswith("## "):
            titolo_rimosso = True
            continue
        out.append(ln)
    md = "\n".join(out)
    # normalizza intestazioni numerate: "## 2. SEO" -> "## SEO"
    md = re.sub(r"(?m)^(#{2,3})\s+\d+[.)]\s+", r"\1 ", md)
    return md.strip()


def genera_kit(topic):
    """Crea un notebook, ricerca l'argomento, genera il kit e ritorna il markdown."""
    today = date.today().isoformat()
    mode = os.environ.get("RESEARCH_MODE", "fast")
    timeout = int(os.environ.get("RESEARCH_TIMEOUT", "600"))
    lang = os.environ.get("REPORT_LANGUAGE", "it")

    nb = run(["create", f"Articolo {today} — {topic[:40]}", "--json"], capture_json=True)
    nbid = nb.get("id") or nb.get("notebook", {}).get("id")
    print(f"Notebook: {nbid}", flush=True)
    try:
        query = (
            f"Approfondisci con dettagli, contesto, dichiarazioni e dati il seguente "
            f"argomento di arte/design/cultura visiva: {topic}. "
            f"Cerca piu' fonti possibili, con fatti concreti, nomi e numeri, e link."
        )
        run([
            "source", "add-research", query,
            "-n", nbid, "--mode", mode, "--import-all", "--cited-only",
            "--timeout", str(timeout), "--json",
        ], capture_json=True, timeout=timeout * 2 + 60, retries=1, retry_wait=30)

        instr = Path(__file__).parent / "article_instructions.txt"
        run([
            "generate", "report", "-n", nbid, "--format", "custom",
            "--prompt-file", str(instr), "--language", lang,
            "--wait", "--timeout", "600", "--json",
        ], capture_json=True, timeout=720, retries=2, retry_wait=30)

        out = Path(f"articolo-{today}-{nbid[:6]}.md")
        run(["download", "report", str(out), "-n", nbid, "--latest", "--force"])
        body = pulisci(out.read_text(encoding="utf-8"))
        out.write_text(body, encoding="utf-8")
        print(f"Kit generato e ripulito ({len(body)} char)", flush=True)
        return body, out
    finally:
        if os.environ.get("KEEP_NOTEBOOK", "") not in ("1", "true", "yes"):
            try:
                run(["delete", "-n", nbid, "-y"])
            except Exception as e:
                print(f"(cleanup fallito, ignoro: {e})", flush=True)


def main():
    topic = " ".join(sys.argv[1:]).strip() or os.environ.get("ARTICLE_TOPIC", "").strip()
    if not topic:
        sys.exit('Uso: python approfondisci.py "argomento della news"')
    auth = run(["auth", "check", "--test", "--json"], capture_json=True)
    if auth.get("status") != "ok":
        raise RuntimeError(f"auth non valida: {auth}")
    body, out = genera_kit(topic)
    send_email(f"📝 Articolo pronto — {topic[:70]}", body, out)


if __name__ == "__main__":
    main()
