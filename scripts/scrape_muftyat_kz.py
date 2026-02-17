"""
Скрипт для скрапинга Q&A с muftyat.kz (раздел Рамазан).
Собирает все вопросы и ответы со всех страниц.
Сохраняет в knowledge/muftyat_kz.json.

Использование:
    python scripts/scrape_muftyat_kz.py
"""

import json
import os
import re
import sys
import time

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://www.muftyat.kz"
CATEGORY_URL = "/kk/qa/?cid=qa-ramadan"
OUTPUT_PATH = os.path.join(os.path.dirname(__file__), "..", "knowledge", "muftyat_kz.json")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "kk,ru;q=0.9,en;q=0.8",
}

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
        url = f"{BASE_URL}{CATEGORY_URL}&page={page_num}"

    soup = get_page(url)
    if not soup:
        return []

    links = []
    for a_tag in soup.find_all("a", href=True):
        href = a_tag["href"]
        # Ссылки на конкретные вопросы в формате /kk/qa/qa-ramadan/YYYY-MM-DD/ID-slug/
        if "/kk/qa/qa-ramadan/" in href and re.search(r"/\d{4}-\d{2}-\d{2}/", href):
            title = a_tag.get_text(strip=True)
            if title and len(title) > 5:
                full_url = href if href.startswith("http") else f"{BASE_URL}{href}"
                links.append({
                    "url": full_url,
                    "title": title,
                })

    # Убираем дубликаты
    seen = set()
    unique_links = []
    for link in links:
        if link["url"] not in seen:
            seen.add(link["url"])
            unique_links.append(link)

    return unique_links


def extract_qa(url: str) -> dict | None:
    """Извлечь вопрос и ответ с конкретной страницы Q&A.

    Структура muftyat.kz:
    - Заголовок: div.row.top_content содержит заголовок (h1 или strong)
    - Ответ: div.post_content — основной блок с текстом ответа
    """
    soup = get_page(url)
    if not soup:
        return None

    # Извлекаем ID из URL
    match = re.search(r"/(\d+)-", url)
    qa_id = match.group(1) if match else ""

    # Заголовок — ищем в top_content или clearfix
    title = ""
    top_content = soup.find("div", class_="top_content")
    if top_content:
        h_tag = top_content.find(["h1", "h2", "h3"])
        if h_tag:
            title = h_tag.get_text(strip=True)
        else:
            strong = top_content.find("strong")
            if strong:
                title = strong.get_text(strip=True)

    # Фоллбэк: любой h1
    if not title:
        h1 = soup.find("h1")
        if h1:
            title = h1.get_text(strip=True)

    # Фоллбэк: title тег страницы
    if not title:
        title_tag = soup.find("title")
        if title_tag:
            title = title_tag.get_text(strip=True).split("|")[0].strip()

    # Чистим заголовок от лишнего текста (убираем " - Қазақстан мұсылмандары...")
    if title:
        for sep in [" - Қазақстан", " | ", " — Қазақстан"]:
            if sep in title:
                title = title[:title.index(sep)].strip()

    question_text = title

    # Ответ: div.post_content
    answer_text = ""
    post_content = soup.find("div", class_="post_content")

    if post_content:
        paragraphs = post_content.find_all("p")
        if paragraphs:
            texts = []
            for p in paragraphs:
                t = p.get_text(strip=True)
                if t and len(t) > 3:
                    texts.append(t)
            answer_text = "\n\n".join(texts)
        else:
            answer_text = post_content.get_text(strip=True)

    # Фоллбэк: div.clearfix
    if not answer_text:
        clearfix = soup.find("div", class_="clearfix")
        if clearfix:
            paragraphs = clearfix.find_all("p")
            if paragraphs:
                texts = []
                for p in paragraphs:
                    t = p.get_text(strip=True)
                    if t and len(t) > 3:
                        texts.append(t)
                answer_text = "\n\n".join(texts)

    # Чистим
    if answer_text:
        for noise in ["Бөлісу", "Пайдалы сілтемелер", "Ұқсас сұрақтар",
                       "Тегтер:", "Жауап берген:", "Пікір жазу"]:
            if noise in answer_text:
                idx = answer_text.index(noise)
                answer_text = answer_text[:idx].strip()

    if not question_text or not answer_text:
        return None

    if len(answer_text) > 4000:
        answer_text = answer_text[:4000] + "..."

    return {
        "id": f"muftyat_kz_{qa_id}" if qa_id else f"muftyat_kz_{hash(url) % 100000}",
        "question": question_text,
        "answer": answer_text,
        "source": "muftyat.kz",
        "source_url": url,
        "category": "oraza",
        "tags": ["ораза", "muftyat.kz", "муфтият"],
    }


def get_total_pages() -> int:
    """Определить общее количество страниц пагинации."""
    soup = get_page(f"{BASE_URL}{CATEGORY_URL}")
    if not soup:
        return 1

    max_page = 1
    for a_tag in soup.find_all("a", href=True):
        href = a_tag["href"]
        match = re.search(r"[?&]page=(\d+)", href)
        if match:
            page_num = int(match.group(1))
            max_page = max(max_page, page_num)

    return max_page


def main():
    print("=" * 60)
    print("  muftyat.kz Q&A Scraper (Ramadan section)")
    print("=" * 60)

    total_pages = get_total_pages()
    print(f"\nTotal pages found: {total_pages}")

    # Собираем все ссылки
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
