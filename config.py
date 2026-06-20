#!/usr/bin/env python3
"""
Configurazione del blog (config-driven).

Tutto cio' che cambia da blog a blog vive in un file JSON (default
`blog.config.json`). Per gestire piu' blog con lo STESSO codice basta puntare
la variabile d'ambiente BLOG_CONFIG a un file diverso.

Espone:
  CONFIG            il dict completo
  BRAND, DESCRIZIONE, FIRMA
  CATEGORIE_NOMI    lista dei nomi categoria
  CATEGORIE_TESTO   "- Nome: descrizione" per il prompt
  get("a.b.c", default)   accesso annidato
"""

import json
import os
from pathlib import Path

_PATH = os.environ.get("BLOG_CONFIG", str(Path(__file__).parent / "blog.config.json"))

try:
    CONFIG = json.loads(Path(_PATH).read_text(encoding="utf-8"))
except Exception as e:
    raise RuntimeError(f"Config blog non caricabile da {_PATH}: {e}") from e


def get(path, default=None):
    """Accesso annidato tipo get('brief.totale', 7)."""
    cur = CONFIG
    for k in path.split("."):
        if isinstance(cur, dict) and k in cur:
            cur = cur[k]
        else:
            return default
    return cur


BRAND = CONFIG.get("brand", "Blog")
DESCRIZIONE = CONFIG.get("descrizione", "")
FIRMA = CONFIG.get("firma", DESCRIZIONE)
CATEGORIE = CONFIG.get("categorie", [])
CATEGORIE_NOMI = [c["nome"] for c in CATEGORIE]
CATEGORIE_TESTO = "\n".join(f"- {c['nome']}: {c['desc']}" for c in CATEGORIE)
