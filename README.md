# KANRI — Automazione editoriale

Pipeline di automazione per una rivista digitale: raccoglie le news dai feed RSS,
le cura con un LLM, genera gli articoli, produce un podcast settimanale e tiene
pulito il database. **Notion** fa da CMS; il frontend (repo separato) legge da lì.

> Documentazione tecnica completa (architettura, schema Notion, frontend, SEO):
> [`DOCUMENTAZIONE.md`](DOCUMENTAZIONE.md).

## Architettura in breve

```
Feed RSS ─▶ kanri_brief ─▶ Notion (news "Da fare") ─▶ [spunta] ─▶ notion_watcher
                                                                      └▶ kanri_article ─▶ Notion (articolo)
Notion (pubblicati) ─▶ kanri_podcast ─▶ TTS + mix ─▶ Internet Archive + Notion
Notion (scaduti)    ─▶ kanri_cleanup ─▶ archivia
```

Tutto è orchestrato da **systemd timer** su una VPS. La logica core usa solo la
libreria standard; le dipendenze esterne servono a funzioni specifiche.

## Componenti

| File | Ruolo |
|:---|:---|
| `kanri_brief.py` | Scansione RSS + selezione LLM (due passate: musica + generale) → news su Notion + email. |
| `notion_watcher.py` | Controlla Notion e avvia la scrittura per le news spuntate. |
| `kanri_article.py` | Ricerca (Tavily/Firecrawl) + stesura articolo con LLM. |
| `kanri_podcast.py` | Copione LLM → TTS → mix musicale → upload audio → Notion. |
| `kanri_cleanup.py` | Archivia le news mai lavorate e scadute. |
| `kanri_engine.py` | Client condivisi: LLM, ricerca, RSS, TTS, audio, email. |
| `notion_sync.py` | Client Notion (REST). |
| `config.py` + `blog.config.json` | Configurazione del blog (config-driven). |
| `trigger_server.py` | Endpoint HTTP per forzare il brief manualmente. |

## Configurazione

Tutto ciò che è specifico del blog vive in [`blog.config.json`](blog.config.json)
(brand, categorie, priorità, parametri brief, podcast). Per gestire un altro blog
con lo stesso codice, punta la variabile d'ambiente `BLOG_CONFIG` a un altro file.

I segreti e i parametri runtime stanno in `notebooklm.env` (non versionato): vedi
[`.env.example`](.env.example).

## Sviluppo

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"      # runtime + ruff + pytest

ruff check .                 # lint
ruff format .                # formattazione
pytest -q                    # test
```

La CI ([`.github/workflows/ci.yml`](.github/workflows/ci.yml)) esegue lint,
controllo formattazione e test a ogni push/PR.

## Deploy (VPS)

```bash
ssh root@<host>
cd /opt/notebooklm && git pull --ff-only
.venv/bin/pip install -r requirements.txt        # se cambiano le dipendenze
cp vps/notebooklm-*.service vps/notebooklm-*.timer /etc/systemd/system/
systemctl daemon-reload
```

Setup iniziale completo: [`vps/setup.sh`](vps/setup.sh). Comandi e timer:
[`DOCUMENTAZIONE.md`](DOCUMENTAZIONE.md).

## Licenza

[MIT](LICENSE).
