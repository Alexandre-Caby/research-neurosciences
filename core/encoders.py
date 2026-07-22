import numpy as np

from core import config


class TextEncoder:
    def __init__(self, model=config.TEXT_MODEL, device=None):
        self.model_name = model
        self.device = device or config.device()
        self._model = None
        self._dim = None

    @property
    def dim(self):
        return self._dim if self._dim is not None else config.TEXT_DIM

    def _load(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(self.model_name, device=self.device)
            self._dim = self._model.get_sentence_embedding_dimension()

    def encode(self, texts: list[str], batch_size=config.EMBED_BATCH) -> np.ndarray:
        self._load()
        return self._model.encode(
            texts,
            batch_size=batch_size,
            normalize_embeddings=True,
            show_progress_bar=False,
            convert_to_numpy=True,
        ).astype("float32")
