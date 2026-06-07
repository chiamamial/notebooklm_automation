# 📚 Documentazione — NotebookLM Daily Research

Automazione che ogni mattina alle **07:00 (ora italiana)** fa una ricerca con
Google NotebookLM su arte, design, grafica, UI/UX e musica, e invia un **brief
editoriale** in italiano via email.

- **Repo:** https://github.com/chiamamial/notebooklm_automation (pubblico)
- **Gira su:** VPS Ubuntu 24.04 — IP `217.160.100.63` — cartella `/opt/notebooklm`
- **Email:** via Resend → `chiamamial93@gmail.com`

---

## Indice
1. [Come funziona](#1-come-funziona)
2. [Struttura dei file](#2-struttura-dei-file)
3. [Collegarsi al server](#3-collegarsi-al-server)
4. [Comandi di tutti i giorni](#4-comandi-di-tutti-i-giorni)
5. [Cambiare l'output (temi, formato, orario)](#5-cambiare-loutput)
6. [Manutenzione della sessione Google](#6-manutenzione-della-sessione-google)
7. [Problemi comuni e soluzioni](#7-problemi-comuni-e-soluzioni)
8. [Riferimento tecnico](#8-riferimento-tecnico)
9. [Cruscotto Notion + articoli on-demand](#9-cruscotto-notion)

---

## 1. Come funziona

Ogni mattina un *timer* di sistema (systemd) avvia lo script `daily_research.py`,
che esegue in sequenza:

```
1. Verifica login a NotebookLM (sessione Google salvata su file)
2. Crea un notebook "Daily Research <data>"
3. Lancia una ricerca sul web (modalità FAST) e importa le fonti citate
4. Genera un report editoriale seguendo report_instructions.txt
5. Scarica il report in Markdown
6. Invia il report via email (Resend)
7. Cancella il notebook (per non accumulare)
```

In parallelo, un secondo timer ogni **20 minuti** fa un "refresh" leggero per
**tenere viva la sessione Google** (altrimenti scadrebbe).

> ⚙️ Tecnologia: libreria **non ufficiale** `notebooklm-py`. Non esiste un'API
> ufficiale di NotebookLM, quindi può capitare (raramente) che qualcosa si
> rompa se Google cambia qualcosa.

### Regola d'oro
La sessione Google vive **solo sul VPS**. Non usare lo stesso login altrove
(es. sul Mac) o le due copie si "litigano" i cookie e smette di funzionare.

---

## 2. Struttura dei file

Tutti i file sono nel repo e su `/opt/notebooklm` sul server.

| File | A cosa serve |
|------|--------------|
| `daily_research.py` | Lo script principale (orchestratore) |
| **`prompt.txt`** | **COSA cercare** — i temi della ricerca |
| **`report_instructions.txt`** | **COME scrivere** il brief (struttura, tono, schede) |
| `requirements.txt` | Dipendenze Python |
| `notebooklm.env` | Segreti (API key Resend). *Solo sul server, non nel repo* |
| `vps/setup.sh` | Script di installazione completa del server |
| `vps/notebooklm-research.{service,timer}` | Timer della ricerca giornaliera |
| `vps/notebooklm-keepalive.{service,timer}` | Timer del refresh sessione |

I file in **grassetto** sono quelli che modifichi per personalizzare l'output.

---

## 3. Collegarsi al server

Apri il **Terminale** sul Mac (Spotlight → "Terminale") e scrivi:

```bash
ssh root@217.160.100.63
```
Inserisci la password (non si vede mentre digiti, è normale) → `Invio`.
Quando compare `root@ubuntu:~#` sei dentro il server.

Per uscire dal server: scrivi `exit` e `Invio`.

---

## 4. Comandi di tutti i giorni

> Questi comandi si lanciano **dentro il server** (dopo esserti collegato).

### Lanciare subito una ricerca di prova
```bash
systemctl start notebooklm-research.service
```
(blocca il terminale per ~2 minuti finché non finisce)

### Vedere i log dal vivo (cosa sta facendo)
```bash
journalctl -u notebooklm-research.service -f
```
Esci dalla diretta con `Ctrl + C`.

### Vedere com'è andato l'ultimo run
```bash
journalctl -u notebooklm-research.service --since "-1 day" --no-pager | tail -30
```

### Controllare se i timer sono attivi e quando partono
```bash
systemctl list-timers 'notebooklm-*' --no-pager
```

### Vedere lo stato dei servizi
```bash
systemctl status notebooklm-research.service --no-pager
systemctl status notebooklm-keepalive.timer --no-pager
```

### Verificare che il login a NotebookLM sia valido
```bash
NOTEBOOKLM_HOME=/opt/notebooklm/nlm_home /opt/notebooklm/.venv/bin/notebooklm auth check --test
```
Deve dire **`Authentication is valid`**.

### Leggere l'ultimo report generato
```bash
cat /opt/notebooklm/report-*.md
```

---

## 5. Cambiare l'output

> Dopo ogni modifica nel repo, vanno aggiornati i file sul server (vedi sotto).

### A) Cambiare i TEMI della ricerca
Modifica `prompt.txt` (è la domanda che fa NotebookLM).

### B) Cambiare il FORMATO del brief
Modifica `report_instructions.txt` (struttura delle schede, tono, sezioni).

### C) Cambiare l'ORARIO di invio
Modifica `vps/notebooklm-research.timer`, riga `OnCalendar`. Esempio per le 08:30:
```
OnCalendar=*-*-* 08:30:00
```
Poi sul server:
```bash
cp /opt/notebooklm/vps/notebooklm-research.timer /etc/systemd/system/
systemctl daemon-reload
systemctl restart notebooklm-research.timer
```

### D) Applicare le modifiche fatte nel repo, sul server
Dopo aver modificato e fatto `git push` dal Mac, sul server:
```bash
cd /opt/notebooklm && git pull
```
(`prompt.txt` e `report_instructions.txt` hanno effetto subito al run successivo)

### Modalità ricerca
È fissata su **`fast`** apposta: `deep` si impalla e va in timeout. Non cambiarla.
Si trova in `/opt/notebooklm/notebooklm.env` → `RESEARCH_MODE=fast`.

---

## 6. Manutenzione della sessione Google

La sessione (i cookie di Google) di solito si mantiene viva da sola grazie al
keepalive. Ma se un giorno smette di funzionare con un errore tipo
*"Authentication expired"*, va rifatto il login. Procedura:

**Sul Mac:**
```bash
# 1. rifai il login (si apre il browser, accedi a Google)
notebooklm login

# 2. copia il file della sessione sul server
scp ~/.notebooklm/profiles/default/storage_state.json \
    root@217.160.100.63:/opt/notebooklm/nlm_home/profiles/default/
```

> ⚠️ Dopo il login sul Mac, **non lanciare lo script sul Mac**: la sessione deve
> restare "di proprietà" del server.

---

## 7. Problemi comuni e soluzioni

| Sintomo | Causa probabile | Soluzione |
|---------|-----------------|-----------|
| Non arriva la mail | Login scaduto | Rifai login (sezione 6) |
| `Authentication expired` nei log | Sessione desincronizzata | Rifai login (sezione 6) |
| `timeout dopo Xs` | Ricerca lenta/bloccata | Normale ogni tanto, riparte il giorno dopo; verifica sia `fast` |
| Mail in Spam | Mittente generico Resend | Sposta in "Posta in arrivo"; o verifica un dominio su Resend |
| `FileNotFoundError: notebooklm` | (già risolto in passato) | `cd /opt/notebooklm && git pull` |

### Riavviare tutto da capo (se serve)
```bash
cd /opt/notebooklm && git pull
bash vps/setup.sh
```

---

## 8. Riferimento tecnico

### Variabili d'ambiente (`/opt/notebooklm/notebooklm.env`)
| Variabile | Valore |
|-----------|--------|
| `RESEND_API_KEY` | API key di Resend |
| `MAIL_FROM` | mittente (es. `onboarding@resend.dev`) |
| `MAIL_TO` | destinatario |
| `RESEARCH_MODE` | `fast` (NON usare `deep`) |
| `RESEARCH_TIMEOUT` | `600` (tetto secondi per fase) |
| `REPORT_LANGUAGE` | `it` |

### Percorsi sul server
```
/opt/notebooklm/                                    → progetto (git)
/opt/notebooklm/.venv/                              → ambiente Python
/opt/notebooklm/nlm_home/profiles/default/storage_state.json  → sessione Google
/etc/systemd/system/notebooklm-*.{service,timer}    → timer di sistema
```

### Accesso SSH a chiave (per assistenza)
Sul Mac esiste una chiave dedicata `~/.ssh/notebooklm_vps` autorizzata sul server
(`~/.ssh/authorized_keys`). Permette l'accesso senza password. Per revocarla,
rimuovere la riga `claude-notebooklm-vps` da quel file sul server.

### Email mittente personalizzata
Con `onboarding@resend.dev` la mail arriva solo all'indirizzo del proprio account
Resend. Per inviare ad altri indirizzi: verificare un dominio su Resend
(Domains → Add) e usare un mittente tipo `redazione@tuodominio.it` in `MAIL_FROM`.
```

---

## 9. Cruscotto Notion

Oltre all'email, ogni news del brief finisce come **riga** in un database Notion
("Kanri — Redazione"). Spuntando la casella **✅ Scrivi articolo**, il sistema genera
un articolo completo (articolo + SEO + social + immagini) e lo scrive **dentro
la pagina Notion**, mettendo poi **Stato = Fatto**.

🔗 Database: https://app.notion.com/p/234c80b5af8546f38b1b1fc866b876f1

### Flusso d'uso
```
Brief 07:00  →  righe nel database  →  spunti ✅ le news che vuoi
   →  entro ~5 min l'articolo appare nella pagina  →  Stato = Fatto
```

### Pezzi tecnici
- `notion_sync.py` — parla con l'API Notion (crea righe, legge spunte, scrive articoli)
- `notion_watcher.py` — controllore: cerca le spunte e genera gli articoli
- `notebooklm-watcher.timer` — lo lancia ogni 5 minuti
- `approfondisci.py` — genera il "kit articolo" (usato anche a mano via email)

### Generare un articolo a mano (senza Notion)
```bash
cd /opt/notebooklm && set -a && . ./notebooklm.env && set +a && \
  NOTEBOOKLM_HOME=/opt/notebooklm/nlm_home .venv/bin/python approfondisci.py "la tua news"
```

### Lanciare il controllore Notion a mano
```bash
systemctl start notebooklm-watcher.service
journalctl -u notebooklm-watcher.service -f
```

### Token Notion
Serve un'integrazione interna Notion (token `ntn_...`) salvata in `notebooklm.env`
come `NOTION_TOKEN`, e il database condiviso con quell'integrazione
(database → ••• → Connections). `NOTION_DB_ID` è l'ID del database.
