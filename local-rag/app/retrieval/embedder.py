"""Embedding + Milvus Lite(无 sentence-transformers,直接用 transformers)"""
import threading
from typing import List
import numpy as np
import torch
from transformers import AutoTokenizer, AutoModel
from pymilvus import MilvusClient

from app.core.config import EMB_MODEL, EMB_DIM, MILVUS_PATH, BM25_TOPK


_lock = threading.Lock()
_tok = None
_model = None
_client: MilvusClient = None
_device = "cpu"


def get_model():
    """懒加载 BGE-small-zh(用 transformers 直跑,避免 sentence-transformers 依赖地狱)"""
    global _tok, _model
    if _model is None:
        with _lock:
            if _model is None:
                _tok = AutoTokenizer.from_pretrained(EMB_MODEL)
                _model = AutoModel.from_pretrained(EMB_MODEL).to(_device)
                _model.eval()
    return _tok, _model


def _last_token_pool(last_hidden_states: torch.Tensor, attention_mask: torch.Tensor) -> torch.Tensor:
    """BGE 官方推荐的 last token pooling(对 left-padded 输入取每行最后一个有效 token)"""
    left_padding = (attention_mask[:, -1].sum() == attention_mask.shape[0])
    if left_padding:
        return last_hidden_states[:, -1]
    sequence_lengths = attention_mask.sum(dim=1) - 1
    batch_size = last_hidden_states.shape[0]
    return last_hidden_states[torch.arange(batch_size, device=last_hidden_states.device), sequence_lengths]


def embed_texts(texts: List[str]) -> np.ndarray:
    """BGE last-token pooling + L2 normalize,输出 (n, dim) float32"""
    tok, model = get_model()
    encoded = tok(
        texts, padding=True, truncation=True, max_length=512, return_tensors="pt"
    ).to(_device)
    with torch.no_grad():
        out = model(**encoded)
        emb = _last_token_pool(out.last_hidden_state, encoded["attention_mask"])
        emb = torch.nn.functional.normalize(emb, p=2, dim=1)
    return emb.cpu().numpy().astype(np.float32)


def get_milvus() -> MilvusClient:
    global _client
    if _client is None:
        _client = MilvusClient(str(MILVUS_PATH))
    return _client


COLL_NAME = "rag_chunks"


def ensure_collection(reset: bool = False):
    """建/重建 collection

    reset=True: 删旧 collection 重建(用于 schema 升级)
    reset=False: 仅在不存在时建
    """
    c = get_milvus()
    if reset and c.has_collection(COLL_NAME):
        c.drop_collection(COLL_NAME)
    if not c.has_collection(COLL_NAME):
        from pymilvus import FieldSchema, CollectionSchema, DataType
        fields = [
            FieldSchema(name="id", dtype=DataType.INT64, is_primary=True, auto_id=True),
            FieldSchema(name="chunk_id", dtype=DataType.INT64),
            FieldSchema(name="vector", dtype=DataType.FLOAT_VECTOR, dim=EMB_DIM),
            FieldSchema(name="text", dtype=DataType.VARCHAR, max_length=4000),
            FieldSchema(name="document_id", dtype=DataType.INT64),
            FieldSchema(name="version_id", dtype=DataType.INT64),
            FieldSchema(name="page", dtype=DataType.VARCHAR, max_length=64),
            FieldSchema(name="category", dtype=DataType.VARCHAR, max_length=64),
            FieldSchema(name="doc_title", dtype=DataType.VARCHAR, max_length=512),
            FieldSchema(name="section_path", dtype=DataType.VARCHAR, max_length=512),
            FieldSchema(name="image_id", dtype=DataType.VARCHAR, max_length=64),
            FieldSchema(name="image_url", dtype=DataType.VARCHAR, max_length=512),
        ]
        schema = CollectionSchema(fields=fields, description="RAG chunks with image metadata")
        c.create_collection(
            collection_name=COLL_NAME,
            schema=schema,
        )
        # 建索引(IVF_FLAT 默认;小数据量可省)
        try:
            c.create_index(
                collection_name=COLL_NAME,
                field_name="vector",
                index_params={"metric_type": "IP", "index_type": "AUTOINDEX", "params": {}},
            )
        except Exception:
            pass
    return c


def insert_chunks(records: List[dict]) -> List[int]:
    c = ensure_collection()
    res = c.insert(collection_name=COLL_NAME, data=records)
    return res.get("ids", [])


def vector_search(query_vec: List[float], top_k: int = 10, filter_expr: str = None) -> List[dict]:
    c = ensure_collection()
    res = c.search(
        collection_name=COLL_NAME,
        data=[query_vec],
        limit=top_k,
        filter=filter_expr,
        output_fields=[
            "chunk_id", "document_id", "version_id", "text", "page", "category",
            "doc_title", "section_path", "image_id", "image_url",
        ],
    )
    if not res:
        return []
    return res[0]


def delete_by_doc_version(document_id: int, version_id: int = None):
    c = ensure_collection()
    expr = f'document_id == {document_id}'
    if version_id is not None:
        expr += f' and version_id == {version_id}'
    c.delete(collection_name=COLL_NAME, filter=expr)


def count() -> int:
    c = ensure_collection()
    stats = c.get_collection_stats(COLL_NAME)
    return int(stats.get("row_count", 0))