#!/usr/bin/env python3
"""Rigenera l'articolo di una pagina Notion (svuota il vecchio e riscrive pulito).
Uso: python regen_article.py <page_id>"""

import json
import os
import re
import sys
import urllib.request as u

import notion_sync
from kanri_article import genera_articolo

TOK = os.environ["NOTION_TOKEN"]
PID = sys.argv[1]

r = u.Request(
    f"https://api.notion.com/v1/pages/{PID}",
    headers={"Authorization": f"Bearer {TOK}", "Notion-Version": "2022-06-28"},
)
p = json.load(u.urlopen(r))["properties"]
title = "".join(x["plain_text"] for x in p["Notizia"]["title"])
summary = "".join(x["plain_text"] for x in p["Di cosa parla"]["rich_text"])
fonte = "".join(x["plain_text"] for x in p["Fonte"]["rich_text"])
m = re.search(r"https?://\S+", fonte)
furl = m.group(0).rstrip(").,") if m else ""
catp = p.get("Categoria", {}).get("select")
cat = catp["name"] if catp else ""

body, cover, slug = genera_articolo(title, summary, furl, categoria=cat, exclude_id=PID)

# svuota i blocchi esistenti
children, cur = [], None
while True:
    q = f"/blocks/{PID}/children?page_size=100" + (f"&start_cursor={cur}" if cur else "")
    res = notion_sync._req("GET", q, TOK)
    children += res["results"]
    if not res.get("has_more"):
        break
    cur = res["next_cursor"]
for b in children:
    notion_sync._req("DELETE", "/blocks/" + b["id"], TOK)

notion_sync.append_markdown(TOK, PID, body)
if cover:
    notion_sync.set_cover(TOK, PID, cover)
if slug:
    notion_sync.set_slug(TOK, PID, slug)
notion_sync.set_status(TOK, PID, "Fatto")
print(f"rigenerato: {title[:40]} | blocchi: {len(children)} | cover: {bool(cover)} | slug: {slug}")
