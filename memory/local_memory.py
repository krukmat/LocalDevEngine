import json
import os
import tempfile
from typing import List, Dict, Any, Optional
import numpy as np
from memory.base import BaseMemory


class VectorStoreError(RuntimeError):
    """Raised when the on-disk store is missing, corrupt, or inconsistent."""


class LocalVectorMemory(BaseMemory):
    """
    A lightweight local implementation of a Vector Store using NumPy.
    Vectors are stored L2-normalized, so a plain dot product at query time
    *is* cosine similarity — no per-query normalization cost.
    Saves embeddings to a local file for persistence without heavy DB dependencies.
    Designed for low VRAM/Disk usage on laptops.
    """

    def __init__(self, storage_dir: str, dimension: int):
        self.storage_dir = storage_dir
        self.index_path = os.path.join(storage_dir, "embeddings.npy")
        self.metadata_path = os.path.join(storage_dir, "metadata.json")
        self.dimension = dimension
        self._vector_matrix: Optional[np.ndarray] = None
        self._metadata: List[Dict[str, Any]] = []

        if not os.path.exists(storage_dir):
            os.makedirs(storage_dir)

        self._load()

    def _load(self):
        """Loads existing vectors and metadata from disk, validating consistency."""
        index_exists = os.path.exists(self.index_path)
        metadata_exists = os.path.exists(self.metadata_path)

        if not index_exists and not metadata_exists:
            return
        if index_exists != metadata_exists:
            raise VectorStoreError(
                f"Vector store at {self.storage_dir!r} is incomplete: "
                f"index present={index_exists}, metadata present={metadata_exists}. "
                "Delete the .vector_store directory to rebuild from scratch."
            )

        matrix = np.load(self.index_path, allow_pickle=False)
        with open(self.metadata_path, "r") as f:
            metadata = json.load(f)

        if matrix.ndim != 2:
            raise VectorStoreError(f"Vector store index has unexpected shape {matrix.shape!r}")
        if matrix.shape[0] != len(metadata):
            raise VectorStoreError(
                f"Vector store is out of sync: {matrix.shape[0]} vectors but "
                f"{len(metadata)} metadata rows."
            )
        if matrix.shape[0] > 0 and matrix.shape[1] != self.dimension:
            raise VectorStoreError(
                f"Vector store dimension {matrix.shape[1]} does not match configured "
                f"dimension {self.dimension}."
            )

        self._vector_matrix = matrix.astype(np.float32, copy=False)
        self._metadata = metadata

    def _save(self):
        """Atomically saves current vectors and metadata to disk."""
        if self._vector_matrix is None:
            return

        index_fd, index_tmp = tempfile.mkstemp(dir=self.storage_dir, suffix=".npy.tmp")
        os.close(index_fd)
        metadata_fd, metadata_tmp = tempfile.mkstemp(dir=self.storage_dir, suffix=".json.tmp")
        os.close(metadata_fd)
        try:
            np.save(index_tmp, self._vector_matrix)
            # np.save appends .npy if the name doesn't already end with it
            if not index_tmp.endswith(".npy"):
                os.replace(index_tmp + ".npy", index_tmp)
            with open(metadata_tmp, "w") as f:
                json.dump(self._metadata, f)

            os.replace(index_tmp, self.index_path)
            os.replace(metadata_tmp, self.metadata_path)
        finally:
            for tmp in (index_tmp, index_tmp + ".npy", metadata_tmp):
                if os.path.exists(tmp):
                    os.remove(tmp)

    @staticmethod
    def _normalize(vectors: np.ndarray) -> np.ndarray:
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        if np.any(norms == 0):
            raise ValueError("Cannot normalize a zero vector.")
        return vectors / norms

    def _validate_embedding(self, embedding: List[float]) -> np.ndarray:
        if not embedding:
            raise ValueError("Embedding is empty.")
        vec = np.array(embedding, dtype=np.float32)
        if vec.ndim != 1 or vec.shape[0] != self.dimension:
            raise ValueError(
                f"Embedding dimension mismatch. Expected {self.dimension}, got {vec.shape}"
            )
        return vec

    def add_text(self, text: str, metadata: Dict[str, Any], embedding: List[float]) -> None:
        """Adds a single embedded chunk to the local store (normalized, then saved)."""
        self.add_batch([{"text": text, "metadata": metadata, "embedding": embedding}])

    def add_batch(self, items: List[Dict[str, Any]]) -> None:
        """
        Adds multiple embedded chunks in a single vstack + single _save().
        Each item: {"text": str, "metadata": dict, "embedding": List[float]}.
        """
        if not items:
            return

        vectors = np.stack([self._validate_embedding(item["embedding"]) for item in items])
        vectors = self._normalize(vectors)

        if self._vector_matrix is None:
            self._vector_matrix = vectors
        else:
            self._vector_matrix = np.vstack([self._vector_matrix, vectors])

        for item in items:
            self._metadata.append({"text": item["text"], **item["metadata"]})

        self._save()

    def replace_source(self, source: str, items: List[Dict[str, Any]]) -> None:
        """
        Atomically replaces all chunks for `source` with `items` in one operation.
        Chunk and embed the new content BEFORE calling this — there is no
        intermediate state where the source is deleted but not yet replaced.
        """
        keep_mask = [m.get("source") != source for m in self._metadata]
        if self._vector_matrix is not None:
            self._vector_matrix = self._vector_matrix[np.array(keep_mask, dtype=bool)]
        self._metadata = [m for m, keep in zip(self._metadata, keep_mask) if keep]

        if not items:
            self._save()
            return

        vectors = np.stack([self._validate_embedding(item["embedding"]) for item in items])
        vectors = self._normalize(vectors)

        if self._vector_matrix is None:
            self._vector_matrix = vectors
        else:
            self._vector_matrix = np.vstack([self._vector_matrix, vectors])

        for item in items:
            self._metadata.append({"text": item["text"], **item["metadata"]})

        self._save()

    def search(
        self,
        query_embedding: List[float],
        top_k: int = 3,
        min_score: float = 0.0,
    ) -> List[Dict[str, Any]]:
        """
        Cosine similarity search. Since stored vectors are normalized at write
        time, this is a plain dot product against a normalized query vector.
        Returns at most top_k results with score >= min_score.
        """
        if self._vector_matrix is None or len(self._metadata) == 0:
            return []

        query_vec = self._validate_embedding(query_embedding).reshape(1, -1)
        query_vec = self._normalize(query_vec)

        similarities = np.dot(self._vector_matrix, query_vec.T).flatten()
        top_indices = np.argsort(similarities)[::-1][:top_k]

        results = []
        for idx in top_indices:
            score = float(similarities[idx])
            if score < min_score:
                continue
            res = self._metadata[idx].copy()
            res["score"] = score
            results.append(res)

        return results

    def get_all_chunks(self) -> List[Dict[str, Any]]:
        return [m.copy() for m in self._metadata]
