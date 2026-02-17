"""
Загрузчик базы знаний из JSON-файлов в ChromaDB.
Поддерживает alt_questions — альтернативные формулировки вопросов.
Поддерживает поля author, book_title, page для источников.
"""

import json
import os
from pathlib import Path

from loguru import logger

from config import KNOWLEDGE_DIR
from core.search_engine import SearchEngine


def load_knowledge_from_file(filepath: str) -> list[dict]:
    """Загрузить записи из одного JSON-файла."""
    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)

    # Поддержка формата {"knowledge_base": [...]} и просто [...]
    if isinstance(data, dict) and "knowledge_base" in data:
        return data["knowledge_base"]
    elif isinstance(data, list):
        return data
    else:
        logger.warning(f"Unknown format in {filepath}")
        return []


def load_all_knowledge(
    search_engine: SearchEngine,
    knowledge_dir: str = KNOWLEDGE_DIR,
) -> int:
    """
    Загрузить все JSON-файлы из директории knowledge/ в ChromaDB.
    Каждый вопрос (включая alt_questions) загружается как отдельный документ,
    но все ссылаются на один и тот же ответ.

    Returns:
        Количество загруженных документов.
    """
    knowledge_path = Path(knowledge_dir)
    if not knowledge_path.exists():
        logger.warning(f"Knowledge directory not found: {knowledge_dir}")
        os.makedirs(knowledge_dir, exist_ok=True)
        return 0

    json_files = [f for f in knowledge_path.glob("*.json") if "ramadan_schedule" not in f.name]
    if not json_files:
        logger.warning(f"No JSON files found in {knowledge_dir}")
        return 0

    all_ids = []
    all_documents = []
    all_metadatas = []

    total_entries = 0

    for json_file in json_files:
        logger.info(f"Loading knowledge from: {json_file.name}")
        entries = load_knowledge_from_file(str(json_file))

        for entry in entries:
            entry_id = entry.get("id", str(total_entries))
            question = entry.get("question", "")
            answer = entry.get("answer", "")
            category = entry.get("category", "")
            tags = entry.get("tags", [])
            alt_questions = entry.get("alt_questions", [])

            if not question or not answer:
                logger.warning(f"Skipping entry {entry_id}: missing question or answer")
                continue

            source = entry.get("source", json_file.stem)
            author = entry.get("author", "")
            book_title = entry.get("book_title", "")
            page = entry.get("page", "")
            source_url = entry.get("source_url", "")

            # Основной вопрос
            doc_id = f"{entry_id}_main"
            all_ids.append(doc_id)
            all_documents.append(question)
            all_metadatas.append({
                "knowledge_id": entry_id,
                "answer": answer,
                "category": category,
                "tags": ",".join(tags) if tags else "",
                "source": source,
                "source_url": source_url,
                "author": author,
                "book_title": book_title,
                "page": str(page) if page else "",
                "is_alt": "false",
            })

            # Альтернативные формулировки
            for i, alt_q in enumerate(alt_questions):
                if not alt_q.strip():
                    continue
                alt_doc_id = f"{entry_id}_alt_{i}"
                all_ids.append(alt_doc_id)
                all_documents.append(alt_q)
                all_metadatas.append({
                    "knowledge_id": entry_id,
                    "answer": answer,
                    "category": category,
                    "tags": ",".join(tags) if tags else "",
                    "source": source,
                    "source_url": source_url,
                    "author": author,
                    "book_title": book_title,
                    "page": str(page) if page else "",
                    "is_alt": "true",
                })

            total_entries += 1

    if not all_ids:
        logger.warning("No valid entries found in knowledge files")
        return 0

    # Загружаем батчами по 100 (ограничение ChromaDB)
    batch_size = 100
    for i in range(0, len(all_ids), batch_size):
        batch_ids = all_ids[i : i + batch_size]
        batch_docs = all_documents[i : i + batch_size]
        batch_metas = all_metadatas[i : i + batch_size]
        search_engine.add_documents(batch_ids, batch_docs, batch_metas)

    logger.info(
        f"Knowledge loaded: {total_entries} entries, "
        f"{len(all_ids)} total documents (with alt_questions)"
    )
    return len(all_ids)
