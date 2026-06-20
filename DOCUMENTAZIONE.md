# 📚 Documentazione Completa KANRI: Automazione & Frontend Web

Benvenuto nella documentazione tecnica e operativa dell'infrastruttura editoriale e web per **KANRI** (rivista indipendente di arte, design e cultura visiva). 

Questo documento descrive sia l'**infrastruttura di automazione backend** (ospitata su un server VPS Ubuntu) sia il **sito web frontend** (Next.js ospitato su Vercel), che sono legati da **Notion** utilizzato come Headless CMS.

---

## 🗺️ Architettura Generale dell'Ecosistema

L'intero sistema KANRI è circolare: l'automazione raccoglie e genera contenuti che vengono salvati su Notion, e il frontend Next.js interroga Notion per generare le pagine statiche distribuite agli utenti.

```mermaid
graph TD
    %% Fonti esterne
    Feeds[Feed RSS <br>kanri_feeds.txt] -->|07:00 timer| Brief[kanri_brief.py]
    
    %% Flusso Curation
    Brief -->|1. Filtra già pubblicati| NotionDB[(Database Notion <br>'Radar News')]
    Brief -->|2. Seleziona & cura| OpenRouter{OpenRouter/LLM}
    OpenRouter -->|3. Inserisce news 'Da fare'| NotionDB
    Brief -->|4. Invia email| Resend[Resend API] -->|Email| UserEmail[Email redazione]
    
    %% Flusso Watcher (Generazione Articoli)
    NotionDB -->|Spunta 'Scrivi articolo'| Watcher[notion_watcher.py]
    Watcher -->|Richiesta articolo| Article[kanri_article.py]
    Article -->|Ricerca SEO & Fonti| Tavily[Tavily Search API]
    Article -->|Estrae testo originale| Firecrawl[Firecrawl Scraper API]
    Article -->|Trova articoli correlati| NotionDB
    Article -->|Genera articolo| Gemini{Gemini / OpenRouter}
    Gemini -->|Scrive in pagina + SEO| Watcher
    Watcher -->|Aggiorna properties & body| NotionDB
    Watcher -->|Stato = Fatto| NotionDB
    
    %% Trigger manuale
    NotionButton[Notion Button] -->|Trigger manuale| WebServer[trigger_server.py]
    WebServer -->|Avvia servizio| Brief

    %% Flusso Podcast settimanale (KANRI Tape)
    NotionDB -->|Lun 08:00: articoli pubblicati settimana| Podcast[kanri_podcast.py]
    Podcast -->|Copione| LLMpod{Gemini / OpenRouter}
    LLMpod -->|Testo parlato| Podcast
    Podcast -->|Sintesi vocale gratis| EdgeTTS[edge-tts mp3]
    EdgeTTS -->|Upload audio| Archive[(Internet Archive)]
    Podcast -->|Metadati puntata| PodcastDB[(Database Notion 'Podcast')]
    PodcastDB -->|Player + feed RSS| Vercel

    %% Frontend Next.js (Vercel)
    Vercel[Next.js App Router <br>Vercel Host] -->|Fetch Notion API <br>a build time / ISR| NotionDB
    Vercel -->|Deploy Hook (POST)| Vercel
    NotionDB -->|Spunta 'Pubblica'| Vercel
    
    %% Client finali
    Users[Utenti Web] -->|Navigazione| Vercel
    AI_Bots[AI Crawlers] -->|llms.txt / Robots| Vercel
```

---

## 🗃️ 1. Il Database Notion ("Radar News") come CMS

Il database Notion rappresenta l'unica sorgente di verità (Single Source of Truth) dei contenuti di KANRI.

### 📋 Schema dei Campi del Database

| Proprietà | Tipo | Ruolo | Fallback / Note |
|:---|:---|:---|:---|
| `Notizia` | title | Titolo dell'articolo / news. | Titolo principale mostrato sul sito. |
| `Categoria` | select | Categoria tematica (Arte, Arte visiva, Product design, Graphic design, UI-UX design, Architettura, Musica, Fotografia, Cultura visiva). | Usato per l'ordinamento e la categorizzazione. |
| `Di cosa parla` | rich_text | Breve riassunto editoriale (1-2 frasi). | Usato come anteprima dell'articolo in homepage. |
| `Fonte` | rich_text | Titolo della fonte + eventuale link web. | Riferimento usato dall'AI per la documentazione. |
| `Scrivi articolo` | checkbox | Trigger manuale per l'automazione. | Spuntando questa casella, il watcher VPS scriverà l'articolo. |
| `Stato` | select | Stato redazionale (`Da fare`, `In corso`, `Fatto`). | Gestito dall'automazione per tracciare lo stato di scrittura. |
| `Pubblica` | checkbox | Spunta di visibilità pubblica. | Il sito Next.js mostra l'articolo online solo se `Pubblica` è attiva. |
| `Data` | date | Data della news inserita dal brief RSS. | Interna, non usata per l'ordinamento pubblico. |
| `Data pubblicazione`| date | Data effettiva di rilascio dell'articolo. | Impostata automaticamente al giorno di pubblicazione. |
| `Copertina` | files / url | Immagine di copertina dell'articolo. | Se assente, il frontend genera una cover halftone grafica. |
| `Slug` | rich_text | Slug URL della pagina (es. `nome-articolo`). | Estratto dal blocco SEO o generato dallo slugify del titolo. |

---

### 📝 Struttura del Corpo Pagina (Markdown logico)

Il corpo della pagina Notion ospita il testo completo dell'articolo scritto in Markdown. Contiene una riga di demarcazione fondamentale `## SEO` che divide la parte **pubblica** da quella **privata (redazionale)**.

Il parser del sito (`lib/parse.ts`) legge il corpo pagina fino all'intestazione `## SEO` per la visualizzazione sul sito, mentre analizza le righe successive per estrarre i metadati.

```markdown
Il primo paragrafo funge da attacco dell'articolo e riceve il capolettera sul sito.
Deve contenere 1-2 frasi chiave che sintetizzano l'avvenimento.

## Sezione 1
Testo del paragrafo con **grassetto**, *corsivo* e [link veri](https://...).

## Sezione 2
Altro testo strutturato. Le citazioni grafiche si fanno così:
> Questa è una citazione in evidenza.

## Conclusione
Paragrafo conclusivo dell'articolo.

## SEO
- Titolo SEO: Titolo ottimizzato per i motori di ricerca
- Meta description: Descrizione breve (120-155 caratteri) per Google
- Slug URL: slug-della-pagina
- Parole chiave: termine1, termine2, termine3

## SOCIAL
### Instagram
Caption proposta per i social...

## IMMAGINI
- Suggerimento immagine 1 (fonte...)

## NOTE FONTI
- https://fonteoriginale.com/news
```

---

## 🤖 2. Il Sistema di Automazione Editoriale (VPS)

Gli script di automazione risiedono nella cartella `/opt/notebooklm` su una VPS Ubuntu 24.04 (`217.160.100.63`) e sono orchestrati da **systemd timers**.

### 📂 Struttura dei File della VPS
* `kanri_brief.py`: Esegue la scansione RSS mattutina e seleziona le notizie con **due passate** LLM: una dedicata alla **musica elettronica** (quota garantita, default 2, via `BRIEF_MUSICA`) dai soli feed musicali, e una **generale** per il resto fino a `BRIEF_TOTALE` (default 7), con priorità su product/graphic design. Cap basso per feed e finestra di 7 giorni per variare le fonti. Crea le righe in Notion come "Da fare" e invia l'email del brief via Resend.
* `kanri_article.py`: Script di core che esegue ricerche web via Tavily, estrae i testi delle fonti con Firecrawl, trova articoli correlati in Notion, e fa redigere l'articolo a Gemini o OpenRouter.
* `notion_watcher.py`: Demone che esamina Notion ogni 5 minuti alla ricerca di righe con `Scrivi articolo` spuntato, avviando il processo di generazione.
* `notion_sync.py`: Client Notion personalizzato per convertire il Markdown in blocchi ricchi Notion e aggiornare le proprietà delle pagine.
* `kanri_engine.py`: Gestore unificato delle chiamate API per LLM (Gemini/OpenRouter), Tavily, Firecrawl, RSS e email.
* `kanri_podcast.py`: Genera la puntata podcast settimanale **KANRI Tape** (digest breve ~2 min). Legge da Notion gli articoli pubblicati nell'ultima settimana, fa scrivere il copione a un LLM, lo sintetizza in mp3 con **ElevenLabs** (free, senza carta; fallback Google Chirp 3 HD → edge-tts), carica l'audio su **Internet Archive** e salva i metadati nel database Notion "Podcast".
* `podcast_instructions.txt`: Prompt di voce del podcast (copione parlato, tono sobrio, regola anti-invenzione, struttura intro/articoli/chiusura).
* `trigger_server.py`: Server HTTP leggero (porta `8765`) che risponde all'endpoint `/cerca-news?token=...` per forzare la scansione RSS manuale.
* `kanri_feeds.txt`: Elenco dei feed RSS da scansionare.
* `article_instructions.txt`: Prompt contenente lo stile di scrittura, le limitazioni lessicali (evitare metafore banali e frasi pubblicitarie) e le linee guida SEO.
* `notebooklm.env`: Contiene tutte le API key e i segreti del server (escluso dal controllo Git).

---

### 🖥️ Comandi Utili per la VPS (via SSH)

Accedi alla VPS con `ssh root@217.160.100.63`:

#### Brief Mattutino (RSS -> Notion)
* **Forzare il brief immediato**: `systemctl start notebooklm-research.service`
* **Vedere i log live**: `journalctl -u notebooklm-research.service -f`

#### Watcher di Scrittura (Notion Watcher)
* **Controllare lo stato del watcher timer**: `systemctl status notebooklm-watcher.timer`
* **Controllare i log di scrittura articoli**: `journalctl -u notebooklm-watcher.service -f`

#### Server Trigger
* **Controllare lo stato del ricevitore**: `systemctl status notebooklm-trigger.service`
* **Riavviare il server trigger**: `systemctl restart notebooklm-trigger.service`

#### Podcast Settimanale (KANRI Tape)
* **Stato del timer**: `systemctl status notebooklm-podcast.timer`
* **Generare subito una puntata (test)**: `systemctl start notebooklm-podcast.service`
* **Log live della generazione**: `journalctl -u notebooklm-podcast.service -f`

---

## 🎙️ 2-bis. Podcast Settimanale "KANRI Tape"

Ogni **lunedì alle 08:00** (timer `notebooklm-podcast.timer`) lo script `kanri_podcast.py`:

1. **Seleziona gli articoli pubblicati** della settimana — query Notion con `Pubblica = true` e `Data pubblicazione` negli ultimi 7 giorni (variabile `PODCAST_DAYS`).
2. **Scrive il copione** con l'LLM (Gemini → OpenRouter, modelli free) usando `podcast_instructions.txt`: un **digest breve (~2 minuti)** in voce KANRI, con regola anti-invenzione (solo dati realmente presenti nelle fonti). Il copione viene troncato a `PODCAST_MAX_CHARS` (default 2400) su confine di frase, per non sforare la quota TTS mensile.
3. **Sintetizza l'audio** con **ElevenLabs** (piano free, **nessuna carta**: 10.000 caratteri/mese ≈ 4-5 puntate brevi). Catena di fallback automatica: ElevenLabs → Google Chirp 3 HD (se presente `GOOGLE_TTS_API_KEY`) → `edge-tts` (sempre disponibile). Prima di sintetizzare verifica i caratteri residui del mese via API e, se insufficienti, passa al fallback.
3b. **Monta il sottofondo musicale** con `ffmpeg`: alcuni secondi di musica pulita in apertura (`PODCAST_INTRO_SEC`), poi la voce con la base in **ducking** (si abbassa quando si parla, `PODCAST_MUSIC_VOLUME`) e dissolvenza finale. La traccia è `assets/kanri-bed.mp3` (override con `PODCAST_BG_MUSIC`). Se `ffmpeg` o la traccia mancano, pubblica la sola voce.
4. **Carica l'mp3 su Internet Archive** (hosting gratuito e permanente con API S3). L'URL pubblico è `https://archive.org/download/kanri-tape-<data>/kanri-tape-<data>.mp3`. Le chiavi si generano su `https://archive.org/account/s3.php` e vanno in `ARCHIVE_ACCESS_KEY` / `ARCHIVE_SECRET_KEY`.
5. **Salva i metadati su Notion** nel database "Podcast" (`PODCAST_DB_ID`) — il frontend leggerà da qui per costruire player e feed RSS.
6. **Invia un'email** di notifica con il copione allegato (Resend).

> Tutto il flusso è **gratuito e senza carta**: ElevenLabs free non richiede metodo di pagamento, Internet Archive offre hosting audio illimitato gratuito, gli LLM usati sono i modelli free già in uso. Nota legale: il piano free di ElevenLabs è **non commerciale** e richiede l'**attribuzione** a ElevenLabs. Le puntate restano brevi per stare nei 10.000 caratteri/mese; per puntate lunghe o uso commerciale servirebbe un piano a pagamento o Google Chirp 3 HD (che richiede una carta sul billing, pur restando a €0).

### 🗃️ Schema del Database Notion "Podcast" (contratto per il frontend)

Crea un nuovo database Notion, condividilo con l'integrazione e incolla il suo ID in `PODCAST_DB_ID`. Lo script popola queste proprietà:

| Proprietà | Tipo | Contenuto |
|:---|:---|:---|
| `Titolo` | title | Es. "KANRI Tape — 9–15 giugno 2026". |
| `Data` | date | Data di pubblicazione della puntata. |
| `Audio` | url | URL diretto dell'mp3 su Internet Archive (per `<audio>` ed `<enclosure>` RSS). |
| `Descrizione` | rich_text | Sinossi breve della puntata. |
| `Durata` | rich_text | Durata stimata `mm:ss`. |
| `Articoli` | rich_text | Titoli degli articoli trattati, separati da `;`. |

Il **copione completo** viene scritto nel **corpo della pagina** (usabile come trascrizione / show-notes).

Il feed podcast lato frontend (es. `/podcast.xml`) usa gli `<enclosure url=…>` puntando all'URL `Audio` su Internet Archive: il feed resta di proprietà di KANRI e può essere sottoscritto una volta su Spotify/Apple.

## 🎨 3. Il Sito Web Frontend (Next.js / Vercel)

Il sito web risiede nella cartella locale `/Users/alessandromazzola/Desktop/Siti/blog` ed è distribuito sulla piattaforma **Vercel** (`https://kanri.chiamamial.com`).

### 🏛️ Architettura del Codice
Il sito è sviluppato con **Next.js (App Router)** e TypeScript, utilizzando CSS nativo (Vanilla CSS) per l'estetica rétro da magazine indipendente anni '80 (colori ad alto contrasto, griglie marcate, stile risograph e caratteri monospace/grotesque).

```
app/
├── articolo/[slug]/
│   ├── page.tsx               # Pagina dell'articolo singolo (Deep-link)
│   └── opengraph-image.tsx    # Generazione dinamica al volo dell'immagine OG
├── categoria/[categoria]/
│   └── page.tsx               # Articoli filtrati per categoria
├── feed.xml/
│   └── route.ts               # Endpoint RSS per AI e lettori feed
├── llms.txt/
│   └── route.ts               # Mappa del sito testuale per i motori AI (GEO)
├── globals.css                # CSS principale, variabili di colore e layout
├── layout.tsx                 # Layout globale del sito
├── page.tsx                   # Homepage (carica e renderizza i Miller Columns)
├── MillerColumns.tsx          # Componente interattivo a tre colonne (Desktop & Mobile)
├── ArticleCover.tsx           # Renderizza la copertina dell'articolo (o il risograph fallback)
├── Ticker.tsx                 # News ticker scorrevole in alto
├── Scramble.tsx               # Effetto testo vintage "scrambled" all'hover
└── ThemeToggle.tsx            # Bottone di cambio modalità Chiara/Scura
lib/
├── notion.ts                  # Query a Notion API e gestione delle cache Next.js
├── parse.ts                   # Logica di split ed estrazione dei blocchi SEO
├── categoryColor.ts           # Mappa i colori ad ogni categoria o li genera stabilmente
├── site.ts                    # Metadati globali del sito (nome, URL, autore)
└── related.ts                 # Algoritmo di selezione degli articoli correlati
```

---

### 🗂️ Layout Interattivo: Three-Tier Miller Columns
La navigazione in homepage si basa sul layout **Miller Columns** (`app/MillerColumns.tsx`), strutturato in 3 colonne:
1. **Colonna 1 (Categorie)**: Elenco di tutte le categorie editoriali presenti.
2. **Colonna 2 (Articoli)**: Lista degli articoli appartenenti alla categoria selezionata.
3. **Colonna 3 (Reader)**: L'articolo completo selezionato per la lettura.

#### ⚙️ Gestione della History e URL Condivisibili
Per evitare che la navigazione ad una sola pagina comprometta la UX (come i tasti "Avanti/Indietro" del browser), il componente Miller Columns implementa la sincronizzazione manuale degli URL:
* Quando un utente seleziona un articolo, lo script esegue `window.history.pushState` impostando il parametro URL `?a=<slug>`.
* Questo rende l'URL immediatamente condivisibile e permette all'utente di usare il tasto "Indietro" per chiudere l'articolo, tornando all'elenco.
* Un listener sull'evento `popstate` intercetta i movimenti della cronologia del browser e riallinea lo stato di React (`syncFromUrl`), garantendo una UX fluida.
* **Ottimizzazione Mobile**: Su schermi piccoli il layout si riduce ad una sola colonna visibile alla volta tramite l'attributo `data-level` (0 = Categorie, 1 = Articoli, 2 = Lettura), offrendo bottoni di ritorno stile app nativa.

---

### 🎨 Copertina Risograph Halftone Dinamica (`ArticleCover.tsx`)
Quando un articolo non ha un'immagine di copertina caricata su Notion, il sistema genera un placeholder grafico on-brand altamente rifinito:
* Calcola un colore di sfondo deterministico per la categoria e un angolo di rotazione stabile a partire dal titolo dell'articolo (`lib/categoryColor.ts`).
* Renderizza sovrapposizioni CSS di filtri halftone (retino di stampa) e linee di scansione della fotocopiatrice che scorrono in loop.
* Il titolo dell'articolo riceve un effetto di sdoppiamento RGB (cromia fuori registro) che si anima delicatamente per simulare la stampa analogica.

---

### ⚡ Strategia di Caching, Fetching e Rigenerazione (ISR)
Per garantire tempi di risposta fulminei (Core Web Vitals eccellenti) senza saturare i limiti dell'API di Notion:
1. **SSG a Build Time**: Il caricamento di tutti gli articoli avviene principalmente a build time.
2. **Next Data Cache**: In produzione, la funzione `loadArticlesCached` in `lib/notion.ts` avvolge le query in `unstable_cache` con un tag `"articles"` e revalidation impostata a 60 secondi.
3. **React `cache()`**: Utilizzato per deduplicare chiamate ripetute nello stesso ciclo di rendering della pagina.
4. **Deploy in tempo reale (Instant Rebuild)**: Su Vercel è configurato un **Deploy Hook**. Quando una notizia viene impostata su `Pubblica = true` in Notion, un'automazione (o una chiamata manuale) effettua una chiamata `POST` a tale hook. Vercel avvia un rebuild parziale rivalidando i dati di Notion, rendendo l'articolo istantaneamente online.

---

## 🔍 4. Strategia SEO (Search Engine) & GEO (Generative Engine)

Il sito è fortemente ottimizzato sia per l'indicizzazione classica di Google sia per l'estrazione da parte dei motori AI (ChatGPT, Perplexity, Gemini, Claude).

| Ottimizzazione | File / Rotta | Scopo / Dettagli |
|:---|:---|:---|
| **Metadati Dinamici** | `generateMetadata` in `[slug]/page.tsx` | Estrae titolo SEO, meta description e tag dal blocco Notion `## SEO` impostando il link canonical corretto. |
| **Open Graph Images** | `[slug]/opengraph-image.tsx` | Genera dinamicamente al volo a livello server l'immagine di anteprima sociale per ogni articolo, includendo titolo e categoria. |
| **Sitemap XML** | `/sitemap.ts` | Genera l'indice dinamico degli URL per facilitare lo spidering di Google. |
| **Robots.txt** | `/robots.ts` | Consente l'accesso a tutti i crawler (compresi i crawler di addestramento AI). |
| **Feed RSS** | `/feed.xml/route.ts` | Genera un feed XML valido contenente tutti gli articoli ordinati per data, ideale per aggregatori di notizie e feed AI. |
| **JSON-LD Strutturati** | `lib/jsonld.tsx` | Inserisce dati strutturati ricchi (Schema.org) quali `NewsArticle`, `BreadcrumbList`, `CollectionPage` e `WebSite` per abilitare i rich snippet su Google. |
| **llms.txt (GEO)** | `/llms.txt/route.ts` | Fornisce una mappa di navigazione in testo semplice (Markdown leggero) ottimizzata per i LLM (standard `llmstxt.org`). Permette agli agenti AI di comprendere istantaneamente la struttura e citare le fonti degli articoli di KANRI. |

---

## 🛠️ Flusso Operativo per Modifiche al Codice

### 💻 Frontend (Next.js)
1. Esegui lo sviluppo locale nella cartella `/Siti/blog`:
   ```bash
   npm install
   npm run dev
   ```
2. Effettua le modifiche ai componenti React o al file `globals.css`.
3. Committa le modifiche e inviale a GitHub:
   ```bash
   git add .
   git commit -m "Aggiorna design Miller Columns"
   git push origin main
   ```
4. Vercel rileverà il push sulla branca principale e avvierà automaticamente il deploy in produzione.

### 🤖 Backend (Automazione su VPS)
1. Modifica i file sul computer locale (es. aggiornando `article_instructions.txt` o `kanri_feeds.txt`).
2. Invia i file modificati al repository GitHub:
   ```bash
   git add .
   git commit -m "Aggiorna istruzioni di scrittura articoli"
   git push origin main
   ```
3. Collegati alla VPS e scarica i file aggiornati:
   ```bash
   ssh root@217.160.100.63
   cd /opt/notebooklm && git pull
   ```
4. Se hai modificato file in `vps/` (come timer o servizi di systemd), ricarica la configurazione del sistema:
   ```bash
   cp /opt/notebooklm/vps/notebooklm-*.timer /opt/notebooklm/vps/notebooklm-*.service /etc/systemd/system/
   systemctl daemon-reload
   systemctl restart notebooklm-watcher.timer
   ```
