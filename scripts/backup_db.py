#!/usr/bin/env python3
"""
Скрипт резервного копирования SQLite базы данных.
Запуск: python scripts/backup_db.py
Рекомендуется добавить в cron для ежедневного бэкапа.
"""

import os
import sys
import shutil
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from config import DATABASE_PATH

BACKUP_DIR = os.path.join(os.path.dirname(DATABASE_PATH), "backups")


def main():
    if not os.path.exists(DATABASE_PATH):
        print(f"Database not found: {DATABASE_PATH}")
        sys.exit(1)

    os.makedirs(BACKUP_DIR, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_name = f"bot_backup_{timestamp}.db"
    backup_path = os.path.join(BACKUP_DIR, backup_name)

    shutil.copy2(DATABASE_PATH, backup_path)
    print(f"Backup created: {backup_path}")

    # Удаляем старые бэкапы (оставляем последние 30)
    backups = sorted(
        [f for f in os.listdir(BACKUP_DIR) if f.endswith(".db")],
        reverse=True,
    )
    for old_backup in backups[30:]:
        old_path = os.path.join(BACKUP_DIR, old_backup)
        os.remove(old_path)
        print(f"Removed old backup: {old_backup}")

    print("Done.")


if __name__ == "__main__":
    main()
