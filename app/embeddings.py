from typing import List, Optional
import numpy as np
import os
import logging

from app.config import settings

log = logging.getLogger("kb_admin")

_model = None


def _ensure_hf_login():
    if os.getenv("HF_TOKEN", "").strip():
        return
    if not settings.hf_token:
        raise RuntimeError("HF_TOKEN не задан. Добавьте HF_TOKEN в .env или окружение.")
    from huggingface_hub import login
    login(token=settings.hf_token)


def load_model_on_startup():
    global _model
    if _model is not None:
        log.info("Embedding model already loaded, skipping.")
        return

    _ensure_hf_login()

    from sentence_transformers import SentenceTransformer

    log.info(
        "Loading embeddings model=%s device=%s truncate_dim=%s",
        settings.embed_model_id,
        settings.embed_device,
        settings.embed_truncate_dim,
    )

    _model = SentenceTransformer(
        settings.embed_model_id,
        device=settings.embed_device,
        truncate_dim=settings.embed_truncate_dim,
    )

    try:
        _model.encode(["warmup"], batch_size=1, show_progress_bar=False)
        log.info("Embedding model loaded and warmed up on device=%s", settings.embed_device)
    except Exception as e:
        log.warning("Embedding model warmup failed (non-fatal): %s", e)


def _get_model():
    global _model
    if _model is None:
        log.warning("Embedding model not preloaded — loading lazily (may be slow).")
        load_model_on_startup()
    return _model


def clean_text(s: str) -> str:
    return (s or "").strip()


def encode_question_embedding(text: str) -> Optional[List[float]]:
    text = clean_text(text)
    if not text:
        return None

    model = _get_model()

    emb = model.encode(
        [text],
        batch_size=1,
        prompt_name="Retrieval-document",
        normalize_embeddings=True,
        convert_to_numpy=True,
        show_progress_bar=False,
    )

    emb = emb.astype(np.float32)[0]
    return emb.tolist()