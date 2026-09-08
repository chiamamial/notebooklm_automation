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


def scegli(candidati, tentativi=3):
    """(indice, classifica) della news più promettente, scelta dall'LLM.

    A volte il modello risponde con un JSON valido ma senza un indice
    utilizzabile: si riprova invece di rinunciare alla serata. Se proprio non
    arriva una scelta valida si solleva l'errore, così l'autopilot NON pubblica
    nulla a caso.
    """
    ultimo = ""
    for tentativo in range(tentativi):
        classifica = ke.llm_json(
            [
                {"role": "system", "content": SYSTEM},
                {"role": "user", "content": costruisci_prompt(candidati)},
            ],
            max_tokens=2000,
            temperature=0.3,
        )
        classifica = classifica_in_lista(classifica)
        for voce in classifica:
            idx = indice_voce(voce, len(candidati))
            if idx is not None:
                return idx, classifica
        ultimo = str(classifica)[:200]
        print(f"  (risposta senza indice valido, ritento {tentativo + 1}/{tentativi})", flush=True)
    raise RuntimeError(f"l'LLM non ha indicato una news valida: {ultimo}")


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

    print("Brief intatto: scelgo la news con più potenziale di lettura", flush=True)
    idx, classifica = scegli(righe)
    scelta = righe[idx]
    perche = ""
    for voce in classifica:
        if indice_voce(voce, len(righe)) == idx:
            perche = str(voce.get("perche", ""))
            break
    print(f"Scelta: {scelta['title']}", flush=True)
    print(f"  perché: {perche}", flush=True)

    if prova:
        print("\n(AUTOPILOT_DRY_RUN=1: mi fermo qui, non scrivo e non pubblico)", flush=True)
        print("\nClassifica completa:", flush=True)
        for pos, voce in enumerate(classifica, 1):
            i = indice_voce(voce, len(righe))
            if i is not None:
                print(f"  {pos}. {righe[i]['title'][:70]}", flush=True)
                print(f"     {str(voce.get('perche', ''))[:150]}", flush=True)
        raise SystemExit(0)

    notion_sync.set_status(nt, scelta["page_id"], "In corso")
    try:
        body, cover, slug = genera_articolo(
            scelta["title"],
            scelta.get("summary", ""),
            scelta.get("fonte_url", ""),
            categoria=scelta.get("categoria", ""),
            exclude_id=scelta["page_id"],
        )
        notion_sync.append_markdown(nt, scelta["page_id"], body)
        if cover:
            notion_sync.set_cover(nt, scelta["page_id"], cover)
        if slug:
            notion_sync.set_slug(nt, scelta["page_id"], slug)
        notion_sync.set_status(nt, scelta["page_id"], "Fatto")
        print("Articolo scritto nella pagina Notion", flush=True)
    except Exception:
        # niente articolo a metà: la riga torna lavorabile domani
        notion_sync.set_status(nt, scelta["page_id"], "Da fare")
        raise

    notion_sync.pubblica(nt, scelta["page_id"], giorno)
    print(f"Pubblicato ({giorno}), slug: {slug or '—'}", flush=True)
    _risveglia_sito()

    altre = [(indice_voce(v, len(righe)), v) for v in classifica]
    scartate = (
        "\n".join(
            f"- {righe[i]['title']}: {str(v.get('perche', ''))[:160]}"
            for i, v in altre
            if i is not None and i != idx
        )
        or "(il modello ha indicato solo la vincitrice)"
    )
    send_email(
        f"🤖 {config.BRAND} in automatico — {scelta['title'][:70]}",
        f"# {scelta['title']}\n\n"
        f"Il brief del {giorno} non è stato lavorato, così l'autopilot ha scelto, "
        f"scritto e pubblicato questa news.\n\n"
        f"**Perché questa:** {perche}\n\n"
        f"**Categoria:** {scelta.get('categoria') or '—'}\n"
        f"**Slug:** {slug or '—'}\n"
        f"**Fonte:** {scelta.get('fonte', '')}\n\n"
        f"Se non ti convince, in Notion puoi togliere la spunta `Pubblica`.\n\n"
        f"---\n\n## Le altre, e perché sono state scartate\n\n{scartate}\n\n"
        f"---\n\n{body}",
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
