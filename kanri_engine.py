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

def openrouter_chat(messages, max_tokens=4000, temperature=0.6, retries=2):
    key = os.environ["OPENROUTER_API_KEY"]
    model = os.environ.get("OPENROUTER_MODEL", "nvidia/nemotron-3-super-120b-a12b:free")
    payload = {"model": model, "messages": messages,
               "max_tokens": max_tokens, "temperature": temperature}
    headers = {"Authorization": f"Bearer {key}", "X-Title": "KANRI"}
    last = ""
    for attempt in range(retries + 1):
        try:
            d = _post("https://openrouter.ai/api/v1/chat/completions", payload, headers, 180)
            return d["choices"][0]["message"]["content"]
        except urllib.error.HTTPError as e:
            last = f"{e.code}: {e.read().decode()[:200]}"
        except Exception as e:
            last = repr(e)[:200]
        if attempt < retries:
            time.sleep(20)
    raise RuntimeError(f"OpenRouter fallito: {last}")


def extract_json(text):
    """Estrae il primo array/oggetto JSON dal testo (ignora il 'ragionamento')."""
    text = re.sub(r"```(?:json)?", "", text)
    for open_c, close_c in (("[", "]"), ("{", "}")):
        i = text.find(open_c)
        if i == -1:
            continue
        depth = 0
        for j in range(i, len(text)):
            if text[j] == open_c:
                depth += 1
            elif text[j] == close_c:
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[i:j + 1])
                    except Exception:
                        break
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
