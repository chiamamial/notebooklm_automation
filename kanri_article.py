#!/usr/bin/env python3
"""
Articolo KANRI (deep research multi-fonte):
- Tavily cerca le fonti che parlano del tema
- Firecrawl scarica il testo pulito di ognuna
- OpenRouter le FONDE in un articolo originale, formato KANRI

Funzione principale: genera_articolo(titolo, contesto) -> markdown
Usata dal controllore Notion (notion_watcher.py).
"""

import sys
from pathlib import Path

import kanri_engine as ke

SYSTEM = (
    "Sei un giornalista-redattore di KANRI, rivista di cultura visiva e sonora. "
    "Scrivi articoli originali in italiano sintetizzando PIÙ fonti, mai copiando."
)


def _titolo_da_md(md):
    for line in md.splitlines():
        s = line.strip()
        if s.startswith("# "):
            return s[2:].strip()[:140]
    for line in md.splitlines():
        s = line.strip()
        if len(s) > 15:
            return s[:140]
    return ""


def genera_articolo(titolo, contesto="", fonte_url="", n_fonti=5):
    fonti = []
    seed = titolo

    # 1. ANCORA: leggi la fonte originale (sicura al 100% sul tema)
    if fonte_url:
        md = ke.firecrawl_scrape(fonte_url)
        if md and len(md) > 400:
            t0 = _titolo_da_md(md) or titolo
            seed = t0
            fonti.append({"title": t0, "url": fonte_url, "text": md[:6000]})

    # 2. cerca ALTRE fonti RECENTI sullo stesso fatto (ultimi 7 giorni)
    query = " ".join(f"{seed} {contesto}".split())[:300]
    risultati = ke.tavily_search(query, max_results=n_fonti + 3, days=7)
    for r in risultati:
        if len(fonti) >= n_fonti + 1:
            break
        url = r.get("url", "")
        if not url or url.rstrip("/") == fonte_url.rstrip("/"):
            continue                                   # gia' inclusa (originale)
        if float(r.get("score", 1)) < 0.4:
            continue                                   # poco pertinente: scarta
        md = ke.firecrawl_scrape(url)
        text = md if (md and len(md) > 400) else r.get("content", "")
        if text:
            fonti.append({"title": r.get("title", ""), "url": url, "text": text[:6000]})

    if not fonti:
        for r in risultati[:n_fonti]:
            fonti.append({"title": r.get("title", ""), "url": r.get("url", ""),
                          "text": r.get("content", "")})

    # 3. sintesi
    formato = (Path(__file__).parent / "article_instructions.txt").read_text(encoding="utf-8")
    blocchi = "\n\n".join(
        f'### FONTE {i+1}: {f["title"]}\nURL: {f["url"]}\n{f["text"]}'
        for i, f in enumerate(fonti))
    user = (
        f"ARGOMENTO (la notizia da approfondire): {titolo}\n"
        f"{('CONTESTO: ' + contesto) if contesto else ''}\n\n"
        f"Qui sotto {len(fonti)} fonti (testo grezzo). DOVREBBERO riguardare tutte "
        f"la STESSA notizia. Se una fonte NON è pertinente all'argomento qui sopra, "
        f"IGNORALA del tutto.\n\n{blocchi}\n\n"
        f"--- ISTRUZIONI DI FORMATO (rispettale alla lettera) ---\n{formato}\n\n"
        f"Scrivi UN SOLO articolo originale in italiano che SINTETIZZA le fonti "
        f"PERTINENTI (non copiarle), con angolo editoriale KANRI. Cita i fatti e, "
        f"nella sezione NOTE FONTI, elenca SOLO le fonti realmente usate (titolo + link)."
    )
    out = ke.openrouter_chat(
        [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}],
        max_tokens=8000, temperature=0.6)
    return ke.pulisci(out)


if __name__ == "__main__":
    topic = " ".join(sys.argv[1:]).strip() or "Gustaf Westman x Nike ceramica scultorea"
    print(genera_articolo(topic))
