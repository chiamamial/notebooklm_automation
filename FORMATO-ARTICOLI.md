# KANRI — Specifica per la creazione degli articoli

> Documento da fornire all'assistente AI che scrive gli articoli.
> KANRI è una **rivista indipendente di arte, design e cultura visiva** (lingua: italiano).
> Ogni articolo è una **riga** di un database Notion ("Radar News"). Il **testo dell'articolo
> va scritto nel corpo della pagina** Notion della riga (non in una proprietà).
> Un sito web legge automaticamente Notion e pubblica gli articoli: **rispetta il formato
> esatto qui sotto**, altrimenti la resa sul sito sarà sbagliata.

---

## 1. Proprietà della riga (campi del database)

Compila questi campi della riga Notion:

| Proprietà | Tipo | Cosa scrivere |
|-----------|------|---------------|
| `Notizia` | titolo | **Il titolo dell'articolo.** È questo il titolo mostrato sul sito (NON quello nel corpo). |
| `Categoria` | select | Una sola tra: `Arte`, `Arte visiva`, `Product design`, `Graphic design`, `UI-UX design`, `Architettura`, `Musica`, `Fotografia`, `Cultura visiva`. |
| `Di cosa parla` | testo | Riassunto breve (1–2 frasi). Usato come **anteprima** in homepage. Testo semplice, niente markdown. |
| `Fonte` | testo | Titolo della fonte principale (+ eventuale link). |
| `Data` | data | Data della notizia. |
| `Stato` | select | Uso interno di redazione: `Da fare` / `In corso` / `Fatto`. Non influisce sulla pubblicazione. |
| `Pubblica` | checkbox | **Spunta = l'articolo va online.** Lascia vuoto finché non è pronto. |

> Un articolo appare sul sito **solo** se `Pubblica` è spuntata **e** il corpo pagina non è vuoto.

---

## 2. Dove va il testo: il corpo della pagina

Il testo completo dell'articolo va nel **corpo della pagina** Notion, in **Markdown**.
Il corpo è diviso in due parti da una linea di intestazione `## SEO`:

- **PRIMA di `## SEO`** = l'**articolo pubblico** (è ciò che si legge sul sito).
- **DA `## SEO` in poi** = **materiale di redazione** (SEO, social, immagini, fonti):
  resta privato, non viene pubblicato. Serve solo a te e al sito per i metadati.

---

## 3. Regole del corpo articolo (la parte pubblica)

1. **Non ripetere il titolo nel corpo.** Il titolo viene dalla proprietà `Notizia`.
   Niente `# Titolo`, niente `Sommario:`, niente `# Kit Editoriale`.
2. **Il primo blocco deve essere un paragrafo** (non un heading): è l'**attacco** dell'articolo
   e riceve il capolettera grafico. Scrivi 1–2 frasi che dicono subito **cosa/chi/quando/dove**.
3. **Sezioni con `##`**, eventuali sottosezioni con `###`. Non usare `#`.
   Titoli di sezione **brevi e descrittivi** (vanno benissimo anche sotto forma di domanda).
4. Usa **markdown vero**: `*corsivo*`, `**grassetto**`, `[testo del link](https://url)`,
   `> citazione`, elenchi con `-`. **Mai** asterischi con escape tipo `\*parola\*`.
5. Lunghezza consigliata: **500–900 parole**, 4–7 sezioni. Paragrafi brevi.
6. Chiudi con una sezione finale (es. `## Conclusione`) che tiri le fila.

---

## 4. Blocco SEO (obbligatorio, formato rigido)

Subito dopo l'articolo, inserisci **esattamente** questa intestazione e queste 4 righe.
Il sito le legge per generare `<title>`, `<meta description>`, URL e parole chiave.

```markdown
## SEO
- Titolo SEO: <titolo ottimizzato, max ~60 caratteri>
- Meta description: <descrizione invogliante, 120–155 caratteri>
- Slug URL: <parole-chiave-minuscole-separate-da-trattini>
- Parole chiave: <termine1, termine2, termine3, termine4>
```

Regole del blocco SEO:
- Le **etichette devono essere quelle esatte**: `Titolo SEO:`, `Meta description:`, `Slug URL:`, `Parole chiave:`.
- **Una riga per campo.**
- `Slug URL`: solo minuscole, senza accenti, parole separate da trattini (es. `nuova-biennale-venezia-2026`).
- `Parole chiave`: separate da **virgola**.

---

## 5. Sezioni di redazione opzionali (restano private)

Dopo il blocco SEO puoi aggiungere altre sezioni di lavorazione. Non vengono pubblicate:

```markdown
## SOCIAL
### Instagram
<caption>
### LinkedIn
<caption>
### X
<caption>

## IMMAGINI
- <suggerimento immagine 1 + fonte>
- <suggerimento immagine 2 + fonte>

## NOTE FONTI
- <fonte 1>
- <fonte 2>
```

---

## 6. Esempio completo (corpo della pagina)

```markdown
Il MoMA nomina Makeda Best a capo del dipartimento di Fotografia a partire da settembre 2026, dopo quasi quattro anni di vacanza del ruolo: una scelta che segnala un cambio di rotta verso una fotografia intesa come strumento civile.

## Un cambio della guardia annunciato
L'annuncio, formalizzato dal direttore Christophe Cherix, chiude una lunga transizione. Best arriva dall'Oakland Museum of California e porta con sé una formazione che unisce pratica artistica e rigore storiografico.

## La fotografia come strumento civico
Nella visione di Best, l'immagine non è un oggetto estetico ma uno strumento di *visual literacy* per leggere le dinamiche di potere del presente.

> La fotografia smette di essere un'isola estetica e diventa il tessuto connettivo del museo.

## Cosa aspettarsi
La sfida è trasformare una collezione di 35.000 opere in una piattaforma di impegno civile.

## Conclusione
Con Best, il MoMA prova a ridefinire il ruolo della fotografia tra arte e coscienza politica.

## SEO
- Titolo SEO: Makeda Best, nuova Chief Curator di Fotografia al MoMA
- Meta description: Il MoMA nomina Makeda Best a capo della Fotografia da settembre 2026: una visione legata a giustizia sociale e revisione del canone.
- Slug URL: makeda-best-moma-fotografia-curatrice
- Parole chiave: MoMA, Makeda Best, curatela fotografica, fotografia contemporanea

## SOCIAL
### Instagram
Una svolta per il MoMA…
### LinkedIn
Il MoMA annuncia la nomina di Makeda Best…
### X
Makeda Best è la nuova guida della fotografia al MoMA.

## IMMAGINI
- Ritratto ufficiale di Makeda Best (credit: MoMA)
- Veduta della mostra "Devour the Land" (Harvard Art Museums)

## NOTE FONTI
- The Art Newspaper, "MoMA appoints Makeda Best", giugno 2026
```

---

## 7. Checklist finale (prima di spuntare `Pubblica`)

- [ ] `Notizia`, `Categoria`, `Di cosa parla`, `Fonte`, `Data` compilati.
- [ ] Corpo: **niente titolo ripetuto**; primo blocco è un **paragrafo** d'attacco.
- [ ] Sezioni con `##` (e `###` per le sottosezioni), nessun `#`.
- [ ] Markdown pulito: `*corsivo*`, `**grassetto**`, `[link](url)`; nessun `\*`.
- [ ] Presente `## SEO` con le **4 righe esatte** (Titolo SEO / Meta description / Slug URL / Parole chiave).
- [ ] `Slug URL` in minuscolo-con-trattini; `Parole chiave` separate da virgola.
- [ ] Solo quando tutto è ok → spunta **`Pubblica`**.
```
