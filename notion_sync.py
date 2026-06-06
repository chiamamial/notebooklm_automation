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

ALLOWED_CATS = {
    "Arte", "Arte visiva", "Product design", "Graphic design",
    "UI-UX design", "Architettura", "Musica", "Fotografia", "Cultura visiva",
}


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

def parse_news(md):
    """Estrae le schede-news dal brief markdown."""
    items = []
    headings = list(re.finditer(r"(?m)^(#{2,3})\s+(.+)$", md))
    for i, h in enumerate(headings):
        title = h.group(2).strip().strip("*").strip()
        low = title.lower()
        if title.startswith(("💡", "📡")) or "idee per titoli" in low or "sul radar" in low:
            continue
        start = h.end()
        end = headings[i + 1].start() if i + 1 < len(headings) else len(md)
        body = md[start:end]

        def field(label):
            m = re.search(r"\*\*\s*" + label + r"\s*:\*\*\s*(.+?)(?=\n\s*[-*]\s*\*\*|\Z)",
                          body, re.S | re.I)
            if not m:
                m = re.search(label + r"\s*:\s*(.+?)(?=\n\s*[-*]|\Z)", body, re.S | re.I)
            return re.sub(r"\s+", " ", m.group(1)).strip() if m else ""

        summary = field("Di cosa parla")
        categoria = field("Categoria").rstrip(".").strip()
        fonte = field("Fonte")
        if not (categoria or fonte):
            continue
        items.append({
            "title": title[:200],
            "summary": summary[:1900],
            "categoria": categoria if categoria in ALLOWED_CATS else None,
            "fonte": fonte[:1900],
        })
    return items


# ---------- scrittura righe ----------

def add_news_rows(token, db_id, items, day):
    created = 0
    for it in items:
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
        out.append({"page_id": p["id"], "title": title, "summary": summary})
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
