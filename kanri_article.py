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


def esegui_ricerca_seo(titolo, contesto=""):
    """
    Effettua una ricerca SEO preliminare per individuare parole chiave,
    domande frequenti e trend relativi all'argomento.
    """
    query_seo = f"'{titolo}' search queries questions keywords trends"
    print(f"  → Ricerca SEO su Tavily con query: {query_seo}", flush=True)
    try:
        risultati = ke.tavily_search(query_seo, max_results=5, days=30)
    except Exception as e:
        print(f"  ✗ Errore ricerca Tavily per SEO: {e}", flush=True)
        return ""

    if not risultati:
        return ""

    snippet_text = "\n\n".join([
        f"Titolo: {r.get('title', '')}\n"
        f"URL: {r.get('url', '')}\n"
        f"Contenuto: {r.get('content', '')}"
        for r in risultati
    ])

    system_seo = (
        "Sei un esperto SEO e analista di dati di ricerca. Il tuo compito è individuare le parole chiave "
        "più rilevanti, le intenzioni di ricerca degli utenti e le domande frequenti (People Also Ask) "
        "relative all'argomento fornito, basandoti sui risultati di ricerca web."
    )

    user_seo = (
        f"Argomento: {titolo}\n"
        f"Contesto: {contesto}\n\n"
        f"Risultati di ricerca web:\n{snippet_text}\n\n"
        "Analizza i dati sopra e restituisci un report SEO sintetico in italiano con:\n"
        "1. KEYWORDS: Un elenco di 5-8 parole chiave o frasi chiave (in ordine di rilevanza) da inserire naturalmente nell'articolo.\n"
        "2. INTENT: L'intenzione di ricerca principale dell'utente (es. informativa, transazionale, ispirazionale) e cosa si aspetta di trovare.\n"
        "3. DOMANDE FREQUENTI: 3-4 domande reali o dubbi che le persone si pongono su questo tema (utili come spunti per i paragrafi).\n"
        "4. SUGGERIMENTO METADATI: Suggerimento per l'ottimizzazione del Titolo SEO (max 60 car.) e Meta description (120-155 car.).\n"
        "\nRispondi in modo sintetico e strutturato in Markdown, senza preamboli."
    )

    print("  → Generazione report SEO con LLM...", flush=True)
    try:
        # Usiamo article_llm che sceglie Gemini o OpenRouter
        report_seo = ke.article_llm(system_seo, user_seo, max_tokens=1500, temperature=0.3)
        return report_seo
    except Exception as e:
        print(f"  ✗ Errore generazione LLM per SEO: {e}", flush=True)
        return ""


def genera_articolo(titolo, contesto="", fonte_url="", n_fonti=5):
    # Esegui ricerca SEO preliminare
    print(f"→ Avvio analisi SEO per: {titolo}", flush=True)
    seo_report = esegui_ricerca_seo(titolo, contesto)
    if seo_report:
        print("  ✓ Analisi SEO completata con successo.", flush=True)
    else:
        print("  ⚠ Analisi SEO non disponibile o fallita. Procedo senza.", flush=True)

    fonti = []
    seed = titolo
    cover = ""

    # 1. ANCORA: leggi la fonte originale (sicura al 100% sul tema) + copertina
    if fonte_url:
        md, cover = ke.firecrawl_scrape_meta(fonte_url)
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
    has_orig = bool(fonte_url and fonti and fonti[0]["url"] == fonte_url)
    blocchi = "\n\n".join(
        f'### FONTE {i+1}{" (ORIGINALE — da cui nasce la notizia)" if (i == 0 and has_orig) else ""}: '
        f'{f["title"]}\nURL: {f["url"]}\n{f["text"]}'
        for i, f in enumerate(fonti))
    nota_orig = (
        f"\nLa FONTE 1 è l'ORIGINALE. Valuta: se è un contenuto esclusivo di quella "
        f"testata (intervista, profilo d'autore, reportage, scoop), ATTRIBUISCILA nel "
        f"corpo. In tal caso il nome della testata DEVE essere un link markdown che "
        f"punta ESATTAMENTE a questo URL: {fonte_url}\n"
        f"Esempio: 'come racconta in un post per [Printmag]({fonte_url})'.\n"
        f"Se invece le altre fonti riportano lo stesso fatto in modo equivalente, è "
        f"notizia generale: niente attribuzione singola.\n"
    ) if has_orig else ""
    seo_instructions = ""
    if seo_report:
        seo_instructions = (
            f"--- DATI E LINEE GUIDA SEO ---\n"
            f"Integra le seguenti indicazioni SEO per ottimizzare l'articolo. "
            f"Usa le parole chiave target in modo fluido e rispondi ai quesiti/domande frequenti "
            f"delle persone all'interno delle sezioni dell'articolo. In fondo all'articolo, usa "
            f"queste informazioni per compilare al meglio la sezione '## SEO' (Titolo SEO, Meta description, "
            f"Slug, Parole chiave).\n\n"
            f"{seo_report}\n\n"
            f"-------------------------------\n\n"
        )

    user = (
        f"ARGOMENTO (la notizia da approfondire): {titolo}\n"
        f"{('CONTESTO: ' + contesto) if contesto else ''}\n\n"
        f"{seo_instructions}"
        f"Qui sotto {len(fonti)} fonti (testo grezzo). DOVREBBERO riguardare tutte "
        f"la STESSA notizia. Se una fonte NON è pertinente all'argomento qui sopra, "
        f"IGNORALA del tutto.\n\n{blocchi}\n{nota_orig}\n"
        f"--- ISTRUZIONI DI FORMATO (rispettale alla lettera) ---\n{formato}\n\n"
        f"Scrivi UN SOLO articolo originale in italiano che SINTETIZZA le fonti "
        f"PERTINENTI (non copiarle), con angolo editoriale KANRI. Cita i fatti e, "
        f"nella sezione NOTE FONTI, elenca SOLO le fonti realmente usate (titolo + link)."
    )
    out = ke.article_llm(SYSTEM, user, max_tokens=8000, temperature=0.6)
    return ke.pulisci(out), cover


if __name__ == "__main__":
    topic = " ".join(sys.argv[1:]).strip() or "Gustaf Westman x Nike ceramica scultorea"
    body, cover = genera_articolo(topic)
    print("COPERTINA:", cover, "\n")
    print(body)
