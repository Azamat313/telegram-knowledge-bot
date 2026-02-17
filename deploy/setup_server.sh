#!/bin/bash
set -euo pipefail

# ─────────────────────────────────────────────────
# Скрипт первичной настройки Ubuntu сервера
# Запуск: sudo bash deploy/setup_server.sh
# ─────────────────────────────────────────────────

APP_DIR="/opt/telegram-knowledge-bot"
APP_USER="bot"
REPO_URL="${1:-}"

echo "══════════════════════════════════════════"
echo "  Настройка сервера для Ramadan Bot"
echo "══════════════════════════════════════════"

# 1. Обновление системы
echo "[1/11] Обновление системы..."
apt update && apt upgrade -y

# 2. Установка зависимостей
echo "[2/11] Установка Python, Nginx, Certbot..."
apt install -y python3 python3-pip python3-venv nginx certbot python3-certbot-nginx git ufw

# Проверяем версию Python
PYTHON_VERSION=$(python3 --version 2>&1 | awk '{print $2}')
echo "  Python version: $PYTHON_VERSION"

# 3. Создание пользователя
echo "[3/11] Создание пользователя '$APP_USER'..."
if ! id "$APP_USER" &>/dev/null; then
    useradd -r -m -s /bin/bash "$APP_USER"
    echo "  Пользователь '$APP_USER' создан"
else
    echo "  Пользователь '$APP_USER' уже существует"
fi

# 4. Клонирование репозитория
echo "[4/11] Настройка приложения в $APP_DIR..."
if [ -n "$REPO_URL" ]; then
    if [ -d "$APP_DIR" ]; then
        echo "  Директория существует, обновляем..."
        cd "$APP_DIR" && git pull
    else
        git clone "$REPO_URL" "$APP_DIR"
    fi
else
    if [ ! -d "$APP_DIR" ]; then
        echo "  REPO_URL не указан. Скопируйте проект в $APP_DIR вручную."
        echo "  Пример: sudo bash deploy/setup_server.sh https://github.com/user/repo.git"
        mkdir -p "$APP_DIR"
    fi
fi

chown -R "$APP_USER":"$APP_USER" "$APP_DIR"

# 5. Виртуальное окружение + зависимости
echo "[5/11] Создание виртуального окружения..."
cd "$APP_DIR"
sudo -u "$APP_USER" python3 -m venv venv
sudo -u "$APP_USER" venv/bin/pip install --upgrade pip
sudo -u "$APP_USER" venv/bin/pip install -r requirements.txt

# 6. Создание необходимых директорий
echo "[6/11] Создание директорий..."
sudo -u "$APP_USER" mkdir -p logs database backups

# 7. Настройка .env
if [ ! -f "$APP_DIR/.env" ]; then
    echo "[7/11] Создание .env из .env.example..."
    sudo -u "$APP_USER" cp .env.example .env
    echo "  ВАЖНО: Отредактируйте $APP_DIR/.env и заполните все переменные!"
else
    echo "[7/11] .env уже существует, пропуск..."
fi

# 8. Копирование systemd юнитов
echo "[8/11] Установка systemd сервисов..."
cp deploy/ramadan-bot.service /etc/systemd/system/
cp deploy/ustaz-bot.service /etc/systemd/system/
cp deploy/web-admin.service /etc/systemd/system/
systemctl daemon-reload

# 9. Настройка Nginx
echo "[9/11] Настройка Nginx..."
DOMAIN=$(grep "^DOMAIN=" "$APP_DIR/.env" 2>/dev/null | cut -d'=' -f2)
if [ -z "$DOMAIN" ] || [ "$DOMAIN" = "yourdomain.com" ]; then
    echo "  Домен не настроен в .env. Укажите DOMAIN= в $APP_DIR/.env"
    echo "  Затем запустите: sudo bash deploy/setup_ssl.sh"
else
    sed "s/DOMAIN_PLACEHOLDER/$DOMAIN/g" deploy/nginx-site.conf > /etc/nginx/sites-available/ramadan-bot
    ln -sf /etc/nginx/sites-available/ramadan-bot /etc/nginx/sites-enabled/
    rm -f /etc/nginx/sites-enabled/default

    # Временно без SSL для получения сертификата
    echo "[9.1] Получение SSL сертификата..."
    # Создаём временный конфиг без SSL
    cat > /etc/nginx/sites-available/ramadan-bot-temp <<EOF
server {
    listen 80;
    server_name $DOMAIN;
    location / {
        proxy_pass http://127.0.0.1:8090;
    }
}
EOF
    ln -sf /etc/nginx/sites-available/ramadan-bot-temp /etc/nginx/sites-enabled/ramadan-bot
    nginx -t && systemctl reload nginx

    certbot --nginx -d "$DOMAIN" --non-interactive --agree-tos --email "admin@$DOMAIN" || {
        echo "  Certbot не удался. Запустите вручную: sudo certbot --nginx -d $DOMAIN"
    }

    # Восстанавливаем полный конфиг
    sed "s/DOMAIN_PLACEHOLDER/$DOMAIN/g" deploy/nginx-site.conf > /etc/nginx/sites-available/ramadan-bot
    ln -sf /etc/nginx/sites-available/ramadan-bot /etc/nginx/sites-enabled/
    nginx -t && systemctl reload nginx
fi

# 10. Настройка UFW (firewall)
echo "[10/11] Настройка файрвола..."
ufw allow OpenSSH
ufw allow 'Nginx Full'
ufw --force enable

# 11. Настройка cron для бэкапов
echo "[11/11] Настройка cron бэкапов..."
CRON_CMD="0 3 * * * cd $APP_DIR && venv/bin/python scripts/backup_db.py >> logs/backup.log 2>&1"
(crontab -u "$APP_USER" -l 2>/dev/null || true; echo "$CRON_CMD") | sort -u | crontab -u "$APP_USER" -

# Запуск сервисов
echo ""
echo "══════════════════════════════════════════"
echo "  Установка завершена!"
echo "══════════════════════════════════════════"
echo ""
echo "Следующие шаги:"
echo "1. Отредактируйте $APP_DIR/.env"
echo "2. Запустите сервисы:"
echo "   sudo systemctl enable --now ramadan-bot ustaz-bot web-admin"
echo "3. Проверьте статус:"
echo "   sudo systemctl status ramadan-bot ustaz-bot web-admin"
echo "4. Логи:"
echo "   sudo journalctl -u ramadan-bot -f"
echo "   sudo journalctl -u ustaz-bot -f"
echo "   sudo journalctl -u web-admin -f"
echo ""
