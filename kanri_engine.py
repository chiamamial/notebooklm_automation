#!/usr/bin/env python3
"""
Motore KANRI: strumenti condivisi.
- openrouter_chat : scrittura/sintesi con un LLM via OpenRouter
- tavily_search   : ricerca web (trova le fonti su un tema)
- firecrawl_scrape: estrae il testo pulito di una pagina
- fetch_rss_items : raccoglie le news dai feed RSS nativi
- extract_json    : estrae JSON dall'output di un LLM (anche se "ragiona")

Variabili d'ambiente: OPENROUTER_API_KEY, OPENROUTER_MODEL,
TAVILY_API_KEY, FIRECRAWL_API_KEY
"""

import os
import re
import json
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126 Safari/537.36")


def _post(url, payload, headers, timeout=120):
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode(),
        headers={**headers, "Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


# ---------- OpenRouter ----------

# Modelli free di riserva (provati in ordine se quello primario fallisce)
FALLBACK_MODELS = [
    "openai/gpt-oss-120b:free",
    "z-ai/glm-4.5-air:free",
    "qwen/qwen3-next-80b-a3b-instruct:free",
    "meta-llama/llama-3.3-70b-instruct:free",
    "nvidia/nemotron-3-super-120b-a12b:free",
]


def openrouter_chat(messages, max_tokens=4000, temperature=0.6, retries=1, model=None):
    key = os.environ["OPENROUTER_API_KEY"]
    model = model or os.environ.get("OPENROUTER_MODEL", FALLBACK_MODELS[0])
    payload = {"model": model, "messages": messages,
               "max_tokens": max_tokens, "temperature": temperature}
    headers = {"Authorization": f"Bearer {key}", "X-Title": "KANRI"}
    last = ""
    for attempt in range(retries + 1):
        try:
            d = _post("https://openrouter.ai/api/v1/chat/completions", payload, headers, 180)
            txt = d.get("choices", [{}])[0].get("message", {}).get("content", "")
            if txt and txt.strip():
                return txt
            last = "risposta vuota"
        except urllib.error.HTTPError as e:
            last = f"{e.code}: {e.read().decode()[:160]}"
        except Exception as e:
            last = repr(e)[:160]
        if attempt < retries:
            time.sleep(15)
    raise RuntimeError(f"OpenRouter ({model}) fallito: {last}")


def alert(subject, text):
    """Manda un avviso via email (Resend). Usato quando qualcosa fallisce."""
    key = os.environ.get("RESEND_API_KEY")
    to = os.environ.get("MAIL_TO")
    if not key or not to:
        return
    sender = os.environ.get("MAIL_FROM", "onboarding@resend.dev")
    payload = {"from": sender, "to": [to], "subject": subject,
               "html": f"<pre style='font-family:sans-serif;white-space:pre-wrap'>{text}</pre>"}
    req = urllib.request.Request(
        "https://api.resend.com/emails", data=json.dumps(payload).encode(),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json",
                 "User-Agent": "kanri/1.0"}, method="POST")
    try:
        urllib.request.urlopen(req, timeout=20)
        print("  (avviso email inviato)", flush=True)
    except Exception:
        pass


def gemini_chat(system, user, max_tokens=8000, temperature=0.6, model=None, thinking=True):
    """Genera testo con l'API Gemini (Google AI Studio).
    Con thinking=False disabilita il ragionamento (i modelli 2.5 lo attivano di
    default e consumano il budget di output, troncando la risposta)."""
    key = os.environ["GEMINI_API_KEY"]
    model = model or os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
    url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
           f"{model}:generateContent?key={key}")
    gen_config = {"maxOutputTokens": max_tokens, "temperature": temperature}
    if not thinking:
        gen_config["thinkingConfig"] = {"thinkingBudget": 0}
    payload = {
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": user}]}],
        "generationConfig": gen_config,
    }
    d = _post(url, payload, {}, 180)
    cands = d.get("candidates", [])
    if not cands:
        raise RuntimeError(f"Gemini: nessuna risposta ({str(d)[:200]})")
    parts = cands[0].get("content", {}).get("parts", [])
    return "".join(p.get("text", "") for p in parts)


def article_llm(system, user, max_tokens=8000, temperature=0.6, thinking=True):
    """Scrive l'articolo: usa Gemini se la chiave c'e', altrimenti OpenRouter."""
    if os.environ.get("GEMINI_API_KEY"):
        try:
            txt = gemini_chat(system, user, max_tokens, temperature, thinking=thinking)
            if txt and txt.strip():
                return txt
        except Exception as e:
            print(f"  (Gemini fallito, uso OpenRouter: {repr(e)[:120]})", flush=True)
    return openrouter_chat(
        [{"role": "system", "content": system}, {"role": "user", "content": user}],
        max_tokens, temperature)


def llm_json(messages, max_tokens=8000, temperature=0.4):
    """Ottiene un JSON dall'LLM provando piu' modelli free finche' uno funziona."""
    primary = os.environ.get("OPENROUTER_MODEL")
    ordine = ([primary] if primary else []) + [m for m in FALLBACK_MODELS if m != primary]
    last = ""
    for model in ordine:
        try:
            out = openrouter_chat(messages, max_tokens, temperature, retries=1, model=model)
            data = extract_json(out)
            if data:
                print(f"  (modello usato: {model})", flush=True)
                return data
            last = f"{model}: JSON vuoto"
        except Exception as e:
            last = f"{model}: {repr(e)[:100]}"
            print(f"  (scarto {model}: {last})", flush=True)
    raise RuntimeError(f"tutti i modelli falliti -> {last}")


def pulisci(md):
    """Forza il formato KANRI sull'output LLM (toglie titolo, denumera sezioni,
    pulisce escape e righe-artefatto)."""
    md = md.replace("\\*", "*").replace("\\_", "_")
    # togli marcatori di citazione: [1] 【1】 [1,2] [1-3]  e  (1)/(12) ma NON gli anni (2026)
    md = re.sub(r"[【\[]\s*\d+(?:\s*[,–-]\s*\d+)*\s*[】\]]", "", md)
    md = re.sub(r"\(\s*\d{1,2}\s*\)", "", md)
    md = re.sub(r"[¹²³⁰-⁹]+", "", md)  # apici ¹²³
    md = re.sub(r"[ \t]+([.,;:!?])", r"\1", md)  # spazi prima della punteggiatura
    md = re.sub(r"(?<=\S) {2,}(?=\S)", " ", md)  # doppi spazi rimasti dopo le rimozioni
    SEZIONI = {"seo": "## SEO", "social": "## SOCIAL",
               "immagini": "## IMMAGINI", "note fonti": "## NOTE FONTI"}
    out, titolo_rimosso = [], False
    for ln in md.splitlines():
        st = ln.strip()
        if not titolo_rimosso and st.startswith("# ") and not st.startswith("## "):
            titolo_rimosso = True
            continue
        if re.fullmatch(r"[*_\\~`]+", st):
            continue
        m = re.match(r"^(#{1,6})\s+(?:\d+[.)]\s+)?(.+?)\s*$", ln)
        if m:
            etic = re.sub(r"\s*\(.*\)\s*$", "", m.group(2))
            etic = re.sub(r"[*_:#]", "", etic).strip().lower()
            if etic == "articolo":
                continue
            out.append(SEZIONI[etic] if etic in SEZIONI else f"{m.group(1)} {m.group(2)}")
            continue
        out.append(ln)
    return "\n".join(out).strip()


def extract_json(text):
    """Estrae il JSON utile dall'output LLM, anche se il modello 'ragiona'.
    Scansiona tutti i gruppi bilanciati e preferisce l'array di oggetti."""
    text = re.sub(r"```(?:json)?", "", text)
    cands = []
    for open_c, close_c in (("[", "]"), ("{", "}")):
        for m in re.finditer(re.escape(open_c), text):
            i, depth = m.start(), 0
            for j in range(i, len(text)):
                if text[j] == open_c:
                    depth += 1
                elif text[j] == close_c:
                    depth -= 1
                    if depth == 0:
                        try:
                            cands.append(json.loads(text[i:j + 1]))
                        except Exception:
                            pass
                        break
    liste = [c for c in cands if isinstance(c, list) and c
             and all(isinstance(x, dict) for x in c)]
    if liste:
        return max(liste, key=len)
    dicts = [c for c in cands if isinstance(c, dict)]
    if dicts:
        return max(dicts, key=lambda d: len(json.dumps(d)))
    if cands:
        return cands[-1]
    raise ValueError("nessun JSON valido trovato nell'output LLM")


# ---------- TTS (edge-tts: voci neurali gratuite di Microsoft Edge) ----------

def tts_edge(text, out_mp3, voice="it-IT-IsabellaNeural", rate="-4%", pitch="+0Hz"):
    """Sintetizza `text` in un mp3 con edge-tts (gratis, nessuna API key).
    Voci italiane utili: it-IT-IsabellaNeural, it-IT-ElsaNeural, it-IT-DiegoNeural.
    Restituisce il percorso del file generato."""
    import asyncio
    import edge_tts

    async def _run():
        comm = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch)
        await comm.save(out_mp3)

    asyncio.run(_run())
    if not os.path.exists(out_mp3) or os.path.getsize(out_mp3) == 0:
        raise RuntimeError("edge-tts non ha prodotto audio (file vuoto)")
    return out_mp3


# ---------- ElevenLabs (voce di alta qualità, piano free senza carta) ----------

def _post_bytes(url, payload, headers, timeout=120):
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode(),
        headers={**headers, "Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def elevenlabs_crediti_residui(api_key=None):
    """Caratteri ancora disponibili nel mese (None se non determinabile)."""
    key = api_key or os.environ.get("ELEVENLABS_API_KEY")
    if not key:
        return None
    try:
        req = urllib.request.Request(
            "https://api.elevenlabs.io/v1/user/subscription",
            headers={"xi-api-key": key})
        with urllib.request.urlopen(req, timeout=20) as r:
            d = json.load(r)
        return max(0, d.get("character_limit", 0) - d.get("character_count", 0))
    except Exception:
        return None


def tts_elevenlabs(text, out_mp3, voice_id=None, model_id=None, api_key=None):
    """Sintetizza `text` in mp3 con ElevenLabs. Le puntate sono brevi (entro il
    limite per richiesta), quindi una sola chiamata. Restituisce il percorso."""
    key = api_key or os.environ["ELEVENLABS_API_KEY"]
    voice_id = voice_id or os.environ.get("ELEVENLABS_VOICE_ID", "21m00Tcm4TlvDq8ikWAM")
    model_id = model_id or os.environ.get("ELEVENLABS_MODEL", "eleven_multilingual_v2")
    url = (f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
           f"?output_format=mp3_44100_128")
    audio = _post_bytes(url, {"text": text, "model_id": model_id},
                        {"xi-api-key": key})
    with open(out_mp3, "wb") as f:
        f.write(audio)
    if os.path.getsize(out_mp3) == 0:
        raise RuntimeError("ElevenLabs non ha prodotto audio (file vuoto)")
    return out_mp3


# ---------- Google Cloud Text-to-Speech (voci Chirp 3 HD) ----------

def _split_tts(text, limit=2500):
    """Spezza il testo in blocchi <= limit caratteri, sui confini di paragrafo
    e, se serve, di frase. Evita di superare il limite per richiesta dell'API."""
    blocchi, buf = [], ""
    for para in re.split(r"\n\s*\n", text.strip()):
        para = para.strip()
        if not para:
            continue
        if len(para) > limit:
            # paragrafo troppo lungo: spezza per frase
            for frase in re.split(r"(?<=[.!?])\s+", para):
                if len(buf) + len(frase) + 1 > limit and buf:
                    blocchi.append(buf.strip())
                    buf = ""
                buf += frase + " "
        elif len(buf) + len(para) + 2 > limit and buf:
            blocchi.append(buf.strip())
            buf = para
        else:
            buf = f"{buf}\n\n{para}" if buf else para
    if buf.strip():
        blocchi.append(buf.strip())
    return blocchi


def tts_google(text, out_mp3, voice="it-IT-Chirp3-HD-Aoede", language_code="it-IT",
               api_key=None, speaking_rate=1.0):
    """Sintetizza `text` in mp3 con Google Cloud Text-to-Speech (voci Chirp 3 HD).
    Spezza i testi lunghi e concatena gli mp3. Restituisce il percorso del file.
    Richiede GOOGLE_TTS_API_KEY (API 'Cloud Text-to-Speech' abilitata sul progetto)."""
    import base64

    key = api_key or os.environ["GOOGLE_TTS_API_KEY"]
    url = f"https://texttospeech.googleapis.com/v1/text:synthesize?key={key}"
    audio = b""
    for blocco in _split_tts(text):
        payload = {
            "input": {"text": blocco},
            "voice": {"languageCode": language_code, "name": voice},
            "audioConfig": {"audioEncoding": "MP3", "speakingRate": speaking_rate},
        }
        d = _post(url, payload, {}, 120)
        b64 = d.get("audioContent")
        if not b64:
            raise RuntimeError(f"Google TTS: risposta senza audio ({str(d)[:160]})")
        audio += base64.b64decode(b64)
    with open(out_mp3, "wb") as f:
        f.write(audio)
    if os.path.getsize(out_mp3) == 0:
        raise RuntimeError("Google TTS non ha prodotto audio (file vuoto)")
    return out_mp3


# ---------- Internet Archive (hosting audio gratuito con API) ----------

def archive_upload(identifier, filepath, metadata, access_key=None, secret_key=None,
                   retries=2):
    """Carica un file su archive.org e restituisce l'URL pubblico diretto.
    Le chiavi S3 si generano (gratis) su https://archive.org/account/s3.php
    e vanno in ARCHIVE_ACCESS_KEY / ARCHIVE_SECRET_KEY."""
    import internetarchive as ia

    access_key = access_key or os.environ["ARCHIVE_ACCESS_KEY"]
    secret_key = secret_key or os.environ["ARCHIVE_SECRET_KEY"]
    fname = os.path.basename(filepath)
    last = ""
    for attempt in range(retries + 1):
        try:
            resp = ia.upload(identifier, files={fname: filepath}, metadata=metadata,
                             access_key=access_key, secret_key=secret_key,
                             retries=2, verbose=False)
            bad = [r for r in resp if getattr(r, "status_code", 200) not in (200, None)]
            if bad:
                last = f"status {[getattr(r, 'status_code', '?') for r in bad]}"
            else:
                return f"https://archive.org/download/{identifier}/{fname}"
        except Exception as e:
            last = repr(e)[:200]
        if attempt < retries:
            time.sleep(20)
    raise RuntimeError(f"upload su Internet Archive fallito: {last}")


# ---------- Tavily ----------

def tavily_search(query, max_results=6, days=14):
    key = os.environ["TAVILY_API_KEY"]
    d = _post("https://api.tavily.com/search",
              {"api_key": key, "query": query, "max_results": max_results,
               "search_depth": "advanced", "days": days}, {})
    return d.get("results", [])


# ---------- Firecrawl ----------

def firecrawl_scrape(url, timeout=120):
    return firecrawl_scrape_meta(url, timeout)[0]


def firecrawl_scrape_meta(url, timeout=120):
    """Ritorna (markdown, immagine_copertina) per una pagina."""
    key = os.environ["FIRECRAWL_API_KEY"]
    try:
        d = _post("https://api.firecrawl.dev/v1/scrape",
                  {"url": url, "formats": ["markdown"], "onlyMainContent": True},
                  {"Authorization": f"Bearer {key}"}, timeout)
        data = d.get("data", {}) or {}
        meta = data.get("metadata", {}) or {}
        cover = (meta.get("ogImage") or meta.get("og:image")
                 or meta.get("twitter:image") or meta.get("image") or "")
        if isinstance(cover, list):
            cover = cover[0] if cover else ""
        return data.get("markdown", "") or "", cover or ""
    except Exception:
        return "", ""


# ---------- RSS ----------

def fetch_rss_items(feeds_file, max_age_days=2, per_feed=6):
    import feedparser
    cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
    items = []
    for line in open(feeds_file, encoding="utf-8"):
        u = line.strip()
        if not u or u.startswith("#"):
            continue
        try:
            d = feedparser.parse(u, agent=UA)
        except Exception:
            continue
        src = u.split("/")[2].replace("www.", "")
        n = 0
        for e in d.entries:
            # data di pubblicazione (se disponibile)
            pub = None
            for k in ("published_parsed", "updated_parsed"):
                if e.get(k):
                    pub = datetime(*e[k][:6], tzinfo=timezone.utc)
                    break
            if pub and pub < cutoff:
                continue
            summary = re.sub(r"<[^>]+>", "", e.get("summary", ""))[:300]
            items.append({
                "source": src,
                "title": e.get("title", "").strip(),
                "url": e.get("link", ""),
                "summary": re.sub(r"\s+", " ", summary).strip(),
                "published": pub.isoformat() if pub else "",
            })
            n += 1
            if n >= per_feed:
                break
    return items
