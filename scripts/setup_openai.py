#!/usr/bin/env python3
"""
Скрипт для загрузки PDF-файлов в OpenAI Vector Store.
Создаёт Vector Store, загружает все PDF, выводит ID для .env.

Запуск: python scripts/setup_openai.py
"""

import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

from openai import OpenAI

PDF_DIR = os.environ.get(
    "PDF_DIR",
    os.path.join(os.path.dirname(__file__), "..", "..", "база книг"),
)

VECTOR_STORE_NAME = "Ramadan Knowledge Base"


def main():
    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        print("OPENAI_API_KEY не установлен! Добавьте его в .env файл.")
        sys.exit(1)

    client = OpenAI(api_key=api_key)

    pdf_dir = os.path.abspath(PDF_DIR)
    print(f"PDF directory: {pdf_dir}")

    if not os.path.exists(pdf_dir):
        print(f"Directory not found: {pdf_dir}")
        sys.exit(1)

    pdf_files = [f for f in os.listdir(pdf_dir) if f.lower().endswith(".pdf")]
    if not pdf_files:
        print("No PDF files found!")
        sys.exit(1)

    print(f"Found {len(pdf_files)} PDF files:")
    for f in pdf_files:
        size_mb = os.path.getsize(os.path.join(pdf_dir, f)) / (1024 * 1024)
        print(f"  {f} ({size_mb:.1f} MB)")

    # Проверяем, существует ли уже Vector Store
    existing_id = os.environ.get("VECTOR_STORE_ID", "")
    if existing_id:
        print(f"\nExisting VECTOR_STORE_ID found: {existing_id}")
        try:
            vs = client.vector_stores.retrieve(existing_id)
            print(f"  Name: {vs.name}, Files: {vs.file_counts.completed}")
            answer = input("Delete and recreate? (y/N): ").strip().lower()
            if answer == "y":
                client.vector_stores.delete(existing_id)
                print("  Deleted.")
            else:
                print("Keeping existing store. Done.")
                return
        except Exception:
            print("  Store not found, creating new one.")

    # Создаём Vector Store
    print(f"\nCreating Vector Store: '{VECTOR_STORE_NAME}'...")
    vector_store = client.vector_stores.create(name=VECTOR_STORE_NAME)
    vs_id = vector_store.id
    print(f"  Created: {vs_id}")

    # Загружаем PDF файлы
    print(f"\nUploading {len(pdf_files)} files...")
    uploaded = 0
    failed = 0

    for pdf_file in sorted(pdf_files):
        pdf_path = os.path.join(pdf_dir, pdf_file)
        print(f"  Uploading: {pdf_file}...", end=" ", flush=True)

        try:
            with open(pdf_path, "rb") as f:
                file_response = client.files.create(file=f, purpose="assistants")

            client.vector_stores.files.create(
                vector_store_id=vs_id,
                file_id=file_response.id,
            )
            uploaded += 1
            print("OK")
        except Exception as e:
            failed += 1
            print(f"FAILED: {e}")

    # Ждём пока все файлы будут обработаны
    print("\nWaiting for file processing...")
    for _ in range(60):
        vs = client.vector_stores.retrieve(vs_id)
        completed = vs.file_counts.completed
        in_progress = vs.file_counts.in_progress
        print(f"  Completed: {completed}, In progress: {in_progress}")
        if in_progress == 0:
            break
        time.sleep(5)

    # Результат
    vs = client.vector_stores.retrieve(vs_id)
    print(f"\n{'='*50}")
    print(f"Vector Store ID: {vs_id}")
    print(f"Name: {vs.name}")
    print(f"Files completed: {vs.file_counts.completed}")
    print(f"Files failed: {vs.file_counts.failed}")
    print(f"Status: {vs.status}")
    print(f"\nДобавьте в .env файл:")
    print(f"VECTOR_STORE_ID={vs_id}")

    # Автоматически обновляем .env
    env_path = os.path.join(os.path.dirname(__file__), "..", ".env")
    if os.path.exists(env_path):
        with open(env_path, "r", encoding="utf-8") as f:
            content = f.read()

        if "VECTOR_STORE_ID=" in content:
            lines = content.split("\n")
            for i, line in enumerate(lines):
                if line.startswith("VECTOR_STORE_ID="):
                    lines[i] = f"VECTOR_STORE_ID={vs_id}"
            content = "\n".join(lines)
        else:
            content += f"\nVECTOR_STORE_ID={vs_id}\n"

        with open(env_path, "w", encoding="utf-8") as f:
            f.write(content)
        print(f"\n.env файл обновлён автоматически!")
    else:
        # Создаём .env
        with open(env_path, "w", encoding="utf-8") as f:
            f.write(f"OPENAI_API_KEY={os.environ.get('OPENAI_API_KEY', '')}\n")
            f.write(f"VECTOR_STORE_ID={vs_id}\n")
        print(f"\n.env файл создан!")


if __name__ == "__main__":
    main()
