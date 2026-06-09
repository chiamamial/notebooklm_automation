#!/usr/bin/env python3
"""
Controllore Notion: cerca le righe con "Scrivi articolo" spuntato, genera il
kit editoriale e lo scrive dentro la pagina Notion, poi mette Stato = Fatto.

Pensato per girare ogni pochi minuti (systemd timer).
Variabili d'ambiente: NOTION_TOKEN, NOTION_DB_ID (+ quelle di ricerca/email).
"""

import os
import sys

import notion_sync
from kanri_article import genera_articolo


def main():
    token = os.environ.get("NOTION_TOKEN")
    db = os.environ.get("NOTION_DB_ID")
    if not token or not db:
        sys.exit("NOTION_TOKEN / NOTION_DB_ID non impostati")

    rows = notion_sync.find_checked(token, db)
    if not rows:
        print("Nessuna riga da approfondire.", flush=True)
        return
    print(f"{len(rows)} riga/e da approfondire.", flush=True)

    for r in rows:
        print(f"→ Approfondisco: {r['title'][:60]}", flush=True)
        notion_sync.set_status(token, r["page_id"], "In corso")
        try:
            body, cover, slug = genera_articolo(
                r["title"], r.get("summary", ""), r.get("fonte_url", ""),
                categoria=r.get("categoria", ""), exclude_id=r["page_id"])
            notion_sync.append_markdown(token, r["page_id"], body)
            if cover:
                notion_sync.set_cover(token, r["page_id"], cover)
            if slug:
                notion_sync.set_slug(token, r["page_id"], slug)
            notion_sync.uncheck(token, r["page_id"])
            notion_sync.set_status(token, r["page_id"], "Fatto")
            print(f"  ✓ articolo scritto nella pagina Notion", flush=True)
        except Exception as e:
            # rimette "Da fare" cosi' viene ritentato al prossimo giro
            notion_sync.set_status(token, r["page_id"], "Da fare")
            print(f"  ✗ errore, riprovero': {e}", flush=True)


if __name__ == "__main__":
    main()
