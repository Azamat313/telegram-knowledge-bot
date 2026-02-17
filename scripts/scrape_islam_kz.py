"""
Скрипт для скрапинга Q&A с islam.kz (раздел Ораза).
Собирает все вопросы и ответы со всех страниц пагинации.
Сохраняет в knowledge/islam_kz.json.

Использование:
    python scripts/scrape_islam_kz.py
"""

import json
import os
import re
import sys
import time

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://islam.kz"
CATEGORY_URL = "/kk/questions/qulshylyq/oraza/"
OUTPUT_PATH = os.path.join(os.path.dirname(__file__), "..", "knowledge", "islam_kz.json")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "kk,ru;q=0.9,en;q=0.8",
}

# Задержка между запросами (секунды)
REQUEST_DELAY = 1.5


def get_page(url: str) -> BeautifulSoup | None:
    """Получить страницу и вернуть BeautifulSoup объект."""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        return BeautifulSoup(resp.text, "html.parser")
    except Exception as e:
        print(f"  [ERROR] Failed to fetch {url}: {e}")
        return None


def get_question_links(page_num: int = 1) -> list[dict]:
    """Получить список ссылок на вопросы с определённой страницы пагинации."""
    if page_num == 1:
        url = f"{BASE_URL}{CATEGORY_URL}"
    else:
        url = f"{BASE_URL}{CATEGORY_URL}?page={page_num}"

    soup = get_page(url)
    if not soup:
        return []

    links = []
    # Ищем ссылки на вопросы — обычно это <a> теги в списке вопросов
    for a_tag in soup.find_all("a", href=True):
        href = a_tag["href"]
        if "/kk/questions/qulshylyq/oraza/" in href and href != CATEGORY_URL:
            # Исключаем ссылки пагинации и категории
            if "?page=" not in href and href.count("/") > 4:
                title = a_tag.get_text(strip=True)
                if title and len(title) > 10:  # Минимальная длина вопроса
                    full_url = href if href.startswith("http") else f"{BASE_URL}{href}"
                    links.append({
                        "url": full_url,
                        "title": title,
                    })

    # Убираем дубликаты по URL
    seen = set()
    unique_links = []
    for link in links:
        if link["url"] not in seen:
            seen.add(link["url"])
            unique_links.append(link)

    return unique_links


def extract_qa(url: str) -> dict | None:
    """Извлечь вопрос и ответ с конкретной страницы Q&A.

    Структура islam.kz:
    - Вопрос: div.question-body > div.text
    - Ответ: div.question-content (класс содержит "question-content")
    - Заголовок: div.article-view-block > div.box содержит заголовок
    """
    soup = get_page(url)
    if not soup:
        return None

    # Извлекаем ID из URL
    match = re.search(r"-(\d+)/$", url)
    qa_id = match.group(1) if match else ""

    # Заголовок — ищем в article-view-block или box
    title = ""
    # Пробуем найти заголовок в box блоке
    box = soup.find("div", class_="box")
    if box:
        # Заголовок обычно первый текст в box
        h_tag = box.find(["h1", "h2", "h3", "h4"])
        if h_tag:
            title = h_tag.get_text(strip=True)

    # Фоллбэк: ищем title в news-view-sub
    if not title:
        news_sub = soup.find("div", class_="news-view-sub")
        if news_sub:
            h_tag = news_sub.find(["h1", "h2", "h3", "h4"])
            if h_tag:
                title = h_tag.get_text(strip=True)

    # Фоллбэк: любой h1/h2
    if not title:
        h1 = soup.find("h1") or soup.find("h2")
        if h1:
            title = h1.get_text(strip=True)

    # Вопрос: div.question-body > div.text
    question_text = ""
    question_body = soup.find("div", class_="question-body")
    if question_body:
        text_div = question_body.find("div", class_="text")
        if text_div:
            question_text = text_div.get_text(strip=True)

    # Если вопроса нет в question-body, используем заголовок
    if not question_text:
        question_text = title

    # Ответ: div с классом содержащим "question-content"
    answer_text = ""
    content_block = soup.find("div", class_=lambda c: c and any(
        "question-content" in cls for cls in (c if isinstance(c, list) else [c])
    ))

    if content_block:
        # Извлекаем текст абзацами
        paragraphs = content_block.find_all("p")
        if paragraphs:
            texts = []
            for p in paragraphs:
                t = p.get_text(strip=True)
                if t and len(t) > 3:
                    texts.append(t)
            answer_text = "\n\n".join(texts)
        else:
            answer_text = content_block.get_text(strip=True)

    # Фоллбэк: div.news-view-sub (весь контент ответа)
    if not answer_text:
        news_view = soup.find("div", class_="news-view-sub")
        if news_view:
            paragraphs = news_view.find_all("p")
            if paragraphs:
                texts = []
                for p in paragraphs:
                    t = p.get_text(strip=True)
                    if t and len(t) > 3:
                        texts.append(t)
                answer_text = "\n\n".join(texts)

    # Чистим ответ
    if answer_text:
        # Убираем навигационные и мета-элементы
        for noise in ["Ұқсас сұрақтар", "Сілтемелер", "Пайдалы сілтемелер",
                       "Жауап берген:", "Бөлісу:", "Тегтер:", "Бөлісу"]:
            if noise in answer_text:
                idx = answer_text.index(noise)
                answer_text = answer_text[:idx].strip()

    if not question_text or not answer_text:
        return None

    # Ограничиваем длину ответа (ChromaDB metadata limit)
    if len(answer_text) > 4000:
        answer_text = answer_text[:4000] + "..."

    return {
        "id": f"islam_kz_{qa_id}" if qa_id else f"islam_kz_{hash(url) % 100000}",
        "question": question_text,
        "answer": answer_text,
        "source": "islam.kz",
        "source_url": url,
        "category": "oraza",
        "tags": ["ораза", "islam.kz"],
    }


def get_total_pages() -> int:
    """Определить общее количество страниц пагинации."""
    soup = get_page(f"{BASE_URL}{CATEGORY_URL}")
    if not soup:
        return 1

    # Ищем пагинацию
    max_page = 1
    for a_tag in soup.find_all("a", href=True):
        href = a_tag["href"]
        match = re.search(r"\?page=(\d+)", href)
        if match:
            page_num = int(match.group(1))
            max_page = max(max_page, page_num)

    return max_page


def main():
    print("=" * 60)
    print("  islam.kz Q&A Scraper (Oraza section)")
    print("=" * 60)

    total_pages = get_total_pages()
    print(f"\nTotal pages found: {total_pages}")

    # Собираем все ссылки на вопросы
    all_links = []
    for page in range(1, total_pages + 1):
        print(f"\n[Page {page}/{total_pages}] Fetching question links...")
        links = get_question_links(page)
        print(f"  Found {len(links)} questions")
        all_links.extend(links)
        time.sleep(REQUEST_DELAY)

    # Убираем дубликаты
    seen_urls = set()
    unique_links = []
    for link in all_links:
        if link["url"] not in seen_urls:
            seen_urls.add(link["url"])
            unique_links.append(link)

    print(f"\nTotal unique questions: {len(unique_links)}")

    # Скрапим каждый вопрос
    knowledge_base = []
    for i, link in enumerate(unique_links, 1):
        print(f"\n[{i}/{len(unique_links)}] Scraping: {link['title'][:60]}...")
        qa = extract_qa(link["url"])
        if qa:
            knowledge_base.append(qa)
            print(f"  OK: answer {len(qa['answer'])} chars")
        else:
            print(f"  SKIP: could not extract Q&A")
        time.sleep(REQUEST_DELAY)

    # Сохраняем
    output = {"knowledge_base": knowledge_base}
    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\n{'=' * 60}")
    print(f"  Done! Saved {len(knowledge_base)} Q&A pairs")
    print(f"  Output: {OUTPUT_PATH}")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
