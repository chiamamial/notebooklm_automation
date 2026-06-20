#!/usr/bin/env python3
"""
Pulizia KANRI: archivia le news mai lavorate e ferme da troppo tempo.

Criterio (sicuro): Stato = "Da fare", NON pubblicate e con `Data` piu' vecchia
di CLEANUP_DAYS giorni (default 3). Le pagine vengono ARCHIVIATE (cestino Notion,
recuperabili ~30 giorni), non distrutte. Articoli gia' scritti (Stato "Fatto") o
pubblicati non vengono mai toccati.

Variabili d'ambiente: NOTION_TOKEN, NOTION_DB_ID, CLEANUP_DAYS (default 3).
"""

import os
from datetime import date

import config
import kanri_engine as ke
import notion_sync


def main():
    nt, ndb = os.environ.get("NOTION_TOKEN"), os.environ.get("NOTION_DB_ID")
    if not (nt and ndb):
        raise SystemExit("NOTION_TOKEN/NOTION_DB_ID non impostate")
    days = int(os.environ.get("CLEANUP_DAYS", "3"))

    righe = notion_sync.righe_da_pulire(nt, ndb, days=days)
    print(
        f"Pulizia: {len(righe)} news 'Da fare' non pubblicate piu' vecchie di {days} giorni",
        flush=True,
    )

    archiviate = 0
    for r in righe:
        try:
            notion_sync.archivia(nt, r["page_id"])
            archiviate += 1
            print(f"  archiviata: [{r.get('data', '?')}] {r.get('title', '')[:80]}", flush=True)
        except Exception as e:
            print(f"  errore su {r['page_id']}: {repr(e)[:120]}", flush=True)

    print(f"Pulizia completata: {archiviate}/{len(righe)} archiviate", flush=True)


if __name__ == "__main__":
    import traceback

    try:
        main()
    except SystemExit:
        raise
    except Exception:
        ke.alert(
            f"⚠️ Pulizia {config.BRAND} FALLITA — {date.today().isoformat()}",
            "La pulizia automatica delle news scadute è fallita.\n\n" + traceback.format_exc(),
        )
        raise
