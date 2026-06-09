#!/usr/bin/env python3
"""
Brief KANRI: raccoglie le news dai feed RSS, le fa selezionare e classificare a
un LLM (OpenRouter), scrive le righe nel database Notion e invia l'email.

Sostituisce la "ricerca delle 07:00" basata su NotebookLM.
"""

import os
from datetime import date
from pathlib import Path

import kanri_engine as ke
import notion_sync
from daily_research import send_email

CATEGORIE = """- BULBOUS / MATERIAL: design scultoreo e materico, oggetti chunky, forme
  organiche/bulbose, ceramiche lucide, mobili ondulati, branded homeware.
- LO-FI UI / LAYOUT: interfacce brutaliste/funzionali, design system,
  tipografia compressa, poster e cataloghi, estetica anti-minimalista.
- RAW FRAME / VISUAL: fotografia grezza/cinematica ad alto impatto,
  automotive/moda/urbano, grana, motion blur, fish-eye.
- 4/4 LOOP / AUDIO: musica elettronica e sound design, melodic techno,
  organic house, analisi di arpeggi/progressioni, il loop come architettura.
- DESIGN MASTERS / ARCHIVE: maestri storici del design e della grafica,
  riscoperte, archivi, metodologie e processi."""

SYSTEM = (
    "Sei il caporedattore di KANRI, rivista indipendente di cultura visiva e "
    "sonora. Selezioni solo notizie forti, fresche e visivamente raccontabili, "
    "coerenti con le 5 verticali editoriali. Rispondi sempre e solo in italiano."
)


def costruisci_prompt(items):
    righe = []
    for i, it in enumerate(items):
        righe.append(f'[{i}] ({it["source"]}) {it["title"]} :: {it["summary"][:160]}')
    elenco = "\n".join(righe)
    return f"""Ecco le news di oggi dai feed (indice tra parentesi quadre):

{elenco}

Le 5 categorie di KANRI:
{CATEGORIE}

Seleziona le 7 notizie PIÙ interessanti per KANRI (scarta gossip, tech
generalista, pubblicità, e i doppioni). Per ognuna restituisci un oggetto JSON:
- "idx": l'indice della news nell'elenco
- "titolo": un titolo in stile magazine, in italiano (riscritto, accattivante)
- "categoria": ESATTAMENTE una tra: BULBOUS / MATERIAL, LO-FI UI / LAYOUT,
  RAW FRAME / VISUAL, 4/4 LOOP / AUDIO, DESIGN MASTERS / ARCHIVE
- "di_cosa_parla": 3-4 frasi in italiano che spiegano bene la notizia
- "perche": una frase sul perché interessa al lettore di KANRI

Rispondi SOLO con un array JSON di 7 oggetti, niente altro."""


def main():
    today = date.today().isoformat()
    feeds = Path(__file__).parent / "kanri_feeds.txt"

    items = ke.fetch_rss_items(str(feeds), max_age_days=4, per_feed=8)
    print(f"RSS: {len(items)} news raccolte", flush=True)

    # anti-ripetizione: scarta le news gia' coperte negli ultimi 7 giorni
    nt, ndb = os.environ.get("NOTION_TOKEN"), os.environ.get("NOTION_DB_ID")
    if nt and ndb:
        coperti = notion_sync.urls_coperti(nt, ndb, days=7)
        items = [it for it in items if it["url"].rstrip("/") not in coperti]
        print(f"  dopo anti-ripetizione: {len(items)} news nuove ({len(coperti)} gia' coperte)", flush=True)
    if not items:
        raise SystemExit("nessuna news nuova dai feed")

    scelte = ke.llm_json(
        [{"role": "system", "content": SYSTEM},
         {"role": "user", "content": costruisci_prompt(items)}],
        max_tokens=8000, temperature=0.5)
    print(f"LLM: {len(scelte)} news selezionate", flush=True)

    # costruisci gli item per Notion + il corpo email
    notizie, righe_md = [], ["# Brief KANRI — " + today, ""]
    for s in scelte:
        if not isinstance(s, dict):
            continue
        idx = s.get("idx")
        src = items[idx] if isinstance(idx, int) and 0 <= idx < len(items) else {}
        cat = notion_sync.normalizza_categoria(s.get("categoria", ""))
        fonte = f'{src.get("source", "")} ({src.get("url", "")})'.strip()
        notizie.append({
            "title": s.get("titolo", src.get("title", ""))[:200],
            "summary": s.get("di_cosa_parla", "")[:1900],
            "categoria": cat,
            "fonte": fonte[:1900],
        })
        righe_md += [
            f'## {s.get("titolo", "")}',
            f'- **Di cosa parla:** {s.get("di_cosa_parla", "")}',
            f'- **Perché pubblicarlo:** {s.get("perche", "")}',
            f'- **Categoria:** {cat or "—"}',
            f'- **Fonte:** {fonte}', ""]

    # scrivi su Notion
    nt, ndb = os.environ.get("NOTION_TOKEN"), os.environ.get("NOTION_DB_ID")
    if nt and ndb:
        n = notion_sync.add_news_rows(nt, ndb, notizie, today)
        print(f"Notion: {n} news aggiunte", flush=True)

    # email
    body = "\n".join(righe_md)
    send_email(f"🗞️ Brief KANRI {today} — {len(notizie)} news", body,
               _scrivi_file(today, body))


def _scrivi_file(today, body):
    p = Path(f"brief-{today}.md")
    p.write_text(body, encoding="utf-8")
    return p


if __name__ == "__main__":
    import time
    import traceback
    from datetime import date as _date
    for _tentativo in range(2):
        try:
            main()
            break
        except SystemExit:
            raise  # "nessuna news nuova" non è un errore: non avvisare
        except Exception:
            if _tentativo == 0:
                print("Brief fallito, riprovo tra 120s...", flush=True)
                time.sleep(120)
                continue
            ke.alert(f"⚠️ Brief KANRI FALLITO — {_date.today().isoformat()}",
                     "Il brief di oggi non è stato generato dopo 2 tentativi.\n\n"
                     + traceback.format_exc())
            raise
