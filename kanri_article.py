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


def genera_articolo(titolo, contesto="", n_fonti=5):
    # 1. trova le fonti (query corta: Tavily limita a ~400 caratteri)
    query = " ".join(f"{titolo} {contesto}".split())[:350]
    risultati = ke.tavily_search(query, max_results=n_fonti + 2)

    # 2. scarica il testo pulito di ognuna
    fonti = []
    for r in risultati:
        if len(fonti) >= n_fonti:
            break
        md = ke.firecrawl_scrape(r.get("url", ""))
        if md and len(md) > 400:
            fonti.append({"title": r.get("title", ""), "url": r.get("url", ""),
                          "text": md[:6000]})
    if not fonti:
        # fallback: usa gli snippet di Tavily
        for r in risultati[:n_fonti]:
            fonti.append({"title": r.get("title", ""), "url": r.get("url", ""),
                          "text": r.get("content", "")})

    # 3. sintesi
    formato = (Path(__file__).parent / "article_instructions.txt").read_text(encoding="utf-8")
    blocchi = "\n\n".join(
        f'### FONTE {i+1}: {f["title"]}\nURL: {f["url"]}\n{f["text"]}'
        for i, f in enumerate(fonti))
    user = (
        f"ARGOMENTO: {titolo}\n"
        f"{('CONTESTO: ' + contesto) if contesto else ''}\n\n"
        f"Hai a disposizione queste {len(fonti)} fonti (testo grezzo):\n\n{blocchi}\n\n"
        f"--- ISTRUZIONI DI FORMATO (rispettale alla lettera) ---\n{formato}\n\n"
        f"Scrivi UN SOLO articolo originale in italiano che SINTETIZZA tutte le "
        f"fonti (non copiarle), con angolo editoriale KANRI. Cita i fatti e, "
        f"nella sezione NOTE FONTI, elenca le fonti con titolo e link reali."
    )
    out = ke.openrouter_chat(
        [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}],
        max_tokens=8000, temperature=0.6)
    return ke.pulisci(out)


if __name__ == "__main__":
    topic = " ".join(sys.argv[1:]).strip() or "Gustaf Westman x Nike ceramica scultorea"
    print(genera_articolo(topic))
