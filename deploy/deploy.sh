#!/bin/bash
set -euo pipefail

# ─────────────────────────────────────────────────
# Скрипт обновления (деплой)
# Запуск: sudo bash deploy/deploy.sh
# ─────────────────────────────────────────────────

APP_DIR="/opt/telegram-knowledge-bot"
APP_USER="bot"

echo "══════════════════════════════════════════"
echo "  Обновление Ramadan Bot"
echo "══════════════════════════════════════════"

cd "$APP_DIR"

# 1. Бэкап БД перед обновлением
echo "[1/5] Бэкап базы данных..."
sudo -u "$APP_USER" venv/bin/python scripts/backup_db.py 2>/dev/null || echo "  Бэкап пропущен"

# 2. Обновление кода
echo "[2/5] git pull..."
sudo -u "$APP_USER" git pull

# 3. Обновление зависимостей
echo "[3/5] Обновление зависимостей..."
sudo -u "$APP_USER" venv/bin/pip install -r requirements.txt --quiet

# 4. Перезапуск сервисов
echo "[4/5] Перезапуск сервисов..."
systemctl restart ramadan-bot ustaz-bot web-admin

# 5. Проверка статуса
echo "[5/5] Проверка статуса..."
sleep 2

echo ""
echo "── Статус сервисов ──"
for svc in ramadan-bot ustaz-bot web-admin; do
    STATUS=$(systemctl is-active "$svc" 2>/dev/null || echo "inactive")
    if [ "$STATUS" = "active" ]; then
        echo "  ✓ $svc: $STATUS"
    else
        echo "  ✗ $svc: $STATUS"
        echo "    Логи: sudo journalctl -u $svc -n 20"
    fi
done

echo ""
echo "Обновление завершено!"
