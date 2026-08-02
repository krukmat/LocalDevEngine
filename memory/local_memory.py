import json
import os
from typing import List, Dict, Any
import numpy as np
from memory.base import BaseMemory

class LocalVectorMemory(BaseMemory):
    """
    A lightweight local implementation of a Vector Store using NumPy and FAISS-like logic.
    Saves embeddings to a local file for persistence without heavy DB dependencies.
    Designed for low VRAM/Disk usage on laptops.
    """

    def __init__(self, storage_dir: str):
        self.storage_dir = storage_dir
        self.index_path = os.path.join(storage_dir, "embeddings.npy")
        self.metadata_path = os.path.join(storage_dir, "metadata.json")
        self.dimension: int = 0
        self._vector_matrix: np.ndarray = None
        self._metadata: List[Dict[str, Any]] = []

        if not os.path.exists(storage_dir):
            os.makedirs(storage_dir)
        
        self._load()

    def _load(self):
        """Loads existing vectors and metadata from disk."""
        if os.path.exists(self.index_path) and os.path.exists(self.metadata_path):
            self._vector_matrix = np.load(self.index_path, allow_pickle=True)
            with open(self.metadata_path, "r") as f:
                self._metadata = json.load(f)
            self.dimension = self._vector_matrix.shape[1]

    def _save(self):
        """Saves current vectors and metadata to disk."""
        if self._vector_matrix is not None:
            np.save(self.index_path, self._vector_matrix)
            with open(self.metadata_path, "w") as f:
                json.dump(self._metadata, f)

    def add_text(self, text: str, metadata: Dict[str, Any], embedding: List[float]) -> None:
        """Adds an embedded chunk to the local store."""
        emb = np.array(embedding).reshape(1, -1)
        
        if self._vector_matrix is None:
            self._vector_matrix = emb
            self.dimension = emb.size
        else:
            # Check dimension compatibility
            if emb.size != self.dimension:
                raise ValueError(f"Embedding dimension mismatch. Expected {self.dimension}, got {emb.size}")
            self._vector_matrix = np.vstack([self._vector_matrix, emb])

        self._metadata.append({
            "text": text,
            **metadata
        })
        self._save()

    def search(self, query_embedding: List[float], top_k: int = 3) -> List[Dict[str, Any]]:
        """Performs Cosine Similarity search to find related chunks."""
        if self._vector_matrix is None or len(self._metadata) == 0:
            return []

        query_vec = np.array(query_embedding).reshape(1, -1)
        # Compute cosine similarity: (A . B) / (||A|| * ||B||)
        # Since embeddings from Ollama are usually normalized or already high-dim:
        similarities = np.dot(self._vector_matrix, query_vec.T).flatten()
        
        # Get top k indices
        top_indices = np.argsort(similarities)[::-1][:top_k]

        results = []
        for idx in top_indices:
            res = self._metadata[idx].copy()
            res["score"] = float(similarities[idx])
            results.append(res)
            
        return results

    def get_all_chunks(self) -> List[Dict[str, Any]]:
        return self._metadata
