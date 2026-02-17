"""
Пересоздание базы знаний: PDF -> текстовые чанки -> JSON.
Нарезает PDF на смысловые абзацы (300-800 слов),
с перекрытием для лучшего поиска контекста.
"""

import json
import os
import re
import sys
from pathlib import Path

import fitz  # PyMuPDF

# Путь к PDF
PDF_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "база книг")
OUTPUT_FILE = os.path.join(os.path.dirname(__file__), "..", "knowledge", "knowledge_base.json")

CHUNK_SIZE = 500       # целевое кол-во слов в чанке
CHUNK_OVERLAP = 100    # слов перекрытия между чанками
MIN_CHUNK_SIZE = 50    # минимальное кол-во слов


def extract_text_from_pdf(pdf_path: str) -> str:
    """Извлекает весь текст из PDF."""
    doc = fitz.open(pdf_path)
    pages = []
    for page in doc:
        text = page.get_text("text")
        if text.strip():
            pages.append(text.strip())
    doc.close()
    return "\n\n".join(pages)


def clean_text(text: str) -> str:
    """Очистка текста от мусора."""
    # Убираем множественные пробелы
    text = re.sub(r'[ \t]+', ' ', text)
    # Убираем множественные переносы строк (больше 2)
    text = re.sub(r'\n{3,}', '\n\n', text)
    # Убираем номера страниц (число на отдельной строке)
    text = re.sub(r'\n\d{1,3}\n', '\n', text)
    return text.strip()


def split_into_chunks(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    """
    Нарезает текст на чанки по абзацам.
    Старается не разрывать абзацы, но при необходимости режет по словам.
    """
    # Разбиваем на абзацы
    paragraphs = re.split(r'\n\s*\n', text)
    paragraphs = [p.strip() for p in paragraphs if p.strip()]

    chunks = []
    current_chunk = []
    current_word_count = 0

    for para in paragraphs:
        para_words = para.split()
        para_word_count = len(para_words)

        # Если текущий абзац слишком длинный, разбиваем его на части
        if para_word_count > chunk_size:
            # Сначала сохраняем текущий чанк
            if current_chunk:
                chunk_text = "\n\n".join(current_chunk)
                if len(chunk_text.split()) >= MIN_CHUNK_SIZE:
                    chunks.append(chunk_text)
                current_chunk = []
                current_word_count = 0

            # Разбиваем длинный абзац на подчанки
            words = para_words
            for i in range(0, len(words), chunk_size - overlap):
                sub_chunk = " ".join(words[i:i + chunk_size])
                if len(sub_chunk.split()) >= MIN_CHUNK_SIZE:
                    chunks.append(sub_chunk)
            continue

        # Если добавление абзаца превысит лимит, сохраняем текущий чанк
        if current_word_count + para_word_count > chunk_size and current_chunk:
            chunk_text = "\n\n".join(current_chunk)
            if len(chunk_text.split()) >= MIN_CHUNK_SIZE:
                chunks.append(chunk_text)

            # Оставляем перекрытие (последний абзац)
            if overlap > 0 and len(current_chunk) > 1:
                last_para = current_chunk[-1]
                current_chunk = [last_para]
                current_word_count = len(last_para.split())
            else:
                current_chunk = []
                current_word_count = 0

        current_chunk.append(para)
        current_word_count += para_word_count

    # Последний чанк
    if current_chunk:
        chunk_text = "\n\n".join(current_chunk)
        if len(chunk_text.split()) >= MIN_CHUNK_SIZE:
            chunks.append(chunk_text)

    return chunks


def main():
    pdf_dir = Path(PDF_DIR).resolve()
    if not pdf_dir.exists():
        print(f"PDF directory not found: {pdf_dir}")
        sys.exit(1)

    pdf_files = sorted(pdf_dir.glob("*.pdf"))
    if not pdf_files:
        print(f"No PDF files found in {pdf_dir}")
        sys.exit(1)

    print(f"Found {len(pdf_files)} PDF files in {pdf_dir}")

    all_entries = []
    entry_id = 0

    for pdf_file in pdf_files:
        source_name = pdf_file.stem.replace(" ", "_")
        print(f"\nProcessing: {pdf_file.name}")

        # Извлечение текста
        raw_text = extract_text_from_pdf(str(pdf_file))
        cleaned_text = clean_text(raw_text)
        word_count = len(cleaned_text.split())
        print(f"  Extracted: {word_count} words")

        # Нарезка на чанки
        chunks = split_into_chunks(cleaned_text)
        print(f"  Chunks: {len(chunks)}")

        for i, chunk in enumerate(chunks):
            # Первые 80 символов как "вопрос" для эмбеддинга
            # Полный текст чанка как "ответ" (контекст для AI)
            first_line = chunk.split('\n')[0][:200].strip()

            entry = {
                "id": f"kb_{entry_id:04d}",
                "question": chunk,   # весь чанк для эмбеддинга
                "answer": chunk,     # весь чанк как контекст
                "source": source_name,
                "category": "ramadan",
                "chunk_index": i,
                "tags": [],
            }
            all_entries.append(entry)
            entry_id += 1

    # Сохранение
    output_path = Path(OUTPUT_FILE).resolve()
    os.makedirs(output_path.parent, exist_ok=True)

    knowledge = {"knowledge_base": all_entries}
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(knowledge, f, ensure_ascii=False, indent=2)

    print(f"\nDone! {len(all_entries)} chunks saved to {output_path}")

    # Статистика по источникам
    from collections import Counter
    source_counts = Counter(e["source"] for e in all_entries)
    print("\nChunks per source:")
    for source, count in source_counts.most_common():
        print(f"  {source}: {count}")


if __name__ == "__main__":
    main()
