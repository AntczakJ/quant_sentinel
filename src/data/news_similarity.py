"""
src/news_similarity.py — Historical News Similarity Search (FAISS)

Finds "similar news in the past" and checks how gold reacted.

Architecture:
  1. Collect historical headlines from Finnhub (stored locally)
  2. Embed each headline with sentence-transformers (all-MiniLM-L6-v2)
  3. Store embeddings in FAISS index with metadata (date, gold_price_reaction)
  4. When new headline arrives → find k-nearest neighbors → report historical reactions
  5. Generate probabilistic signal: "similar headlines led to +X% gold avg"

The model (80MB) loads lazily on first use. Embeddings cached to disk.

Usage:
    from src.data.news_similarity import find_similar_news
    result = find_similar_news("Fed holds rates steady amid inflation")
"""

import os
import time
import pickle
import datetime
import numpy as np
from typing import Optional, Dict, List
from src.core.logger import logger

_INDEX_FILE = "data/news_faiss_index.pkl"
_MODEL = None  # lazy loaded


def _get_model():
    """Lazy-load sentence-transformers model (80MB, first call ~10s)."""
    global _MODEL
    if _MODEL is None:
        try:
            from sentence_transformers import SentenceTransformer
            _MODEL = SentenceTransformer('all-MiniLM-L6-v2')
            logger.info("[FAISS] Sentence-transformer model loaded")
        except ImportError:
            logger.debug("[FAISS] sentence-transformers not installed")
            return None
    return _MODEL


def build_index_from_finnhub() -> int:
    """
    Fetch recent headlines from Finnhub, embed them, build FAISS index.
    Enriches each headline with gold price context.

    Returns number of indexed headlines.
    """
    try:
        import faiss
        from src.data.news_feed import fetch_finnhub_news

        model = _get_model()
        if model is None:
            return 0

        # Get current gold-relevant headlines
        articles = fetch_finnhub_news()
        if not articles:
            logger.debug("[FAISS] No articles to index")
            return 0

        # Load existing index if available
        existing = _load_index()
        existing_headlines = set()
        if existing:
            existing_headlines = set(e.get("headline", "") for e in existing.get("metadata", []))

        # Filter out already-indexed headlines
        new_articles = [a for a in articles if a.get("headline", "") not in existing_headlines]
        if not new_articles:
            return len(existing.get("metadata", []))

        # Embed new headlines
        new_headlines = [a["headline"] for a in new_articles]
        new_embeddings = model.encode(new_headlines, normalize_embeddings=True)

        # Build metadata
        new_metadata = []
        for a in new_articles:
            new_metadata.append({
                "headline": a["headline"],
                "source": a.get("source", ""),
                "timestamp": a.get("timestamp"),
                "score": a.get("score", 0),
                "impact": a.get("impact", "low"),
                "indexed_at": datetime.datetime.now().isoformat(),
            })

        # Merge with existing
        if existing and existing.get("embeddings") is not None:
            all_embeddings = np.vstack([existing["embeddings"], new_embeddings])
            all_metadata = existing["metadata"] + new_metadata
        else:
            all_embeddings = new_embeddings
            all_metadata = new_metadata

        # Build FAISS index
        dim = all_embeddings.shape[1]
        index = faiss.IndexFlatIP(dim)  # inner product (cosine after normalization)
        index.add(all_embeddings.astype(np.float32))

        # Save
        _save_index(all_embeddings, all_metadata, index)

        logger.info(f"[FAISS] Index built: {len(all_metadata)} headlines ({len(new_metadata)} new)")
        return len(all_metadata)

    except ImportError as e:
        logger.debug(f"[FAISS] Missing dependency: {e}")
        return 0
    except Exception as e:
        logger.warning(f"[FAISS] Index build failed: {e}")
        return 0


def find_similar_news(headline: str, k: int = 5) -> Dict:
    """
    Find k most similar historical headlines and their gold-impact scores.

    Args:
        headline: New headline to search for
        k: Number of similar headlines to return

    Returns:
        {
            "query": str,
            "matches": [
                {"headline": str, "similarity": float, "score": float, "impact": str},
                ...
            ],
            "avg_historical_score": float,  # average sentiment of similar past news
            "signal": -1|0|1,               # based on historical pattern
        }
    """
    try:
        import faiss

        model = _get_model()
        if model is None:
            return {"signal": 0, "error": "model unavailable"}

        data = _load_index()
        if not data or data.get("embeddings") is None or len(data.get("metadata", [])) == 0:
            # Try building index first
            count = build_index_from_finnhub()
            if count == 0:
                return {"signal": 0, "error": "no index available"}
            data = _load_index()
            if not data:
                return {"signal": 0, "error": "index build failed"}

        # Embed query
        query_embedding = model.encode([headline], normalize_embeddings=True)

        # Build temporary FAISS index from stored embeddings
        embeddings = data["embeddings"].astype(np.float32)
        metadata = data["metadata"]
        dim = embeddings.shape[1]
        index = faiss.IndexFlatIP(dim)
        index.add(embeddings)

        # Search
        k = min(k, len(metadata))
        distances, indices = index.search(query_embedding.astype(np.float32), k)

        matches = []
        scores = []
        for dist, idx in zip(distances[0], indices[0]):
            if idx < 0 or idx >= len(metadata):
                continue
            meta = metadata[idx]
            matches.append({
                "headline": meta["headline"],
                "similarity": round(float(dist), 3),
                "score": meta.get("score", 0),
                "impact": meta.get("impact", "low"),
                "source": meta.get("source", ""),
                "date": meta.get("timestamp", ""),
            })
            if float(dist) > 0.3:  # only count reasonably similar matches
                scores.append(meta.get("score", 0))

        avg_score = float(np.mean(scores)) if scores else 0

        # Signal from historical pattern
        if avg_score > 0.15:
            signal = -1  # similar news historically bullish for gold
        elif avg_score < -0.15:
            signal = 1   # similar news historically bearish
        else:
            signal = 0

        return {
            "query": headline[:100],
            "matches": matches,
            "avg_historical_score": round(avg_score, 3),
            "signal": signal,
            "signal_text": {-1: "bullish (similar news was bullish)", 0: "neutral",
                           1: "bearish (similar news was bearish)"}.get(signal, "neutral"),
            "matched_count": len(scores),
        }

    except ImportError:
        return {"signal": 0, "error": "faiss/sentence-transformers not installed"}
    except Exception as e:
        logger.warning(f"[FAISS] Search failed: {e}")
        return {"signal": 0, "error": str(e)}


def _load_index() -> Optional[Dict]:
    """Load FAISS index + metadata from disk."""
    try:
        if os.path.exists(_INDEX_FILE):
            with open(_INDEX_FILE, 'rb') as f:
                return pickle.load(f)
    except (FileNotFoundError, pickle.UnpicklingError, EOFError):
        pass
    return None


def _save_index(embeddings: np.ndarray, metadata: list, index):
    """Save embeddings + metadata to disk."""
    try:
        os.makedirs(os.path.dirname(_INDEX_FILE) or ".", exist_ok=True)
        with open(_INDEX_FILE, 'wb') as f:
            pickle.dump({
                "embeddings": embeddings,
                "metadata": metadata,
                "built_at": datetime.datetime.now().isoformat(),
            }, f)
    except (OSError, pickle.PicklingError) as e:
        logger.debug(f"[FAISS] Save failed: {e}")
