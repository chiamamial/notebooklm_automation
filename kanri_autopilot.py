#!/usr/bin/env python3
"""
Autopilot KANRI: il salvagente di fine giornata.

Se alle 21:00 il brief del mattino è rimasto INTATTO (nessuna riga spuntata,
nessun articolo scritto, niente pubblicato), sceglie la notizia con più
potenziale di lettura, la fa scrivere e la mette online. Se invece hai lavorato
al brief — anche una riga sola — non fa assolutamente nulla: l'ultima parola
resta tua.

Variabili d'ambiente:
  NOTION_TOKEN, NOTION_DB_ID   database delle news (obbligatorie)
  AUTOPILOT_DRY_RUN=1          sceglie e stampa, senza scrivere né pubblicare
  AUTOPILOT_DATE=YYYY-MM-DD    forza il giorno del brief (utile a mano)
  VERCEL_DEPLOY_HOOK           se impostata, fa ripartire il build del sito
  RESEND_API_KEY / MAIL_*      email di resoconto
"""

import os
import urllib.request
from datetime import date

import config
import kanri_engine as ke
import notion_sync
from kanri_article import genera_articolo
from kanri_engine import send_email

SYSTEM = (
    f"Sei il caporedattore di {config.BRAND}, {config.DESCRIZIONE}. "
    "Conosci il pubblico della rivista e sai riconoscere quale notizia, tra "
    "tante, verrà davvero letta e condivisa. Rispondi sempre e solo in italiano."
)


def righe_lavorate(righe):
    """Le news su cui c'e' stata una mano umana: spuntate per la scrittura, gia'
    lavorate (Stato diverso da 'Da fare') o gia' online.

    E' il cancello dell'autopilot: se questa lista non e' vuota il brief e' stato
    lavorato e non si pubblica nulla in automatico.
    """
    return [
        r
        for r in righe
        if r.get("scrivi") or r.get("pubblica") or (r.get("stato") or "Da fare") != "Da fare"
    ]


def classifica_in_lista(dati):
    """Riporta la risposta dell'LLM a una lista di dizionari.

    L'array chiesto nel prompt non arriva sempre: certi modelli rispondono con
    un solo oggetto (gia' la scelta migliore), altri annidano l'array dentro una
    chiave. Il 7 settembre 2026 una risposta perfettamente valida —
    {"idx": 0, "perche": ...} — e' stata scartata per questo e l'articolo della
    sera non e' uscito.
    """
    if isinstance(dati, dict):
        if "idx" in dati:
            return [dati]
        for valore in dati.values():
            if isinstance(valore, list) and any(isinstance(x, dict) for x in valore):
                return [x for x in valore if isinstance(x, dict)]
        return []
    if isinstance(dati, list):
        return [x for x in dati if isinstance(x, dict)]
    return []


def indice_voce(voce, quanti):
    """L'indice indicato dalla voce, se utilizzabile. Tollera l'intero scritto
    come stringa ("2"), che alcuni modelli restituiscono."""
    idx = voce.get("idx")
    if isinstance(idx, bool):  # True varrebbe 1: non e' una scelta
        return None
    if isinstance(idx, str) and idx.strip().isdigit():
        idx = int(idx)
    return idx if isinstance(idx, int) and 0 <= idx < quanti else None


def costruisci_prompt(candidati):
    righe = [
        f"[{i}] ({c.get('categoria') or '—'}) {c['title']} :: {c.get('summary', '')[:220]}"
        for i, c in enumerate(candidati)
    ]
    return f"""Ecco le news selezionate stamattina per {config.BRAND} (indice tra parentesi quadre):

{chr(10).join(righe)}

Nessuna di queste è stata ancora lavorata. Devi sceglierne UNA da trasformare
subito in articolo: quella con il maggior potenziale di lettura e condivisione
per il pubblico di {config.BRAND}, {config.DESCRIZIONE}.

Criteri, in ordine di importanza:
1. FORZA DEL TEMA: un fatto vero e riconoscibile (un nome noto, un'opera, una
   mostra, un oggetto sorprendente), non un annuncio generico o di servizio.
2. POTENZIALE VISIVO: se ne può parlare per immagini forti.
3. CURIOSITÀ: fa venire voglia di aprire il pezzo senza essere acchiappaclick.
4. DURATA: interessa anche fra una settimana, non solo oggi.

Penalizza: comunicati stampa, pubblicità mascherata, notizie di puro servizio,
temi già visti mille volte, argomenti troppo di nicchia per essere condivisi.

Ordina TUTTE le news dalla più promettente alla meno promettente. Per ognuna:
- "idx": l'indice della news nell'elenco
- "perche": una frase sul perché funzionerebbe (o no) con i lettori

Rispondi SOLO con un array JSON, niente altro."""


def scegli(candidati, quanti=1, tentativi=3):
    """(scelte, classifica): le `quanti` news più promettenti, in ordine.

    `scelte` è una lista di (indice, voce) presa dalla classifica dell'LLM, che
    il prompt chiede ordinata dalla migliore alla peggiore. Se il modello ne
    indica meno di `quanti`, se ne pubblicano meno: "massimo 3", non "sempre 3".

    A volte la risposta non contiene indici utilizzabili: si riprova. Se proprio
    non arriva nulla di valido si solleva l'errore, così l'autopilot NON
    pubblica a caso.
    """
    ultimo = ""
    for tentativo in range(tentativi):
        classifica = classifica_in_lista(
            ke.llm_json(
                [
                    {"role": "system", "content": SYSTEM},
                    {"role": "user", "content": costruisci_prompt(candidati)},
                ],
                max_tokens=2000,
                temperature=0.3,
            )
        )
        scelte, visti = [], set()
        for voce in classifica:
            idx = indice_voce(voce, len(candidati))
            if idx is None or idx in visti:  # l'LLM a volte ripete un indice
                continue
            visti.add(idx)
            scelte.append((idx, voce))
            if len(scelte) >= quanti:
                break
        if scelte:
            return scelte, classifica
        ultimo = str(classifica)[:200]
        print(f"  (risposta senza indice valido, ritento {tentativo + 1}/{tentativi})", flush=True)
    raise RuntimeError(f"l'LLM non ha indicato una news valida: {ultimo}")


def scrivi_e_pubblica(nt, riga, giorno):
    """Scrive l'articolo nella pagina Notion e lo manda online.
    Se la scrittura fallisce la riga torna 'Da fare', lavorabile domani."""
    notion_sync.set_status(nt, riga["page_id"], "In corso")
    try:
        body, cover, slug = genera_articolo(
            riga["title"],
            riga.get("summary", ""),
            riga.get("fonte_url", ""),
            categoria=riga.get("categoria", ""),
            exclude_id=riga["page_id"],
        )
        notion_sync.append_markdown(nt, riga["page_id"], body)
        if cover:
            notion_sync.set_cover(nt, riga["page_id"], cover)
        if slug:
            notion_sync.set_slug(nt, riga["page_id"], slug)
        notion_sync.set_status(nt, riga["page_id"], "Fatto")
    except Exception:
        notion_sync.set_status(nt, riga["page_id"], "Da fare")
        raise
    notion_sync.pubblica(nt, riga["page_id"], giorno)
    return body, slug


def _risveglia_sito():
    """Fa ripartire il build del sito, se è configurato un deploy hook."""
    hook = os.environ.get("VERCEL_DEPLOY_HOOK")
    if not hook:
        print("  (VERCEL_DEPLOY_HOOK non impostata: il sito si aggiornerà al prossimo build)")
        return
    try:
        req = urllib.request.Request(hook, data=b"{}", method="POST")
        req.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(req, timeout=30):
            print("  (build del sito avviato)", flush=True)
    except Exception as e:
        print(f"  (deploy hook fallito: {repr(e)[:140]})", flush=True)


def main():
    nt = os.environ.get("NOTION_TOKEN")
    ndb = os.environ.get("NOTION_DB_ID")
    if not (nt and ndb):
        raise SystemExit("NOTION_TOKEN/NOTION_DB_ID non impostate")
    prova = os.environ.get("AUTOPILOT_DRY_RUN") == "1"
    giorno = os.environ.get("AUTOPILOT_DATE") or date.today().isoformat()

    righe = notion_sync.righe_del_giorno(nt, ndb, giorno)
    print(f"Brief del {giorno}: {len(righe)} news", flush=True)
    if not righe:
        print("Nessun brief oggi: niente da fare", flush=True)
        raise SystemExit(0)

    # "Nessuna azione" = nessuna riga spuntata, nessuna lavorata, niente online.
    lavorate = righe_lavorate(righe)
    if lavorate:
        print(f"Hai già lavorato al brief ({len(lavorate)} news toccate): l'autopilot si ferma.")
        for r in lavorate:
            print(f"  - [{r['stato']}] {r['title'][:70]}", flush=True)
        raise SystemExit(0)

    quanti = int(os.environ.get("AUTOPILOT_MAX", str(config.get("autopilot.max_articoli", 3))))
    print(f"Brief intatto: scelgo fino a {quanti} news con più potenziale", flush=True)
    scelte, classifica = scegli(righe, quanti=quanti)
    print(f"Scelte {len(scelte)} news su {len(righe)}:", flush=True)
    for pos, (idx, voce) in enumerate(scelte, 1):
        print(f"  {pos}. {righe[idx]['title'][:70]}", flush=True)
        print(f"     {str(voce.get('perche', ''))[:150]}", flush=True)

    if prova:
        print("\n(AUTOPILOT_DRY_RUN=1: mi fermo qui, non scrivo e non pubblico)", flush=True)
        vincitori = {i for i, _ in scelte}
        print("\nClassifica completa:", flush=True)
        for pos, voce in enumerate(classifica, 1):
            i = indice_voce(voce, len(righe))
            if i is not None:
                segno = "→" if i in vincitori else " "
                print(f"  {segno} {pos}. {righe[i]['title'][:70]}", flush=True)
        raise SystemExit(0)

    # Ogni articolo va per conto suo: se il secondo fallisce, il primo resta
    # online e il terzo viene comunque tentato.
    pubblicati, falliti = [], []
    for pos, (idx, voce) in enumerate(scelte, 1):
        riga = righe[idx]
        print(f"\n[{pos}/{len(scelte)}] {riga['title'][:70]}", flush=True)
        try:
            body, slug = scrivi_e_pubblica(nt, riga, giorno)
            pubblicati.append(
                {
                    "titolo": riga["title"],
                    "categoria": riga.get("categoria") or "—",
                    "fonte": riga.get("fonte", ""),
                    "perche": str(voce.get("perche", "")),
                    "slug": slug or "—",
                    "body": body,
                }
            )
            print(f"  pubblicato, slug: {slug or '—'}", flush=True)
        except Exception as e:
            falliti.append((riga["title"], repr(e)[:200]))
            print(f"  FALLITO: {repr(e)[:200]}", flush=True)

    if not pubblicati:
        raise RuntimeError(
            "nessun articolo pubblicato. Errori:\n" + "\n".join(f"- {t}: {e}" for t, e in falliti)
        )
    _risveglia_sito()

    vincitori = {i for i, _ in scelte}
    scartate = (
        "\n".join(
            f"- {righe[i]['title']}: {str(v.get('perche', ''))[:160]}"
            for i, v in ((indice_voce(v, len(righe)), v) for v in classifica)
            if i is not None and i not in vincitori
        )
        or "(il modello ha indicato solo le vincitrici)"
    )
    elenco = "\n".join(
        f"{n}. **{a['titolo']}**\n"
        f"   - Perché: {a['perche']}\n"
        f"   - Categoria: {a['categoria']} · Slug: {a['slug']}\n"
        f"   - Fonte: {a['fonte']}"
        for n, a in enumerate(pubblicati, 1)
    )
    problemi = (
        "\n\n## Non riusciti\n\n" + "\n".join(f"- {t}: {e}" for t, e in falliti) if falliti else ""
    )
    testi = "\n\n---\n\n".join(f"# {a['titolo']}\n\n{a['body']}" for a in pubblicati)
    plurale = "articoli" if len(pubblicati) > 1 else "articolo"
    send_email(
        f"🤖 {config.BRAND} in automatico — {len(pubblicati)} {plurale}",
        f"Il brief del {giorno} non è stato lavorato, così l'autopilot ha scelto, "
        f"scritto e pubblicato {len(pubblicati)} {plurale} su {len(righe)} news.\n\n"
        f"{elenco}{problemi}\n\n"
        f"Se qualcuno non ti convince, in Notion puoi togliere la spunta `Pubblica`.\n\n"
        f"---\n\n## Le altre, e perché sono state scartate\n\n{scartate}\n\n"
        f"---\n\n{testi}",
    )


if __name__ == "__main__":
    import traceback

    try:
        main()
    except SystemExit:
        raise
    except Exception:
        ke.alert(
            f"⚠️ Autopilot {config.BRAND} FALLITO — {date.today().isoformat()}",
            "L'articolo automatico di fine giornata non è stato pubblicato.\n\n"
            + traceback.format_exc(),
        )
        raise
