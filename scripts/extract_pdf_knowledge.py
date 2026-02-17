#!/usr/bin/env python3
"""
Скрипт извлечения вопросов и ответов из PDF-файлов базы знаний.
Извлекает:
1. Пары "Сұрақ/Жауап" из PDF (формат Q&A)
2. Тематические блоки из книжных PDF (по разделам/абзацам)

Запуск: python scripts/extract_pdf_knowledge.py
"""

import json
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

try:
    import pymupdf
except ImportError:
    print("pymupdf не установлен. Установите: pip install PyMuPDF")
    sys.exit(1)


# Путь к PDF-файлам
PDF_DIR = os.environ.get(
    "PDF_DIR",
    os.path.join(os.path.dirname(__file__), "..", "..", "база книг"),
)
OUTPUT_PATH = os.path.join(os.path.dirname(__file__), "..", "knowledge", "knowledge_base.json")


def extract_text_from_pdf(pdf_path: str) -> str:
    """Извлекает весь текст из PDF."""
    doc = pymupdf.open(pdf_path)
    full_text = ""
    for page in doc:
        full_text += page.get_text() + "\n"
    doc.close()
    return full_text


def parse_qa_pairs(text: str, source: str) -> list[dict]:
    """
    Извлекает пары вопрос-ответ из текста.
    Формат: "Сұрақ:" followed by "Жауап:"
    """
    pattern = r'Сұрақ:\s*(.*?)\s*Жауап:\s*(.*?)(?=Сұрақ:|$)'
    matches = re.findall(pattern, text, re.DOTALL)

    qa_pairs = []
    for question, answer in matches:
        question = clean_text(question)
        answer = clean_text(answer)

        if question and answer and len(question) > 5 and len(answer) > 10:
            qa_pairs.append({
                "question": question,
                "answer": answer,
                "source": source,
            })

    return qa_pairs


def parse_book_sections(text: str, source: str) -> list[dict]:
    """
    Извлекает тематические блоки из книжного PDF.
    Разбивает текст на параграфы и создаёт записи по разделам.
    """
    sections = []

    # Очищаем текст
    text = re.sub(r'https?://\S+', '', text)
    text = re.sub(r'[ \t]+', ' ', text)

    # Разбиваем на абзацы (двойной перевод строки)
    paragraphs = re.split(r'\n\s*\n', text)

    current_heading = ""
    current_content = []

    for para in paragraphs:
        para = para.strip()
        if not para or len(para) < 20:
            continue

        # Проверяем, является ли это заголовком (короткий, заглавные, без точки в конце)
        is_heading = (
            len(para) < 100
            and not para.endswith(".")
            and (para.isupper() or para[0].isupper())
            and "\n" not in para.strip()
        )

        if is_heading and len(para) > 5:
            # Сохраняем предыдущий раздел
            if current_heading and current_content:
                content = "\n".join(current_content)
                if len(content) > 50:
                    sections.append({
                        "question": current_heading,
                        "answer": clean_text(content),
                        "source": source,
                    })
            current_heading = clean_text(para)
            current_content = []
        else:
            current_content.append(para)

    # Сохраняем последний раздел
    if current_heading and current_content:
        content = "\n".join(current_content)
        if len(content) > 50:
            sections.append({
                "question": current_heading,
                "answer": clean_text(content),
                "source": source,
            })

    # Если не удалось разбить по заголовкам, разбиваем по абзацам
    if len(sections) < 3:
        sections = []
        chunks = split_into_chunks(text, max_chars=1500)
        for i, chunk in enumerate(chunks):
            chunk = clean_text(chunk)
            if len(chunk) > 100:
                # Берём первое предложение как "вопрос"/тему
                first_sentence = chunk.split(".")[0].strip() if "." in chunk else chunk[:80]
                sections.append({
                    "question": first_sentence,
                    "answer": chunk,
                    "source": source,
                })

    return sections


def split_into_chunks(text: str, max_chars: int = 1500) -> list[str]:
    """Разбивает текст на смысловые куски."""
    paragraphs = text.split("\n")
    chunks = []
    current_chunk = ""

    for para in paragraphs:
        para = para.strip()
        if not para:
            continue

        if len(current_chunk) + len(para) > max_chars and current_chunk:
            chunks.append(current_chunk.strip())
            current_chunk = para
        else:
            current_chunk += "\n" + para

    if current_chunk.strip():
        chunks.append(current_chunk.strip())

    return chunks


def clean_text(text: str) -> str:
    """Очистка текста от лишних пробелов, переносов и мусора."""
    # Убираем номера страниц
    text = re.sub(r'\n\d+\n', '\n', text)
    # Убираем URL
    text = re.sub(r'https?://\S+', '', text)
    # Убираем множественные пробелы
    text = re.sub(r'[ \t]+', ' ', text)
    # Убираем множественные переносы строк
    text = re.sub(r'\n\s*\n+', '\n', text)
    # Убираем пробелы в начале строк
    text = re.sub(r'\n ', '\n', text)
    # Убираем хвостовые заголовки разделов (из книги 200 сұрақ)
    section_headers = [
        "Рамазан оразасына қатысты",
        "Оразаға ниет",
        "Сәресіге қатысты",
        "Оразаны бұзатын және бұзбайтын жағдайлар",
        "Оразаға қатысты әртүрлі мәселелер",
        "Жолаушы және науқас адамдардың оразасы",
        "Әйел кісілерге тән жағдайлар",
        "Тарауих намазы",
        "Қадір түні",
        "Пітір садақасы",
        "Иғтикаф",
        "Ораза айтына қатысты",
        "Шәууәл айындағы ораза",
        "Зекет",
        "Ораза кітапшасы",
    ]
    for header in section_headers:
        text = text.replace(header, "")

    return text.strip()


def determine_category(question: str, answer: str) -> str:
    """Определяет категорию вопроса по содержанию."""
    text = (question + " " + answer).lower()

    if any(w in text for w in ["ниет", "ниеттен"]):
        return "ниет"
    elif any(w in text for w in ["сәресі", "сухур", "ауыз бекіт"]):
        return "сәресі"
    elif any(w in text for w in ["бұзатын", "бұзбайтын", "бұзыл", "каффарат"]):
        return "ораза бұзу"
    elif any(w in text for w in ["қаза"]):
        return "қаза"
    elif any(w in text for w in ["жолаушы", "сапар", "жол"]):
        return "жолаушы"
    elif any(w in text for w in ["әйел", "хайыз", "нифас", "босанғаш"]):
        return "әйелдер"
    elif any(w in text for w in ["тарауих"]):
        return "тарауих"
    elif any(w in text for w in ["қадір түні", "лайлатул"]):
        return "қадір түні"
    elif any(w in text for w in ["пітір"]):
        return "пітір садақа"
    elif any(w in text for w in ["садақа"]):
        return "садақа"
    elif any(w in text for w in ["иғтикаф", "итикаф"]):
        return "иғтикаф"
    elif any(w in text for w in ["зекет", "закят"]):
        return "зекет"
    elif any(w in text for w in ["айт", "мейрам"]):
        return "ораза айт"
    elif any(w in text for w in ["шәууәл"]):
        return "шәууәл оразасы"
    elif any(w in text for w in ["ауызашар", "ауыз аш"]):
        return "ауызашар"
    elif any(w in text for w in ["намаз"]):
        return "намаз"
    elif any(w in text for w in ["рамазан"]):
        return "рамазан"
    elif any(w in text for w in ["ораза"]):
        return "ораза"
    else:
        return "жалпы"


def extract_tags(question: str, answer: str) -> list[str]:
    """Извлекает теги из вопроса и ответа."""
    tags = set()
    text = (question + " " + answer).lower()

    keyword_map = {
        "ораза": "ораза",
        "рамазан": "рамазан",
        "ниет": "ниет",
        "сәресі": "сәресі",
        "ауызашар": "ауызашар",
        "намаз": "намаз",
        "тарауих": "тарауих",
        "зекет": "зекет",
        "садақа": "садақа",
        "пітір": "пітір",
        "каффарат": "каффарат",
        "қаза": "қаза",
        "жолаушы": "жолаушы",
        "науқас": "науқас",
        "дәрі": "дәрі",
        "құрма": "құрма",
        "құран": "құран",
        "хадис": "хадис",
        "дұға": "дұға",
        "иғтикаф": "иғтикаф",
        "қадір": "қадір түні",
        "әйел": "әйелдер",
        "жүкті": "жүкті",
        "бала": "бала",
        "шайтан": "шайтан",
        "нәпсі": "нәпсі",
        "тәубе": "тәубе",
        "сабыр": "сабыр",
    }

    for keyword, tag in keyword_map.items():
        if keyword in text:
            tags.add(tag)

    return list(tags)


def process_all_pdfs():
    """Обрабатывает все PDF-файлы и создаёт единую базу знаний."""
    pdf_dir = os.path.abspath(PDF_DIR)
    print(f"PDF directory: {pdf_dir}")

    if not os.path.exists(pdf_dir):
        print(f"Directory not found: {pdf_dir}")
        sys.exit(1)

    pdf_files = [f for f in os.listdir(pdf_dir) if f.endswith(".pdf")]
    print(f"Found {len(pdf_files)} PDF files")

    all_qa = []
    qa_id = 1

    for pdf_file in sorted(pdf_files):
        pdf_path = os.path.join(pdf_dir, pdf_file)
        source_name = os.path.splitext(pdf_file)[0]
        print(f"\nProcessing: {pdf_file}...")

        text = extract_text_from_pdf(pdf_path)

        # Сначала пробуем извлечь Q&A пары
        qa_pairs = parse_qa_pairs(text, source_name)
        print(f"  Q&A pairs found: {len(qa_pairs)}")

        # Если Q&A мало, извлекаем тематические блоки из книги
        if len(qa_pairs) < 5:
            book_sections = parse_book_sections(text, source_name)
            print(f"  Book sections found: {len(book_sections)}")
            qa_pairs.extend(book_sections)

        print(f"  Total entries: {len(qa_pairs)}")

        for qa in qa_pairs:
            # Фильтрация мусорных записей
            q = qa["question"]
            a = qa["answer"]
            if len(q) < 10 or len(a) < 30:
                continue
            # Пропускаем записи, состоящие из повторяющихся URL/слов
            if re.search(r'(WWW\.|\.KZ|\.COM)', a.upper()) and a.upper().count("WWW") > 3:
                continue
            # Пропускаем ISBN, библиографические данные
            if "ISBN" in a or "ББК" in q or "УДК" in q:
                continue
            # Пропускаем записи с арабским текстом в вопросе (мусор из PDF)
            if re.search(r'[\u0600-\u06FF\uFE70-\uFEFF]', q):
                continue
            # Пропускаем записи, где вопрос начинается с цифр (номера страниц)
            if re.match(r'^\d{1,3}\s', q):
                continue

            category = determine_category(q, a)
            tags = extract_tags(q, a)

            entry = {
                "id": f"{qa_id:03d}",
                "question": q,
                "answer": a,
                "category": category,
                "tags": tags,
                "alt_questions": [],
                "source": qa["source"],
            }
            all_qa.append(entry)
            qa_id += 1

    # Удаляем пример базы знаний (sample) если он есть
    sample_path = os.path.join(os.path.dirname(OUTPUT_PATH), "sample_knowledge.json")
    if os.path.exists(sample_path):
        os.remove(sample_path)
        print(f"\nRemoved sample knowledge: {sample_path}")

    # Сохраняем JSON
    output_dir = os.path.dirname(OUTPUT_PATH)
    os.makedirs(output_dir, exist_ok=True)

    knowledge = {"knowledge_base": all_qa}
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(knowledge, f, ensure_ascii=False, indent=2)

    print(f"\n{'='*50}")
    print(f"Total entries extracted: {len(all_qa)}")
    print(f"Saved to: {OUTPUT_PATH}")

    # Статистика по категориям
    categories = {}
    for qa in all_qa:
        cat = qa["category"]
        categories[cat] = categories.get(cat, 0) + 1

    print("\nCategories:")
    for cat, count in sorted(categories.items(), key=lambda x: -x[1]):
        print(f"  {cat}: {count}")

    # Статистика по источникам
    sources = {}
    for qa in all_qa:
        src = qa.get("source", "unknown")
        sources[src] = sources.get(src, 0) + 1

    print("\nSources:")
    for src, count in sorted(sources.items(), key=lambda x: -x[1]):
        print(f"  {src}: {count}")


if __name__ == "__main__":
    process_all_pdfs()
