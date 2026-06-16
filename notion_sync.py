#!/usr/bin/env python3
"""
Integrazione Notion (via REST API, solo libreria standard).

Funzioni:
- parse_news(markdown)          -> estrae le news dal brief
- add_news_rows(token,db,items) -> crea una riga per news nel database
- find_checked(token,db)        -> righe con "Scrivi articolo" spuntato e non Fatto
- set_status / uncheck          -> aggiorna lo stato della riga
- append_markdown(token,page,md)-> scrive l'articolo dentro la pagina Notion

Variabili d'ambiente: NOTION_TOKEN, NOTION_DB_ID
"""

import re
import json
import urllib.request
import urllib.error

API = "https://api.notion.com/v1"
VERSION = "2022-06-28"

ALLOWED_CATS = [
    "Design del Prodotto", "Graphic Design", "Fotografia",
    "Musica Elettronica", "Storia del Design",
]
# match robusto: chiave senza spazi/punteggiatura -> nome esatto
_CAT_MAP = {re.sub(r"[^a-z0-9]", "", c.lower()): c for c in ALLOWED_CATS}


def normalizza_categoria(testo):
    """Riconosce la categoria anche con maiuscole/spazi/slash diversi."""
    if not testo:
        return None
    return _CAT_MAP.get(re.sub(r"[^a-z0-9]", "", testo.lower()))


def _req(method, path, token, payload=None):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(
        API + path, data=data, method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Notion-Version": VERSION,
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"Notion {method} {path} -> {e.code}: {e.read().decode()[:300]}")


# ---------- parsing del brief ----------

_META = ("idee per titoli", "sul radar", "brief editoriale", "indice",
         "sommario", "panoramica")


def parse_news(md):
    """Estrae le schede-news dal brief markdown. Tollerante alle variazioni
    di formato di NotebookLM (etichette mancanti, livelli di heading diversi)."""
    items = []
    headings = list(re.finditer(r"(?m)^(#{1,6})\s+(.+)$", md))
    for i, h in enumerate(headings):
        level = len(h.group(1))
        title = h.group(2).strip().strip("*").strip()
        low = title.lower()
        # salta sezioni meta e il titolo-documento (primo heading di livello 1)
        if title.startswith(("💡", "📡")) or any(k in low for k in _META):
            continue
        if i == 0 and level == 1:
            continue
        start = h.end()
        end = headings[i + 1].start() if i + 1 < len(headings) else len(md)
        body = md[start:end]

        def field(*labels):
            for label in labels:
                m = re.search(r"\*\*\s*" + label + r"\s*:?\s*\*\*\s*:?\s*(.+?)"
                              r"(?=\n\s*[-*]\s*\*\*|\n#|\Z)", body, re.S | re.I)
                if not m:
                    m = re.search(label + r"\s*:\s*(.+?)(?=\n\s*[-*]|\n#|\Z)",
                                  body, re.S | re.I)
                if m:
                    return re.sub(r"\s+", " ", m.group(1)).strip()
            return ""

        summary = field("Di cosa parla", "In breve", "Perché pubblicarlo")
        categoria = field("Categoria").rstrip(".").strip()
        fonte = field("Fonte", "Fonti")
        # fallback: se manca il riassunto, usa il primo paragrafo della sezione
        if not summary:
            for para in re.split(r"\n\s*\n", body.strip()):
                p = re.sub(r"\s+", " ", re.sub(r"^[-*]\s*", "", para)).strip()
                if len(p) > 40 and not p.lower().startswith(("categoria", "fonte", "perché")):
                    summary = p
                    break
        # è una news solo se ha almeno un contenuto utile
        if not (summary or categoria or fonte):
            continue
        items.append({
            "title": title[:200],
            "summary": summary[:1900],
            "categoria": normalizza_categoria(categoria),
            "fonte": fonte[:1900],
        })
    return items


# ---------- scrittura righe ----------

def _titoli_esistenti(token, db_id, day):
    """Titoli gia' presenti nel database per quel giorno (anti-duplicati)."""
    try:
        res = _req("POST", f"/databases/{db_id}/query", token,
                   {"filter": {"property": "Data", "date": {"equals": day}}, "page_size": 100})
    except Exception:
        return set()
    out = set()
    for p in res.get("results", []):
        t = "".join(x.get("plain_text", "") for x in p["properties"]["Notizia"]["title"])
        out.add(t.strip())
    return out


def add_news_rows(token, db_id, items, day):
    esistenti = _titoli_esistenti(token, db_id, day)
    created = 0
    for it in items:
        if it["title"].strip() in esistenti:
            continue  # gia' presente oggi: salta il doppione
        esistenti.add(it["title"].strip())
        props = {
            "Notizia": {"title": [{"text": {"content": it["title"]}}]},
            "Di cosa parla": {"rich_text": [{"text": {"content": it["summary"]}}]},
            "Fonte": {"rich_text": [{"text": {"content": it["fonte"]}}]},
            "Stato": {"select": {"name": "Da fare"}},
            "Scrivi articolo": {"checkbox": False},
            "Data": {"date": {"start": day}},
        }
        if it["categoria"]:
            props["Categoria"] = {"select": {"name": it["categoria"]}}
        _req("POST", "/pages", token, {"parent": {"database_id": db_id}, "properties": props})
        created += 1
    return created


# ---------- watcher ----------

def find_checked(token, db_id):
    payload = {"filter": {"and": [
        {"property": "Scrivi articolo", "checkbox": {"equals": True}},
        {"property": "Stato", "select": {"does_not_equal": "Fatto"}},
        {"property": "Stato", "select": {"does_not_equal": "In corso"}},
    ]}}
    res = _req("POST", f"/databases/{db_id}/query", token, payload)
    out = []
    for p in res.get("results", []):
        props = p["properties"]
        title = "".join(t.get("plain_text", "") for t in props["Notizia"]["title"])
        summary = "".join(t.get("plain_text", "") for t in props["Di cosa parla"]["rich_text"])
        fonte = "".join(t.get("plain_text", "") for t in props["Fonte"]["rich_text"])
        cat = props.get("Categoria", {}).get("select")
        m = re.search(r"https?://\S+", fonte)
        out.append({"page_id": p["id"], "title": title, "summary": summary,
                    "categoria": cat["name"] if cat else "",
                    "fonte_url": m.group(0).rstrip(").,") if m else ""})
    return out


def urls_coperti(token, db_id, days=7):
    """URL delle fonti gia' presenti negli ultimi `days` giorni (anti-ripetizione)."""
    from datetime import date, timedelta
    since = (date.today() - timedelta(days=days)).isoformat()
    urls, cur = set(), None
    while True:
        payload = {"filter": {"property": "Data", "date": {"on_or_after": since}},
                   "page_size": 100}
        if cur:
            payload["start_cursor"] = cur
        res = _req("POST", f"/databases/{db_id}/query", token, payload)
        for p in res.get("results", []):
            fonte = "".join(t.get("plain_text", "") for t in p["properties"]["Fonte"]["rich_text"])
            m = re.search(r"https?://\S+", fonte)
            if m:
                urls.add(m.group(0).rstrip(").,").rstrip("/"))
        if not res.get("has_more"):
            break
        cur = res["next_cursor"]
    return urls


def _blocchi_pagina(token, page_id):
    """Tutti i blocchi figli di una pagina (con paginazione)."""
    blocchi, cur = [], None
    while True:
        path = f"/blocks/{page_id}/children?page_size=100"
        if cur:
            path += f"&start_cursor={cur}"
        res = _req("GET", path, token)
        blocchi.extend(res.get("results", []))
        if not res.get("has_more"):
            break
        cur = res["next_cursor"]
    return blocchi


def leggi_corpo_pubblico(token, page_id, max_chars=4000):
    """Testo semplice del corpo articolo, fermandosi al marcatore redazionale
    `## SEO` (tutto cio' che segue e' privato). Usato per dare all'LLM il
    contenuto reale degli articoli da riassumere nel podcast."""
    righe = []
    TIPI_TESTO = ("paragraph", "heading_1", "heading_2", "heading_3",
                  "quote", "bulleted_list_item", "numbered_list_item", "callout")
    for b in _blocchi_pagina(token, page_id):
        t = b.get("type")
        if t not in TIPI_TESTO:
            continue
        testo = "".join(r.get("plain_text", "") for r in b[t].get("rich_text", [])).strip()
        if not testo:
            continue
        # i heading "SEO/SOCIAL/IMMAGINI/NOTE FONTI" segnano l'inizio della parte privata
        if t.startswith("heading") and testo.strip("# ").upper() in (
                "SEO", "SOCIAL", "IMMAGINI", "NOTE FONTI"):
            break
        righe.append(testo)
        if sum(len(r) for r in righe) > max_chars:
            break
    return re.sub(r"\n{3,}", "\n\n", "\n\n".join(righe)).strip()[:max_chars]


def articoli_pubblicati(token, db_id, days=7, leggi_corpo=True):
    """Articoli con `Pubblica` spuntato e `Data pubblicazione` negli ultimi `days`
    giorni. Restituisce title/summary/categoria/slug + (opzionale) corpo testuale.
    E' la base di partenza della puntata podcast settimanale."""
    from datetime import date, timedelta
    since = (date.today() - timedelta(days=days)).isoformat()
    payload = {"filter": {"and": [
        {"property": "Pubblica", "checkbox": {"equals": True}},
        {"property": "Data pubblicazione", "date": {"on_or_after": since}},
    ]}, "sorts": [{"property": "Data pubblicazione", "direction": "ascending"}],
        "page_size": 100}
    res = _req("POST", f"/databases/{db_id}/query", token, payload)
    out = []
    for p in res.get("results", []):
        props = p["properties"]
        title = "".join(t.get("plain_text", "") for t in props["Notizia"]["title"])
        if not title:
            continue
        summary = "".join(t.get("plain_text", "") for t in
                          props.get("Di cosa parla", {}).get("rich_text", []))
        slug = "".join(t.get("plain_text", "") for t in
                       props.get("Slug", {}).get("rich_text", []))
        cat = props.get("Categoria", {}).get("select")
        corpo = leggi_corpo_pubblico(token, p["id"]) if leggi_corpo else ""
        out.append({
            "page_id": p["id"], "title": title.strip(), "summary": summary.strip(),
            "categoria": cat["name"] if cat else "", "slug": slug.strip(),
            "corpo": corpo,
        })
    return out


def crea_episodio(token, podcast_db_id, ep):
    """Crea una riga nel database Notion 'Podcast' con i metadati della puntata
    e il copione completo nel corpo pagina. `ep` ha: titolo, data (ISO),
    descrizione, audio_url, durata, articoli (lista di {title, slug}), copione."""
    articoli_txt = "; ".join(a.get("title", "") for a in ep.get("articoli", []))
    props = {
        "Titolo": {"title": [{"text": {"content": ep["titolo"][:200]}}]},
        "Data": {"date": {"start": ep["data"]}},
        "Audio": {"url": ep["audio_url"]},
        "Descrizione": {"rich_text": [{"text": {"content": ep.get("descrizione", "")[:1900]}}]},
        "Durata": {"rich_text": [{"text": {"content": ep.get("durata", "")[:50]}}]},
        "Articoli": {"rich_text": [{"text": {"content": articoli_txt[:1900]}}]},
    }
    page = _req("POST", "/pages", token,
                {"parent": {"database_id": podcast_db_id}, "properties": props})
    # copione completo nel corpo (utile come trascrizione/show-notes)
    if ep.get("copione"):
        append_markdown(token, page["id"], ep["copione"])
    return page["id"]


def set_cover(token, page_id, url):
    _req("PATCH", f"/pages/{page_id}", token,
         {"properties": {"Copertina": {"url": url}}})


def set_slug(token, page_id, slug):
    _req("PATCH", f"/pages/{page_id}", token,
         {"properties": {"Slug": {"rich_text": [{"text": {"content": slug[:200]}}]}}})


def articoli_correlati(token, db_id, categoria, exclude_id="", limit=6):
    """Articoli REALI gia' scritti (Stato=Fatto) della stessa categoria, con slug.
    Sono i candidati per i link interni: l'AI puo' linkare solo questi."""
    if not categoria:
        return []
    payload = {"page_size": 30, "filter": {"and": [
        {"property": "Categoria", "select": {"equals": categoria}},
        {"property": "Stato", "select": {"equals": "Fatto"}},
        {"property": "Slug", "rich_text": {"is_not_empty": True}},
    ]}}
    try:
        res = _req("POST", f"/databases/{db_id}/query", token, payload)
    except Exception:
        return []
    out = []
    for p in res.get("results", []):
        if p["id"] == exclude_id:
            continue
        title = "".join(t.get("plain_text", "") for t in p["properties"]["Notizia"]["title"])
        slug = "".join(t.get("plain_text", "") for t in p["properties"]["Slug"]["rich_text"])
        if title and slug:
            out.append({"title": title, "slug": slug.strip()})
        if len(out) >= limit:
            break
    return out


def set_status(token, page_id, status):
    _req("PATCH", f"/pages/{page_id}", token,
         {"properties": {"Stato": {"select": {"name": status}}}})


def uncheck(token, page_id):
    _req("PATCH", f"/pages/{page_id}", token,
         {"properties": {"Scrivi articolo": {"checkbox": False}}})


def _txt(content, bold=False, italic=False, link=None):
    """Uno o piu' oggetti rich_text (spezzati a 1900 char), con annotazioni."""
    out = []
    for i in range(0, len(content) or 1, 1900):
        chunk = content[i:i + 1900]
        t = {"content": chunk}
        if link:
            t["link"] = {"url": link}
        out.append({
            "type": "text",
            "text": t,
            "annotations": {"bold": bold, "italic": italic},
        })
    return out


_INLINE = re.compile(
    r"\[([^\]]+)\]\((https?://[^)\s]+)\)"   # 1,2  link [testo](url)
    r"|\*\*(.+?)\*\*"                        # 3    **grassetto**
    r"|__(.+?)__"                            # 4    __grassetto__
    r"|\*(.+?)\*"                            # 5    *corsivo*
    r"|_(.+?)_"                              # 6    _corsivo_
)


def parse_inline(text):
    """Converte markdown inline (grassetto/corsivo/link) in rich_text Notion."""
    text = (text or "").replace("\\*", "*").replace("\\_", "_")
    out, pos = [], 0
    for m in _INLINE.finditer(text):
        if m.start() > pos:
            out += _txt(text[pos:m.start()])
        if m.group(1) is not None:
            out += _txt(m.group(1), link=m.group(2))
        elif m.group(3) is not None:
            out += _txt(m.group(3), bold=True)
        elif m.group(4) is not None:
            out += _txt(m.group(4), bold=True)
        elif m.group(5) is not None:
            out += _txt(m.group(5), italic=True)
        elif m.group(6) is not None:
            out += _txt(m.group(6), italic=True)
        pos = m.end()
    if pos < len(text):
        out += _txt(text[pos:])
    return out or _txt("")


def md_to_blocks(md):
    blocks = []
    for line in md.splitlines():
        s = line.rstrip()
        if not s.strip():
            continue
        ls = s.lstrip()
        if re.fullmatch(r"-{3,}|\*{3,}|_{3,}", ls):
            blocks.append({"type": "divider", "divider": {}})
        elif s.startswith("### "):
            blocks.append({"type": "heading_3", "heading_3": {"rich_text": parse_inline(s[4:])}})
        elif s.startswith("## "):
            blocks.append({"type": "heading_2", "heading_2": {"rich_text": parse_inline(s[3:])}})
        elif s.startswith("# "):
            blocks.append({"type": "heading_2", "heading_2": {"rich_text": parse_inline(s[2:])}})
        elif ls.startswith("> "):
            blocks.append({"type": "quote", "quote": {"rich_text": parse_inline(ls[2:])}})
        elif ls.startswith(("- ", "* ")):
            blocks.append({"type": "bulleted_list_item",
                           "bulleted_list_item": {"rich_text": parse_inline(ls[2:])}})
        else:
            blocks.append({"type": "paragraph", "paragraph": {"rich_text": parse_inline(s)}})
    return blocks


def append_markdown(token, page_id, md):
    blocks = md_to_blocks(md)
    # Notion: max 100 blocchi per richiesta
    for i in range(0, len(blocks), 90):
        _req("PATCH", f"/blocks/{page_id}/children", token,
             {"children": blocks[i:i + 90]})
