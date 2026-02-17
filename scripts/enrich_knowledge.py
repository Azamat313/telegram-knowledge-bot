"""
Скрипт для обогащения knowledge_base.json полями author, book_title, page.
Парсит поле 'source' и первые строки question/answer для извлечения информации.
"""

import json
import re
import sys

# Маппинг source → (author, book_title)
SOURCE_MAP = {
    "АҚАТАЕВ_ОРАЗА": ("Ақатаев", "Рамазан оразасы"),
}


def extract_page(text: str) -> str:
    """Извлечь номер страницы из текста."""
    # Ищем паттерны вроде "502\n\n" в начале текста
    match = re.match(r"^(\d{1,4})\s*\n", text)
    if match:
        return match.group(1)
    return ""


def enrich_entry(entry: dict) -> dict:
    """Обогатить запись полями author, book_title, page."""
    source = entry.get("source", "")

    author = ""
    book_title = ""

    if source in SOURCE_MAP:
        author, book_title = SOURCE_MAP[source]
    else:
        # Попробуем разобрать source: "АВТОР_НАЗВАНИЕ"
        parts = source.split("_", 1)
        if len(parts) == 2:
            author = parts[0].capitalize()
            book_title = parts[1].replace("_", " ").capitalize()

    page = extract_page(entry.get("question", ""))

    entry["author"] = entry.get("author") or author
    entry["book_title"] = entry.get("book_title") or book_title
    entry["page"] = entry.get("page") or page

    return entry


def main():
    if len(sys.argv) < 2:
        print("Usage: python enrich_knowledge.py <knowledge_base.json>")
        sys.exit(1)

    filepath = sys.argv[1]

    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)

    if isinstance(data, dict) and "knowledge_base" in data:
        entries = data["knowledge_base"]
    elif isinstance(data, list):
        entries = data
    else:
        print("Unknown format")
        sys.exit(1)

    enriched = 0
    for entry in entries:
        enrich_entry(entry)
        enriched += 1

    if isinstance(data, dict):
        data["knowledge_base"] = entries
    else:
        data = entries

    output_path = filepath.replace(".json", "_enriched.json")
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"Enriched {enriched} entries → {output_path}")


if __name__ == "__main__":
    main()
