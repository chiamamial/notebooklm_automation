#!/usr/bin/env python3
"""
Brief KANRI: raccoglie le news dai feed RSS, le fa selezionare e classificare a
un LLM (OpenRouter), scrive le righe nel database Notion e invia l'email.

Sostituisce la "ricerca delle 07:00" basata su NotebookLM.
"""

import os
import random
from datetime import date
from pathlib import Path

import config
import kanri_engine as ke
import notion_sync
from kanri_engine import send_email

CATEGORIE = config.CATEGORIE_TESTO

SYSTEM = (
    f"Sei il caporedattore di {config.BRAND}, {config.DESCRIZIONE}. "
    "Selezioni solo notizie forti, fresche e visivamente raccontabili, "
    "coerenti con le verticali editoriali. Rispondi sempre e solo in italiano."
)

# Domini per le passate a quota garantita: ogni passata pesca SOLO dai suoi feed
# (config), così arte e musica non devono competere con design e grafica.
ARTE_DOMINI = set(config.get("brief.arte_domini", []))
CATEGORIA_ARTE = config.get("brief.categoria_arte", "Arte e Fotografia")
MUSICA_DOMINI = set(config.get("brief.musica_domini", []))
CATEGORIA_MUSICA = config.get("brief.categoria_musica", "Musica Elettronica")
_PRIORITA = config.get("priorita", [])
_ESCLUSE = [
    f"'{c}'" for c, d in ((CATEGORIA_ARTE, ARTE_DOMINI), (CATEGORIA_MUSICA, MUSICA_DOMINI)) if d
]

FOCUS_GENERALE = (
    f"Seleziona le notizie PIÙ interessanti per {config.BRAND} (scarta gossip, "
    "tech generalista, pubblicità, doppioni).\n"
    + (
        f"PRIORITÀ EDITORIALE: soprattutto {' e '.join(_PRIORITA)}; il resto le altre categorie.\n"
        if _PRIORITA
        else ""
    )
    + (
        f"NON selezionare notizie di {' o '.join(_ESCLUSE)}: sono gestite in passate separate."
        if _ESCLUSE
        else ""
    )
)

FOCUS_ARTE = (
    "Queste news vengono da testate di arte contemporanea. Seleziona SOLO le più "
    "forti e attinenti all'ARTE: artisti e loro lavori (pittura, scultura, "
    "disegno, installazione), mostre e retrospettive, biennali e fiere (Art "
    "Basel, Frieze, TEFAF), musei e collezioni, mercato dell'arte e aste, "
    "riscoperte e archivi d'artista. Scarta ciò che è puro design di prodotto o "
    "grafica commerciale, il gossip sui collezionisti e le note di mercato senza "
    f"un'opera al centro. Per 'categoria' usa sempre '{CATEGORIA_ARTE}'."
)

FOCUS_MUSICA = (
    "Queste news vengono da testate di musica elettronica e cultura sonora. "
    "Seleziona SOLO le più forti e attinenti a MUSICA ELETTRONICA / sound design "
    "/ club culture (techno, house, ambient, sperimentale; uscite, produzione, "
    "attrezzatura, scena, ritratti d'artista). Scarta ciò che non è musica "
    f"elettronica. Per 'categoria' usa sempre '{CATEGORIA_MUSICA}'."
)


def costruisci_prompt(items, n, focus):
    righe = [
        f"[{i}] ({it['source']}) {it['title']} :: {it['summary'][:160]}"
        for i, it in enumerate(items)
    ]
    return f"""Ecco le news dai feed (indice tra parentesi quadre):

{chr(10).join(righe)}

Le categorie di {config.BRAND}:
{CATEGORIE}

{focus}

DIVERSIFICA LE FONTI: non scegliere più di 2 notizie dalla stessa testata
(guarda la fonte tra parentesi tonde). A parità di interesse, preferisci una
fonte non ancora usata.

Per ognuna restituisci un oggetto JSON:
- "idx": l'indice della news nell'elenco
- "titolo": un titolo in stile magazine, in italiano (riscritto, accattivante)
- "categoria": ESATTAMENTE una tra: {", ".join(config.CATEGORIE_NOMI)}
- "di_cosa_parla": 3-4 frasi in italiano che spiegano bene la notizia
- "perche": una frase sul perché interessa al lettore di {config.BRAND}

Rispondi SOLO con un array JSON di {n} oggetti, niente altro."""


def seleziona(items, n, focus):
    """Una passata di scrematura LLM: sceglie fino a `n` news da `items`."""
    if not items or n <= 0:
        return []
    n = min(n, len(items))
    scelte = ke.llm_json(
        [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": costruisci_prompt(items, n, focus)},
        ],
        max_tokens=8000,
        temperature=0.5,
    )
    return scelte or []


def aggiungi(scelte, fonte_items, notizie, righe_md, visti):
    """Trasforma le scelte LLM in righe Notion + blocchi email (dedup per URL)."""
    for s in scelte:
        if not isinstance(s, dict):
            continue
        idx = s.get("idx")
        if not (isinstance(idx, int) and 0 <= idx < len(fonte_items)):
            continue
        src = fonte_items[idx]
        url = src.get("url", "").rstrip("/")
        if url and url in visti:
            continue
        visti.add(url)
        cat = notion_sync.normalizza_categoria(s.get("categoria", ""))
        fonte = f"{src.get('source', '')} ({src.get('url', '')})".strip()
        notizie.append(
            {
                "title": s.get("titolo", src.get("title", ""))[:200],
                "summary": s.get("di_cosa_parla", "")[:1900],
                "categoria": cat,
                "fonte": fonte[:1900],
            }
        )
        righe_md += [
            f"## {s.get('titolo', '')}",
            f"- **Di cosa parla:** {s.get('di_cosa_parla', '')}",
            f"- **Perché pubblicarlo:** {s.get('perche', '')}",
            f"- **Categoria:** {cat or '—'}",
            f"- **Fonte:** {fonte}",
            "",
        ]


def main():
    today = date.today().isoformat()
    feeds = Path(__file__).parent / "kanri_feeds.txt"
    totale = int(os.environ.get("BRIEF_TOTALE", str(config.get("brief.totale", 7))))
    arte_target = int(os.environ.get("BRIEF_ARTE", str(config.get("brief.arte", 3))))
    musica_target = int(os.environ.get("BRIEF_MUSICA", str(config.get("brief.musica", 2))))

    # cap basso per feed (no monopolio di chi pubblica tantissimo, es. Dezeen)
    # e finestra ampia (i feed lenti, es. Giappone, fanno comunque in tempo).
    items = ke.fetch_rss_items(
        str(feeds),
        max_age_days=config.get("brief.max_age_days", 7),
        per_feed=config.get("brief.per_feed", 4),
    )
    print(f"RSS: {len(items)} news raccolte", flush=True)

    # anti-ripetizione: scarta le news gia' coperte negli ultimi 7 giorni
    nt, ndb = os.environ.get("NOTION_TOKEN"), os.environ.get("NOTION_DB_ID")
    if nt and ndb:
        coperti = notion_sync.urls_coperti(nt, ndb, days=7)
        items = [it for it in items if it["url"].rstrip("/") not in coperti]
        print(
            f"  dopo anti-ripetizione: {len(items)} news nuove ({len(coperti)} gia' coperte)",
            flush=True,
        )
    if not items:
        raise SystemExit("nessuna news nuova dai feed")

    # mescola: l'ordine dei feed non deve influenzare la scelta dell'LLM
    random.shuffle(items)

    # split del pool: arte / musica elettronica / tutto il resto
    riservati = ARTE_DOMINI | MUSICA_DOMINI
    arte = [it for it in items if it.get("source") in ARTE_DOMINI]
    musica = [it for it in items if it.get("source") in MUSICA_DOMINI]
    altri = [it for it in items if it.get("source") not in riservati]
    print(
        f"  pool: {len(arte)} arte / {len(musica)} musica elettronica / {len(altri)} altri",
        flush=True,
    )

    # PASSATA 1 — quota garantita di arte contemporanea (filone principale)
    n_arte = min(arte_target, len(arte))
    scelte_arte = seleziona(arte, n_arte, FOCUS_ARTE)
    print(f"LLM arte: {len(scelte_arte)} news", flush=True)

    # PASSATA 2 — quota garantita di musica elettronica
    n_musica = min(musica_target, len(musica))
    scelte_musica = seleziona(musica, n_musica, FOCUS_MUSICA)
    print(f"LLM musica: {len(scelte_musica)} news", flush=True)

    # PASSATA 3 — il resto (design/grafica/storia), per arrivare a `totale`
    scelte_altri = seleziona(altri, totale - n_arte - n_musica, FOCUS_GENERALE)
    print(f"LLM generale: {len(scelte_altri)} news", flush=True)

    # costruisci gli item per Notion + il corpo email
    notizie, righe_md, visti = [], [f"# Brief {config.BRAND} — " + today, ""], set()
    aggiungi(scelte_arte, arte, notizie, righe_md, visti)
    aggiungi(scelte_musica, musica, notizie, righe_md, visti)
    aggiungi(scelte_altri, altri, notizie, righe_md, visti)

    # scrivi su Notion
    if nt and ndb:
        n = notion_sync.add_news_rows(nt, ndb, notizie, today)
        print(f"Notion: {n} news aggiunte", flush=True)

    # email
    body = "\n".join(righe_md)
    send_email(
        f"🗞️ Brief {config.BRAND} {today} — {len(notizie)} news", body, _scrivi_file(today, body)
    )


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
            ke.alert(
                f"⚠️ Brief {config.BRAND} FALLITO — {_date.today().isoformat()}",
                "Il brief di oggi non è stato generato dopo 2 tentativi.\n\n"
                + traceback.format_exc(),
            )
            raise
