#!/usr/bin/env bash
# Выкатка обновления кода бота на VPS. Запуск из корня репозитория.
# Требует настроенного ssh-доступа к серверу (или используйте pscp с Windows).
set -euo pipefail

SERVER="${SERVER:-root@87.121.47.233}"
DEST="/opt/buklbot"

echo ">> rsync bot/ -> $SERVER:$DEST/bot/"
rsync -az --delete \
  --exclude '__pycache__' \
  bot/ "$SERVER:$DEST/bot/"

echo ">> rsync requirements.txt"
rsync -az requirements.txt "$SERVER:$DEST/requirements.txt"

echo ">> pip install (если изменились зависимости) + restart"
ssh "$SERVER" "cd $DEST && ./.venv/bin/pip install -q -r requirements.txt && systemctl restart buklbot && systemctl --no-pager status buklbot | head -5"

echo ">> done"
