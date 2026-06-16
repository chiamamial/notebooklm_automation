#!/usr/bin/env bash
# Setup completo del VPS (Ubuntu/Debian). Esegui come root:
#   bash setup.sh
set -euo pipefail

APP_DIR=/opt/notebooklm
REPO=https://github.com/chiamamial/notebooklm_automation.git

echo "== 1. Pacchetti di sistema =="
apt-get update -y
apt-get install -y python3-venv python3-pip git ffmpeg

echo "== 2. Repo in $APP_DIR =="
if [ ! -d "$APP_DIR/.git" ]; then
  git clone "$REPO" "$APP_DIR"
else
  git -C "$APP_DIR" pull --ff-only
fi
cd "$APP_DIR"

echo "== 3. Virtualenv + dipendenze =="
python3 -m venv .venv
.venv/bin/pip install -U pip
.venv/bin/pip install -r requirements.txt

echo "== 4. Cartelle sessione =="
mkdir -p "$APP_DIR/nlm_home/profiles/default"

echo "== 5. File env (segreti) =="
if [ ! -f "$APP_DIR/notebooklm.env" ]; then
  cp vps/notebooklm.env.example notebooklm.env
  echo "  -> Creato $APP_DIR/notebooklm.env : MODIFICALO con la tua RESEND_API_KEY"
fi

echo "== 6. Timer systemd =="
cp vps/notebooklm-*.service vps/notebooklm-*.timer /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now notebooklm-keepalive.timer
systemctl enable --now notebooklm-research.timer
systemctl enable --now notebooklm-watcher.timer
systemctl enable --now notebooklm-podcast.timer
systemctl enable --now notebooklm-trigger.service

echo
echo "== FATTO =="
echo "Restano DUE cose manuali:"
echo "  A) Modifica $APP_DIR/notebooklm.env con la RESEND_API_KEY"
echo "  B) Copia il file della sessione dal Mac in:"
echo "     $APP_DIR/nlm_home/profiles/default/storage_state.json"
echo
echo "Poi verifica:  cd $APP_DIR && NOTEBOOKLM_HOME=$APP_DIR/nlm_home .venv/bin/notebooklm auth check --test"
