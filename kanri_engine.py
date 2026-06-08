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


# ---------- Tavily ----------

def tavily_search(query, max_results=6, days=14):
    key = os.environ["TAVILY_API_KEY"]
    d = _post("https://api.tavily.com/search",
              {"api_key": key, "query": query, "max_results": max_results,
               "search_depth": "advanced", "days": days}, {})
    return d.get("results", [])


# ---------- Firecrawl ----------

def firecrawl_scrape(url, timeout=120):
    key = os.environ["FIRECRAWL_API_KEY"]
    try:
        d = _post("https://api.firecrawl.dev/v1/scrape",
                  {"url": url, "formats": ["markdown"], "onlyMainContent": True},
                  {"Authorization": f"Bearer {key}"}, timeout)
        return (d.get("data", {}) or {}).get("markdown", "") or ""
    except Exception:
        return ""


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
