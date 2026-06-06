# Handoff — Sito/Blog "mire" alimentato da Notion

> Documento per l'assistente che costruirà il sito. Spiega **da dove prendere i
> contenuti** e come renderizzarli. La fonte dei contenuti è un **database
> Notion** (Notion-as-CMS). Il sito è statico, da deployare su **Vercel**.

---

## 1. Architettura

```
Notion (database "Radar News")  =  il CMS / fonte dei contenuti
        ↓  (Notion API, a build time)
Sito statico (Next.js)  →  deploy su Vercel
```

- Gli articoli sono **righe** del database. Il **testo dell'articolo** è nel
  **corpo della pagina** Notion di ogni riga (blocchi).
- Pubblicare = far ripartire un build di Vercel (via Deploy Hook).

## 2. Accesso ai dati (Notion API)

- Endpoint base: `https://api.notion.com/v1`
- Header: `Authorization: Bearer <NOTION_TOKEN>`, `Notion-Version: 2022-06-28`
- **NOTION_TOKEN**: creare un'integrazione interna su
  https://www.notion.so/my-integrations (sola lettura va bene) e **condividere
  il database con l'integrazione** (database → ••• → Connections). Mettere il
  token come **Environment Variable su Vercel** (`NOTION_TOKEN`). NON committarlo.
- **Database ID**: `234c80b5af8546f38b1b1fc866b876f1`
- (Data source / collection ID, se serve l'API nuova: `428cc2cf-c45c-4cf3-8baf-3e843122e77f`)

Libreria consigliata: `@notionhq/client`. Per convertire il corpo pagina in
Markdown/HTML: `notion-to-md` (oppure rendering manuale dei blocchi).

## 3. Schema del database "Radar News"

Proprietà attuali di ogni riga:

| Proprietà | Tipo | Contenuto |
|-----------|------|-----------|
| `Notizia` | title | Titolo della news/articolo |
| `Categoria` | select | Arte / Arte visiva / Product design / Graphic design / UI-UX design / Architettura / Musica / Fotografia / Cultura visiva |
| `Di cosa parla` | rich_text | Riassunto breve (ottimo come **estratto/anteprima**) |
| `Fonte` | rich_text | Titolo fonte + eventuale link |
| `Scrivi articolo` | checkbox | (uso interno: innesca la scrittura dell'articolo) |
| `Stato` | select | `Da fare` / `In corso` / `Fatto` (`Fatto` = articolo scritto nel corpo pagina) |
| `Data` | date | Data della news |

### Dove sta il testo dell'articolo
Nel **corpo della pagina** Notion della riga (non in una proprietà). Si legge con
`blocks.children.list({ block_id: pageId })` (paginare con `start_cursor`).

Il corpo ha questa struttura (Markdown logico):
```
# Titolo dell'articolo
occhiello / sommario (1-2 frasi)
---
### sezione...
### sezione...
---
## SEO          ← Titolo SEO, Meta description, Slug, Parole chiave
## SOCIAL       ← caption Instagram / LinkedIn / X
## IMMAGINI     ← suggerimenti immagini
## NOTE FONTI   ← elenco fonti
```

**Per il sito pubblico:** mostrare SOLO la parte **articolo**, cioè tutto il
contenuto **fino all'intestazione `## SEO`**. Le sezioni `## SEO`, `## SOCIAL`,
`## IMMAGINI`, `## NOTE FONTI` sono materiale di redazione: usarle così:
- `## SEO` → ricavare `<title>` e `<meta name="description">` della pagina
- le altre → ignorarle nel sito pubblico (eventualmente in una vista admin)

## 4. Quali righe pubblicare

✅ Esiste già la checkbox **`Pubblica`**. Il sito mostra SOLO le righe con
`Pubblica = true` (e corpo pagina non vuoto). Query:
```json
{ "filter": { "and": [
  { "property": "Pubblica", "checkbox": { "equals": true } }
] } }
```

> Formato esatto del corpo articolo: vedere **FORMATO-ARTICOLI.md**. In sintesi:
> il corpo NON ripete il titolo, inizia con un paragrafo d'attacco, usa `##`/`###`
> per le sezioni, e la parte pubblica finisce all'intestazione esatta `## SEO`.

## 5. Proprietà consigliate da aggiungere (per un sito pulito)

Idealmente aggiungere al database (a mano in Notion) queste proprietà:

| Proprietà | Tipo | Uso nel sito | Fallback se assente |
|-----------|------|--------------|---------------------|
| `Pubblica` | checkbox | quali articoli sono online | usare `Stato = Fatto` |
| `Slug` | rich_text | URL della pagina (`/articolo/<slug>`) | generarlo dal titolo (slugify) |
| `Copertina` | files o url | immagine in cima/anteprima | nessuna immagine, o cover di default |
| `Estratto` | rich_text | testo anteprima in homepage | usare `Di cosa parla` |

Se non vengono aggiunte, derivare con i fallback indicati (es. slug dal titolo,
estratto da `Di cosa parla`).

## 6. Pagine del sito da generare

- **Home**: elenco articoli pubblicati, ordinati per `Data` (desc), con titolo,
  categoria, estratto, copertina.
- **Pagina articolo** (`/articolo/<slug>`): titolo, data, categoria, corpo
  articolo (fino a `## SEO`), `<title>`/`<meta>` dai dati SEO.
- **Categoria** (`/categoria/<categoria>`): elenco filtrato per `Categoria`.

## 7. Stack e deploy consigliati

- **Next.js (App Router)** su **Vercel**.
- Fetch da Notion **a build time** (SSG) con `@notionhq/client`. Opzionale ISR:
  `export const revalidate = 3600`.
- **Pubblicazione istantanea**: creare un **Deploy Hook** su Vercel
  (Project → Settings → Git → Deploy Hooks). Chiamando quell'URL (POST) il sito
  si ri-genera. Si può collegare a un pulsante/automazione Notion quando si
  spunta `Pubblica`.
- Variabili d'ambiente su Vercel: `NOTION_TOKEN`, `NOTION_DATABASE_ID`.

## 8. Note

- Il sito deve essere **sola lettura** verso Notion (non scrive nulla).
- Categorie disponibili: vedere l'elenco nello schema (sezione 3).
- Lingua dei contenuti: italiano.
- Identità "mire": magazine di arte, design e cultura visiva.
```
