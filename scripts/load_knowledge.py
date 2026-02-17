#!/usr/bin/env python3
"""
Скрипт загрузки базы знаний из JSON-файлов в ChromaDB.
Запуск: python scripts/load_knowledge.py
"""

import sys
import os

# Добавляем корень проекта в путь
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from loguru import logger

from config import KNOWLEDGE_DIR, CHROMA_PATH
from core.search_engine import SearchEngine
from core.knowledge_loader import load_all_knowledge


def main():
    logger.remove()
    logger.add(sys.stderr, level="INFO")

    logger.info("=== Knowledge Base Loader ===")
    logger.info(f"Knowledge dir: {KNOWLEDGE_DIR}")
    logger.info(f"ChromaDB path: {CHROMA_PATH}")

    # Инициализация поискового движка
    engine = SearchEngine()
    engine.init()

    before_count = engine.get_collection_count()
    logger.info(f"Documents before loading: {before_count}")

    # Загрузка
    loaded = load_all_knowledge(engine)

    after_count = engine.get_collection_count()
    logger.info(f"Documents after loading: {after_count}")
    logger.info(f"Total loaded: {loaded}")
    logger.info("=== Done ===")


if __name__ == "__main__":
    main()
