"""
Поисковый и кэш-движок: sentence-transformers + ChromaDB.
Две коллекции:
  - knowledge_base: извлечённые Q&A из PDF (для поиска контекста)
  - ai_cache: кэш ИИ-ответов (для экономии)
"""

import asyncio
import os
import time
from typing import Optional

import chromadb
from chromadb.config import Settings
from sentence_transformers import SentenceTransformer
from loguru import logger

from config import EMBEDDING_MODEL, CHROMA_PATH, CACHE_THRESHOLD, SIMILARITY_THRESHOLD


class SearchEngine:
    def __init__(
        self,
        model_name: str = EMBEDDING_MODEL,
        chroma_path: str = CHROMA_PATH,
        cache_threshold: float = CACHE_THRESHOLD,
    ):
        self.cache_threshold = cache_threshold
        self.model_name = model_name
        self.chroma_path = chroma_path
        self._model: Optional[SentenceTransformer] = None
        self._client: Optional[chromadb.ClientAPI] = None
        self._kb_collection = None
        self._cache_collection = None

    def init(self):
        """Инициализация модели и ChromaDB."""
        logger.info(f"Loading embedding model: {self.model_name}...")
        self._model = SentenceTransformer(self.model_name)
        logger.info("Embedding model loaded")

        os.makedirs(self.chroma_path, exist_ok=True)
        self._client = chromadb.PersistentClient(
            path=self.chroma_path,
            settings=Settings(anonymized_telemetry=False),
        )

        # Коллекция базы знаний
        self._kb_collection = self._client.get_or_create_collection(
            name="knowledge_base",
            metadata={"hnsw:space": "cosine"},
        )

        # Коллекция кэша ИИ-ответов
        self._cache_collection = self._client.get_or_create_collection(
            name="ai_cache",
            metadata={"hnsw:space": "cosine"},
        )

        kb_count = self._kb_collection.count()
        cache_count = self._cache_collection.count()
        logger.info(f"ChromaDB: {kb_count} knowledge docs, {cache_count} cached answers")

    def get_collection_count(self) -> int:
        if self._kb_collection is None:
            return 0
        return self._kb_collection.count()

    def get_cache_count(self) -> int:
        if self._cache_collection is None:
            return 0
        return self._cache_collection.count()

    # ==================== Knowledge Base ====================

    def add_documents(self, ids, documents, metadatas):
        """Добавить документы в базу знаний."""
        if not ids:
            return
        embeddings = self._model.encode(documents, show_progress_bar=False).tolist()
        self._kb_collection.upsert(
            ids=ids, embeddings=embeddings, documents=documents, metadatas=metadatas,
        )

    def _sync_search_context(self, query: str, n_results: int = 5) -> list[dict]:
        """
        Поиск релевантного контекста в базе знаний (для отправки в ИИ).
        Возвращает топ-N результатов ВСЕГДА (без порога), чтобы ИИ сам решил.
        """
        if self._kb_collection is None or self._kb_collection.count() == 0:
            return []

        embedding = self._model.encode([query], show_progress_bar=False).tolist()
        results = self._kb_collection.query(
            query_embeddings=embedding,
            n_results=n_results,
            include=["documents", "metadatas", "distances"],
        )

        if not results["ids"] or not results["ids"][0]:
            return []

        output = []
        seen_ids = set()
        for i in range(len(results["ids"][0])):
            distance = results["distances"][0][i]
            similarity = 1.0 - distance
            metadata = results["metadatas"][0][i]
            kid = metadata.get("knowledge_id", results["ids"][0][i])

            if kid in seen_ids:
                continue
            seen_ids.add(kid)

            output.append({
                "question": results["documents"][0][i],
                "answer": metadata.get("answer", ""),
                "similarity": similarity,
                "source": metadata.get("source", ""),
                "category": metadata.get("category", ""),
            })

        return output

    async def search_context(self, query: str, n_results: int = 5) -> list[dict]:
        return await asyncio.to_thread(self._sync_search_context, query, n_results)

    # ==================== AI Cache ====================

    def _sync_search_cache(self, question: str) -> Optional[dict]:
        """Ищет похожий вопрос в кэше ИИ-ответов."""
        if self._cache_collection is None or self._cache_collection.count() == 0:
            return None

        embedding = self._model.encode([question], show_progress_bar=False).tolist()
        results = self._cache_collection.query(
            query_embeddings=embedding,
            n_results=1,
            include=["documents", "metadatas", "distances"],
        )

        if not results["ids"] or not results["ids"][0]:
            return None

        distance = results["distances"][0][0]
        similarity = 1.0 - distance

        if similarity < self.cache_threshold:
            return None

        metadata = results["metadatas"][0][0]
        logger.info(f"Cache hit! similarity={similarity:.4f}")

        return {
            "answer": metadata.get("answer", ""),
            "sources": metadata.get("sources", ""),
            "cached_question": results["documents"][0][0],
            "similarity": similarity,
            "from_cache": True,
        }

    async def search_cache(self, question: str) -> Optional[dict]:
        return await asyncio.to_thread(self._sync_search_cache, question)

    def _sync_cache_answer(self, question: str, answer: str, sources: str = ""):
        """Сохраняет ИИ-ответ в кэш."""
        if self._cache_collection is None or not answer:
            return
        doc_id = f"cache_{int(time.time() * 1000)}"
        embedding = self._model.encode([question], show_progress_bar=False).tolist()
        self._cache_collection.upsert(
            ids=[doc_id],
            embeddings=embedding,
            documents=[question],
            metadatas=[{"answer": answer, "sources": sources, "cached_at": str(int(time.time()))}],
        )
        logger.info(f"Cached answer for: '{question[:50]}...'")

    async def cache_answer(self, question: str, answer: str, sources: str = ""):
        return await asyncio.to_thread(self._sync_cache_answer, question, answer, sources)

    def clear_cache(self):
        """Очистка кэша ИИ-ответов."""
        if self._client:
            try:
                self._client.delete_collection("ai_cache")
            except Exception:
                pass
            self._cache_collection = self._client.get_or_create_collection(
                name="ai_cache", metadata={"hnsw:space": "cosine"},
            )
            logger.info("AI cache cleared")

    def reset_knowledge(self):
        """Сброс базы знаний (для перезагрузки)."""
        if self._client:
            try:
                self._client.delete_collection("knowledge_base")
            except Exception:
                pass
            self._kb_collection = self._client.get_or_create_collection(
                name="knowledge_base", metadata={"hnsw:space": "cosine"},
            )


# Alias
CacheEngine = SearchEngine
