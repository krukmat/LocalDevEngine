import os
from dataclasses import dataclass, field
from typing import List, Dict, Any, Tuple
from core.chunking import chunk_file, Chunk
from memory.embeddings import EmbeddingService, EmbeddingTooLargeError
from memory.local_memory import LocalVectorMemory

DEFAULT_EXTENSIONS = [".py", ".js", ".ts", ".md", ".sql", ".html"]
DEFAULT_IGNORED_DIRS = {"node_modules", ".git", "__pycache__", "venv", ".venv", ".vector_store"}
DEFAULT_MAX_FILE_BYTES = 1_000_000
DEFAULT_BATCH_SIZE = 16
MAX_SPLIT_DEPTH = 4


@dataclass
class IngestSummary:
    indexed_files: int = 0
    skipped: List[Tuple[str, str]] = field(default_factory=list)
    failed: List[Tuple[str, str]] = field(default_factory=list)
    total_chunks: int = 0


class DataIngestor:
    """
    Scans a directory and populates the Vector Memory. Files are split into
    structural chunks (core/chunking.py) before embedding, since a single
    file can exceed the embedding model's context window.
    """

    def __init__(
        self,
        memory: LocalVectorMemory,
        embedder: EmbeddingService,
        extensions: List[str] = None,
        ignored_dirs: set = None,
        max_file_bytes: int = DEFAULT_MAX_FILE_BYTES,
        max_chunk_chars: int = 3000,
        batch_size: int = DEFAULT_BATCH_SIZE,
    ):
        self.memory = memory
        self.embedder = embedder
        self.extensions = extensions or DEFAULT_EXTENSIONS
        self.ignored_dirs = ignored_dirs or DEFAULT_IGNORED_DIRS
        self.max_file_bytes = max_file_bytes
        self.max_chunk_chars = max_chunk_chars
        self.batch_size = batch_size

    async def ingest_directory(self, directory_path: str) -> IngestSummary:
        """Recursively crawls a directory and indexes files of the configured extensions."""
        print(f"🚀 Starting ingestion in: {directory_path}")
        summary = IngestSummary()

        for root, dirs, files in os.walk(directory_path):
            dirs[:] = sorted(d for d in dirs if d not in self.ignored_dirs)

            for file in sorted(files):
                if not any(file.endswith(ext) for ext in self.extensions):
                    continue
                file_path = os.path.join(root, file)
                await self._process_file(file_path, summary)

        print(
            f"✅ Ingestion complete. Indexed {summary.indexed_files} files "
            f"({summary.total_chunks} chunks), {len(summary.skipped)} skipped, "
            f"{len(summary.failed)} failed."
        )
        if summary.failed:
            print("⚠️ Failures:")
            for path, reason in summary.failed:
                print(f"  {path}: {reason}")
        return summary

    async def _process_file(self, file_path: str, summary: IngestSummary) -> None:
        source = os.path.realpath(file_path)

        try:
            file_size = os.path.getsize(file_path)
        except OSError as e:
            summary.failed.append((file_path, f"stat failed: {e}"))
            return

        if file_size > self.max_file_bytes:
            summary.skipped.append((file_path, f"exceeds max_file_bytes ({file_size} bytes)"))
            return

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()
        except (OSError, UnicodeDecodeError) as e:
            summary.failed.append((file_path, f"read failed: {e}"))
            return

        if not content.strip():
            summary.skipped.append((file_path, "empty or whitespace-only"))
            return

        chunks = chunk_file(file_path, content, max_chars=self.max_chunk_chars)
        if not chunks:
            summary.skipped.append((file_path, "no chunks produced"))
            return

        try:
            items = await self._embed_chunks(file_path, chunks)
        except Exception as e:
            summary.failed.append((file_path, f"embedding failed: {str(e) or type(e).__name__}"))
            return

        for item in items:
            item["metadata"] = {
                "source": source,
                "filename": os.path.basename(file_path),
            }

        # Chunk and embed BEFORE touching the store: replace_source deletes
        # and re-adds atomically, so a failure above never loses old rows.
        self.memory.replace_source(source, items)

        summary.indexed_files += 1
        summary.total_chunks += len(items)

    async def _embed_chunks(self, file_path: str, chunks: List[Chunk]) -> List[Dict[str, Any]]:
        """Embeds all chunks of a file in batches, bisecting on
        EmbeddingTooLargeError to isolate and split the offending chunk."""
        items: List[Dict[str, Any]] = []
        texts = [c.text for c in chunks]

        for i in range(0, len(texts), self.batch_size):
            batch = texts[i:i + self.batch_size]
            items.extend(await self._embed_batch(batch, depth=0))

        return items

    async def _embed_batch(self, texts: List[str], depth: int) -> List[Dict[str, Any]]:
        try:
            embeddings, _ = await self.embedder.get_embeddings(texts)
            return [{"text": t, "embedding": e} for t, e in zip(texts, embeddings)]
        except EmbeddingTooLargeError:
            if len(texts) == 1:
                return await self._split_and_embed(texts[0], depth)
            mid = len(texts) // 2
            left = await self._embed_batch(texts[:mid], depth)
            right = await self._embed_batch(texts[mid:], depth)
            return left + right

    async def _split_and_embed(self, text: str, depth: int) -> List[Dict[str, Any]]:
        """A single chunk was still too large for the model — split it in
        half and retry, bounded by MAX_SPLIT_DEPTH."""
        if depth >= MAX_SPLIT_DEPTH or len(text) < 2:
            raise EmbeddingTooLargeError(
                f"Chunk still too large after {depth} halvings ({len(text)} chars)."
            )
        mid = len(text) // 2
        left_items = await self._embed_batch([text[:mid]], depth + 1)
        right_items = await self._embed_batch([text[mid:]], depth + 1)
        return left_items + right_items
