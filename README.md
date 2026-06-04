# Daily NotebookLM Research → Email

Automazione che ogni giorno esegue una **deep research con Google NotebookLM**,
genera un report e te lo manda via **email**. Gira su **GitHub Actions** (cloud).

Usa la libreria non ufficiale [`notebooklm-py`](https://github.com/teng-lin/notebooklm-py):
il login a Google si fa **una volta sola** in locale, poi tutto gira via HTTP
sul cloud usando i cookie salvati.

## Come funziona

`daily_research.py` esegue in sequenza:
1. crea un notebook `Daily Research <data>`
2. lancia una web research (modalità `deep`) e importa le fonti citate
3. genera un report *briefing-doc* e lo scarica in Markdown
4. invia il report via email (Resend API)
5. cancella il notebook (per non accumulare; disattiva con `KEEP_NOTEBOOK=1`)

La domanda fissa è in [`prompt.txt`](prompt.txt) (oppure via env `RESEARCH_QUERY`).

---

## Setup (una tantum)

### 1. Login NotebookLM (già fatto in locale)
```bash
notebooklm login                  # apre il browser, accedi a Google
notebooklm auth check --test      # deve dire status: ok
```
Questo crea `~/.notebooklm/profiles/default/storage_state.json`.

### 2. Crea il repo su GitHub e carica questi file
```bash
cd ~/Desktop/notebooklm
git init && git add . && git commit -m "Daily NotebookLM research"
gh repo create notebooklm-daily --private --source=. --push
```
> `.gitignore` esclude già `storage_state.json` e i report: **non finiscono nel repo**.

### 3. Imposta i GitHub Secrets
Vai su **Settings → Secrets and variables → Actions → New repository secret**
e crea:

| Secret | Valore |
|--------|--------|
| `NOTEBOOKLM_AUTH_JSON` | il **contenuto** di `storage_state.json` (vedi sotto) |
| `RESEND_API_KEY` | la API key di Resend (https://resend.com/api-keys) |
| `MAIL_FROM` | mittente. In test usa `onboarding@resend.dev`; con dominio verificato, es. `research@tuodominio.it` |
| `MAIL_TO` | destinatario (es. chiamamial93@gmail.com) |

**Copia il contenuto dell'auth negli appunti** (macOS):
```bash
cat ~/.notebooklm/profiles/default/storage_state.json | pbcopy
```
Poi incollalo nel secret `NOTEBOOKLM_AUTH_JSON`.

**Resend** (https://resend.com):
1. crea un account gratuito (3.000 email/mese gratis)
2. **API Keys → Create** → copia la key in `RESEND_API_KEY`
3. Mittente:
   - **per provare subito** usa `MAIL_FROM=onboarding@resend.dev` — funziona
     SOLO verso l'email con cui ti sei registrato su Resend
   - **per inviare a qualsiasi indirizzo** verifica un tuo dominio in Resend
     (Domains → Add) e usa un indirizzo tipo `research@tuodominio.it`

### 4. Fatto
Il workflow [`daily-research.yml`](.github/workflows/daily-research.yml) gira ogni
giorno alle **06:30 UTC**. Puoi anche lanciarlo a mano da **Actions →
Daily NotebookLM Research → Run workflow** per provarlo subito.

---

## ⚠️ Il limite onesto: scadenza della sessione

I cookie di Google **non durano per sempre** e Google ruota il token di sessione
con tempi suoi. La libreria tiene la sessione "calda", ma su GitHub Actions un job
giornaliero da solo non basta. Per questo c'è
[`keepalive.yml`](.github/workflows/keepalive.yml) che fa un refresh leggero
ogni ~15 min.

Resta un rischio reale: il cron di GitHub Actions è impreciso e gli IP del cloud
potrebbero far scadere la sessione prima. Se noti che si rompe, hai due opzioni:

**A) Keepalive sul Mac (più affidabile)** — fai girare il refresh sul tuo computer
con `launchd` (puntuale, ogni 20 min). Crea
`~/Library/LaunchAgents/com.notebooklm.refresh.plist`:
```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.notebooklm.refresh</string>
  <key>ProgramArguments</key>
  <array>
    <string>/Users/alessandromazzola/.local/bin/notebooklm</string>
    <string>auth</string><string>refresh</string>
  </array>
  <key>StartInterval</key><integer>1200</integer>
  <key>RunAtLoad</key><true/>
</dict></plist>
```
poi: `launchctl load ~/Library/LaunchAgents/com.notebooklm.refresh.plist`
> Nota: in questo caso il refresh aggiorna il file locale; vai ricaricato come
> secret quando rifai login. Per il keepalive puro va bene anche solo cloud.

**B) Re-login a mano quando scade** — rilancia `notebooklm login`, poi riaggiorna
il secret `NOTEBOOKLM_AUTH_JSON` con il nuovo `storage_state.json`.

> È una libreria **non ufficiale**: può rompersi se Google cambia qualcosa.
> Non è "metti e dimentica per sempre", ma per uso personale regge bene.

---

## Provarlo in locale
```bash
RESEARCH_MODE=fast python3 daily_research.py     # senza email: stampa il report
# con email:
RESEND_API_KEY=re_xxx MAIL_FROM=onboarding@resend.dev MAIL_TO=tua@mail.it \
  python3 daily_research.py
```
