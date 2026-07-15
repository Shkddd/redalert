"""Embedding 向量化 - 用于语义匹配"""
# pyarrow 19+ 兼容: datasets 库用 PyExtensionType, 新版改名 ExtensionType
try:
    import pyarrow as _pa
    if not hasattr(_pa, "PyExtensionType"):
        _pa.PyExtensionType = _pa.ExtensionType
except ImportError:
    pass

import numpy as np
from typing import List, Optional

_model = None


def _get_model():
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer
        from app.config import EMBED_MODEL
        _model = SentenceTransformer(EMBED_MODEL)
    return _model


def embed_text(text: str) -> np.ndarray:
    model = _get_model()
    return model.encode(text, normalize_embeddings=True)


def embed_texts(texts: List[str]) -> np.ndarray:
    if not texts:
        return np.array([])
    model = _get_model()
    return model.encode(texts, normalize_embeddings=True, batch_size=32, show_progress_bar=False)


def cosine_sim(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.dot(a, b))


def cosine_sim_batch(query_vec: np.ndarray, matrix: np.ndarray) -> np.ndarray:
    """query_vec vs matrix 每行的余弦相似度"""
    if matrix.size == 0:
        return np.array([])
    return matrix @ query_vec
