#!/usr/bin/env python3
"""
Podcast settimanale KANRI Tape.

Ogni lunedì mattina:
  1. legge da Notion gli articoli PUBBLICATI nell'ultima settimana
  2. fa scrivere a un LLM (Gemini -> OpenRouter, gratis) un copione parlato
  3. sintetizza l'audio con edge-tts (voci neurali gratuite, nessuna API key)
  4. carica l'mp3 su Internet Archive (hosting gratuito con API)
  5. salva i metadati della puntata su Notion (DB "Podcast"), così il
     frontend può costruire player e feed RSS
  6. invia un'email di notifica con il copione in allegato

Variabili d'ambiente:
  NOTION_TOKEN, NOTION_DB_ID      database articoli (sorgente)
  PODCAST_DB_ID                   database Notion delle puntate (opzionale)
  PODCAST_VOICE                   voce edge-tts (default it-IT-IsabellaNeural)
  PODCAST_DAYS                    finestra giorni (default 7)
  ARCHIVE_ACCESS_KEY/_SECRET_KEY  chiavi S3 di archive.org
  ARCHIVE_COLLECTION              collezione archive.org (default "opensource_audio")
  GEMINI_API_KEY / OPENROUTER_*   LLM per il copione
  RESEND_API_KEY / MAIL_*         email di notifica
"""

import json
import os
import re
import shutil
from datetime import date, timedelta
from pathlib import Path

import config
import kanri_engine as ke
import notion_sync
from kanri_engine import send_email

PODCAST_NOME = config.get("podcast.nome", f"{config.BRAND} Tape")
PODCAST_SLUG = config.get("podcast.slug", "kanri-tape")
VOCE_GOOGLE_DEFAULT = "it-IT-Chirp3-HD-Aoede"
VOCE_EDGE_DEFAULT = "it-IT-IsabellaNeural"
# Tetto caratteri per puntata: protegge la quota mensile di ElevenLabs free
# (10.000 caratteri/mese ≈ 4-5 puntate brevi).
MAX_CHARS_DEFAULT = 2400

SYSTEM = (Path(__file__).parent / "podcast_instructions.txt").read_text(encoding="utf-8")


def _stato_carica(percorso):
    """Stato di avanzamento della puntata di giornata (upload/Notion/fine)."""
    try:
        return json.loads(percorso.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _stato_salva(percorso, stato):
    percorso.write_text(json.dumps(stato, ensure_ascii=False), encoding="utf-8")


def taglia_a_caratteri(testo, max_chars):
    """Tronca il copione al limite, ma su un confine di frase (niente tagli a metà)."""
    if len(testo) <= max_chars:
        return testo
    tagliato = testo[:max_chars]
    m = list(re.finditer(r"[.!?](?:\s|$)", tagliato))
    if m:
        tagliato = tagliato[: m[-1].end()]
    return tagliato.strip()


# Marcatori del "pensare ad alta voce": alcuni modelli (es. nemotron) scrivono
# la catena di ragionamento DENTRO il contenuto invece di tenerla separata. Se
# finisce nel copione, la sintesi vocale legge il prompt: e' successo il 3 e il
# 17 agosto 2026. Vengono cercati solo in testa al testo.
_RAGIONAMENTO = re.compile(
    r"(?i)\b(we need to|we must|we should|we can|we have to|the user (?:wants|asks)"
    r"|let'?s (?:craft|write|aim|start|count|draft)|i should|word count"
    r"|must not invent|okay,|first,)"
)

# Parole funzionali italiane: servono a capire se il testo e' davvero in italiano
# (il ragionamento dei modelli e' in inglese).
_STOPWORD_IT = {
    "il", "lo", "la", "i", "gli", "le", "di", "del", "della", "dei", "delle", "che", "per",
    "con", "una", "un", "uno", "nel", "nella", "sono", "è", "e", "da", "si", "non", "questa",
    "questo", "settimana", "anche", "come", "più", "tra", "sua", "suo", "ha", "in", "al", "alla",
}  # fmt: skip


def _sembra_italiano(testo, soglia=0.12):
    """True se la quota di parole funzionali italiane e' plausibile."""
    parole = re.findall(r"[a-zàèéìòóùü']+", testo.lower())
    if len(parole) < 30:
        return False
    return sum(1 for p in parole if p in _STOPWORD_IT) / len(parole) >= soglia


def _valida_copione(testo):
    """(ok, motivo): il testo e' un copione pronto per la sintesi vocale?
    Ultimo cancello prima del TTS: quello che passa qui viene LETTO AD ALTA VOCE."""
    # prima il ragionamento: e' il difetto piu' specifico da diagnosticare
    if _RAGIONAMENTO.search(testo[:600]):
        return False, "contiene il ragionamento del modello, non il copione"
    parole = len(testo.split())
    if parole < 60:
        return False, f"troppo corto ({parole} parole)"
    if not _sembra_italiano(testo):
        return False, "non sembra italiano"
    return True, ""


def _dopo_marcatore_bozza(grezzo):
    """I modelli che ragionano in chiaro spesso chiudono con un marcatore tipo
    'Draft:' seguito dal copione vero: tiene solo cio' che viene dopo l'ultimo."""
    marcatori = list(
        re.finditer(
            r"(?i)\b(?:draft|bozza|copione(?:\s+finale)?|final(?:\s+script)?)\s*[:\n]", grezzo
        )
    )
    if not marcatori:
        return ""
    return grezzo[marcatori[-1].end() :].strip().strip("\"“”'").strip()


def _prepara_copione(grezzo):
    """Dal testo grezzo del modello al copione pronto. Se il modello ha 'pensato
    ad alta voce', prova a recuperare la sola bozza finale."""
    testo = _pulisci_copione(grezzo)
    if _valida_copione(testo)[0]:
        return testo
    estratto = _pulisci_copione(_dopo_marcatore_bozza(grezzo))
    return estratto if _valida_copione(estratto)[0] else testo


def genera_audio(copione, out_mp3):
    """Sintetizza l'audio. Priorità: ElevenLabs (qualità) → Google (se chiave) →
    Edge (sempre disponibile). Restituisce il nome del motore/voce usata."""
    if os.environ.get("ELEVENLABS_API_KEY"):
        residui = ke.elevenlabs_crediti_residui()
        if residui is not None:
            print(f"  (ElevenLabs: ~{residui} caratteri residui nel mese)", flush=True)
        if residui is None or residui >= len(copione):
            try:
                voce = os.environ.get("ELEVENLABS_VOICE_ID", "(default)")
                ke.tts_elevenlabs(copione, out_mp3)
                return f"ElevenLabs/{voce}"
            except Exception as e:
                print(f"  (ElevenLabs fallito, provo altri motori: {repr(e)[:220]})", flush=True)
        else:
            print("  (ElevenLabs: quota mensile insufficiente, uso fallback)", flush=True)
    if os.environ.get("GOOGLE_TTS_API_KEY"):
        voce = os.environ.get("GOOGLE_TTS_VOICE", VOCE_GOOGLE_DEFAULT)
        try:
            ke.tts_google(copione, out_mp3, voice=voce)
            return f"Google/{voce}"
        except Exception as e:
            print(f"  (Google TTS fallito, uso Edge: {repr(e)[:140]})", flush=True)
    voce = os.environ.get("PODCAST_VOICE", VOCE_EDGE_DEFAULT)
    ke.tts_edge(copione, out_mp3, voice=voce)
    return f"Edge/{voce}"


def settimana_label(oggi):
    """Etichetta leggibile della settimana, es. '9–15 giugno 2026'."""
    mesi = [
        "gennaio",
        "febbraio",
        "marzo",
        "aprile",
        "maggio",
        "giugno",
        "luglio",
        "agosto",
        "settembre",
        "ottobre",
        "novembre",
        "dicembre",
    ]
    inizio = oggi - timedelta(days=7)
    if inizio.month == oggi.month:
        return f"{inizio.day}–{oggi.day} {mesi[oggi.month - 1]} {oggi.year}"
    return f"{inizio.day} {mesi[inizio.month - 1]} – {oggi.day} {mesi[oggi.month - 1]} {oggi.year}"


def costruisci_prompt(articoli, settimana):
    blocchi = []
    for i, a in enumerate(articoli, 1):
        parti = [
            f"ARTICOLO {i}",
            f"Titolo: {a['title']}",
            f"Categoria: {a.get('categoria') or '—'}",
        ]
        if a.get("summary"):
            parti.append(f"Di cosa parla: {a['summary']}")
        # solo un estratto del corpo: basta per il taglio parlato, tiene corto il prompt
        corpo = (a.get("corpo") or "").strip()
        if corpo:
            parti.append(f"Estratto: {corpo[:600]}")
        blocchi.append("\n".join(parti))
    materiali = "\n\n———\n\n".join(blocchi)
    return (
        f"Settimana di riferimento: {settimana}.\n"
        f"Numero di articoli pubblicati: {len(articoli)}.\n\n"
        f"Ecco i materiali (usa SOLO queste informazioni):\n\n{materiali}\n\n"
        f"Scrivi il copione della puntata di {PODCAST_NOME} seguendo le istruzioni."
    )


def stima_durata(testo):
    """Durata stimata di lettura (≈155 parole/minuto) in formato mm:ss."""
    parole = len(testo.split())
    sec = round(parole / 155 * 60)
    return f"{sec // 60:02d}:{sec % 60:02d}"


def main():
    oggi = date.today()
    settimana = settimana_label(oggi)
    nt = os.environ.get("NOTION_TOKEN")
    ndb = os.environ.get("NOTION_DB_ID")
    days = int(os.environ.get("PODCAST_DAYS", "7"))

    if not (nt and ndb):
        raise SystemExit("NOTION_TOKEN/NOTION_DB_ID non impostate")

    # stato della giornata: rende il rilancio idempotente (non ripubblica, non
    # duplica la riga Notion) e quindi i ritenti sono gratis.
    stato_file = Path(f"{PODCAST_SLUG}-{oggi.isoformat()}.state.json")
    stato = _stato_carica(stato_file)
    if stato.get("done"):
        print(f"Puntata del {oggi.isoformat()} già pubblicata: niente da fare", flush=True)
        raise SystemExit(0)

    articoli = notion_sync.articoli_pubblicati(nt, ndb, days=days)
    print(f"Notion: {len(articoli)} articoli pubblicati negli ultimi {days} giorni", flush=True)
    if not articoli:
        print("nessun articolo pubblicato questa settimana: niente puntata", flush=True)
        raise SystemExit(0)

    # 1. copione — i file di giornata fanno da checkpoint: se un tentativo
    # precedente e' arrivato fin qui, si riusa il risultato invece di
    # riconsumare quota LLM/TTS (es. quando fallisce solo l'upload).
    txt = Path(f"{PODCAST_SLUG}-{oggi.isoformat()}.txt")
    mp3 = Path(f"{PODCAST_SLUG}-{oggi.isoformat()}.mp3")
    voce_mp3 = Path(f"{PODCAST_SLUG}-{oggi.isoformat()}.voce.mp3")
    copione = ""
    if txt.exists() and txt.stat().st_size > 0:
        salvato = txt.read_text(encoding="utf-8").strip()
        ok, motivo = _valida_copione(salvato)
        if ok:
            copione = salvato
            print(f"Copione: riuso il checkpoint del tentativo precedente ({txt})", flush=True)
        else:
            print(f"Copione: checkpoint scartato ({motivo}), lo rigenero", flush=True)
    if not copione:
        # thinking=False: i modelli Gemini 2.5 altrimenti consumano il budget di
        # output ragionando e troncano il copione.
        grezzo = ke.article_llm(
            SYSTEM,
            costruisci_prompt(articoli, settimana),
            max_tokens=2000,
            temperature=0.6,
            thinking=False,
            valida=lambda t: _valida_copione(_prepara_copione(t))[0],
        )
        copione = _prepara_copione(grezzo)
        ok, motivo = _valida_copione(copione)
        if not ok:
            raise RuntimeError(f"copione inutilizzabile: {motivo}")
        # tetto caratteri: protegge la quota mensile di ElevenLabs free
        max_chars = int(os.environ.get("PODCAST_MAX_CHARS", MAX_CHARS_DEFAULT))
        prima = len(copione)
        copione = taglia_a_caratteri(copione, max_chars)
        if len(copione) < prima:
            print(
                f"  (copione troncato da {prima} a {len(copione)} caratteri per la quota)",
                flush=True,
            )
        txt.write_text(copione, encoding="utf-8")
        # il copione e' nuovo: l'audio di un tentativo precedente e' obsoleto
        for vecchio in (voce_mp3, mp3):
            if vecchio.exists():
                vecchio.unlink()
                print(f"  (rimosso audio obsoleto: {vecchio})", flush=True)
    durata = stima_durata(copione)
    print(
        f"LLM: copione di {len(copione.split())} parole / {len(copione)} caratteri (~{durata})",
        flush=True,
    )

    # 2. audio (voce)
    if voce_mp3.exists() and voce_mp3.stat().st_size > 0:
        print(f"TTS: riuso la voce del tentativo precedente ({voce_mp3})", flush=True)
    else:
        voce = genera_audio(copione, str(voce_mp3))
        print(f"TTS: voce generata ({voce_mp3.stat().st_size // 1024} KB) con {voce}", flush=True)

    # 2b. mix con sottofondo musicale (intro pulita + ducking + fade out)
    # PODCAST_BG_MUSIC vuota (o assente) = usa la traccia del repo.
    bg = os.environ.get("PODCAST_BG_MUSIC") or str(
        Path(__file__).parent / "assets" / "kanri-bed.mp3"
    )
    if mp3.exists() and mp3.stat().st_size > 0:
        print(f"Mix: riuso l'audio del tentativo precedente ({mp3})", flush=True)
    elif shutil.which("ffmpeg") and os.path.exists(bg):
        ke.mix_audio(
            str(voce_mp3),
            bg,
            str(mp3),
            intro=float(os.environ.get("PODCAST_INTRO_SEC", "4")),
            volume=float(os.environ.get("PODCAST_MUSIC_VOLUME", "0.30")),
        )
        print(f"Mix: sottofondo applicato -> {mp3.stat().st_size // 1024} KB", flush=True)
    else:
        mp3 = voce_mp3  # niente ffmpeg/traccia: pubblica la sola voce
        print("  (ffmpeg o traccia assenti: nessun sottofondo, uso la sola voce)", flush=True)

    # 3. upload su Internet Archive
    titolo = f"{PODCAST_NOME} — {settimana}"
    identifier = f"{PODCAST_SLUG}-{oggi.isoformat()}"
    descrizione = (
        f"{PODCAST_NOME}, il punto settimanale di {config.BRAND}, "
        f"{config.DESCRIZIONE}. Gli articoli pubblicati nella settimana {settimana}."
    )
    audio_url = stato.get("audio_url", "")
    if audio_url:
        print(
            f"Internet Archive: riuso l'upload del tentativo precedente ({audio_url})", flush=True
        )
    elif os.environ.get("ARCHIVE_ACCESS_KEY"):
        meta = {
            "title": titolo,
            "mediatype": "audio",
            "collection": os.environ.get("ARCHIVE_COLLECTION", "opensource_audio"),
            "creator": config.BRAND,
            "subject": "design; arte; cultura visiva; podcast",
            "language": "ita",
            "date": oggi.isoformat(),
            "description": descrizione,
        }
        audio_url = ke.archive_upload(identifier, str(mp3), meta)
        stato["audio_url"] = audio_url
        _stato_salva(stato_file, stato)
        print(f"Internet Archive: {audio_url}", flush=True)
    else:
        print("  (ARCHIVE_ACCESS_KEY non impostata: salto l'upload)", flush=True)

    # 4. metadati su Notion (DB Podcast)
    pdb = os.environ.get("PODCAST_DB_ID")
    if stato.get("notion_ok"):
        print("Notion: riga già creata in un tentativo precedente", flush=True)
    elif pdb and audio_url:
        ep = {
            "titolo": titolo,
            "data": oggi.isoformat(),
            "descrizione": descrizione,
            "audio_url": audio_url,
            "durata": durata,
            "copione": copione,
            "articoli": [{"title": a["title"], "slug": a.get("slug", "")} for a in articoli],
        }
        notion_sync.crea_episodio(nt, pdb, ep)
        stato["notion_ok"] = True
        _stato_salva(stato_file, stato)
        print("Notion: puntata salvata nel database Podcast", flush=True)
    elif not pdb:
        print("  (PODCAST_DB_ID non impostata: salto il salvataggio su Notion)", flush=True)

    # 5. email di notifica con copione in allegato (il .txt e' gia' su disco)
    corpo_mail = (
        f"# {titolo}\n\nDurata stimata: {durata}\n"
        f"Articoli: {len(articoli)}\n"
        f"Audio: {audio_url or '(upload saltato)'}\n\n---\n\n{copione}"
    )
    send_email(f"🎙️ {PODCAST_NOME} — {settimana}", corpo_mail, str(txt))
    stato["done"] = True
    _stato_salva(stato_file, stato)


def _pulisci_copione(testo):
    """Toglie residui di markdown/regia che l'LLM a volte aggiunge."""
    testo = re.sub(r"(?m)^\s{0,3}#{1,6}\s*", "", testo)  # heading
    testo = re.sub(r"[*_`]+", "", testo)  # enfasi markdown
    testo = re.sub(r"(?m)^\s*[-*•]\s+", "", testo)  # punti elenco
    testo = re.sub(r"(?im)^\s*(intro|outro|sigla|nota di regia)\s*:?\s*$", "", testo)
    return re.sub(r"\n{3,}", "\n\n", testo).strip()


if __name__ == "__main__":
    import time
    import traceback

    for _tentativo in range(2):
        try:
            main()
            break
        except SystemExit:
            raise  # "nessun articolo" non è un errore
        except Exception:
            if _tentativo == 0:
                # 5 minuti: i fallimenti tipici (coda archive.org, rate limit)
                # non rientrano in 2. I checkpoint rendono il retry economico.
                print("Podcast fallito, riprovo tra 300s...", flush=True)
                time.sleep(300)
                continue
            if os.environ.get("PODCAST_QUIET") == "1":
                # ritenti automatici del pomeriggio: falliscono in silenzio,
                # l'avviso e' gia' partito col run principale
                raise
            ke.alert(
                f"⚠️ {PODCAST_NOME} FALLITO — {date.today().isoformat()}",
                "La puntata podcast settimanale non è stata generata dopo 2 tentativi.\n"
                "L'audio potrebbe essere già pronto sul server: i ritenti automatici "
                "del pomeriggio riprovano solo la pubblicazione.\n\n" + traceback.format_exc(),
            )
            raise
