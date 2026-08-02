import os
from typing import List, Dict, Any
from memory.embeddings import EmbeddingService
from memory.local_memory import LocalVectorMemory

class DataIngestor:
    """
    Responsible for scanning directories and populating the Vector Memory.
    Optimized to process files in chunks and respect project structure.
    """
    def __init__(self, memory: LocalVectorMemory, embedder: EmbeddingService):
        self.memory = memory
        self.embedder = embedder

    async def ingest_directory(self, directory_path: str, extensions: List[str] = None) -> None:
        """
        Recursively crawls a directory and indexes files of specified extensions.
        """
        if extensions is None:
            extensions = [".py", ".js", ".ts", ".md", ".sql", ".html"]

        print(f"🚀 Starting ingestion in: {directory_path}")
        count = 0
        
        for root, _, files in os.walk(directory_path):
            # Skip common heavy/irrelevant directories
            if any(ignored in root for ignored in ["node_modules", ".git", "__pycache__", "venv"]):
                continue

            for file in files:
                if any(file.endswith(ext) for ext in extensions):
                    file_path = os.path.join(root, file)
                    await self._process_file(file_path)
                    count += 1
        
        print(f"✅ Ingestion complete. Indexed {count} files.")

    async def _process_file(self, file_path: str) -> None:
        """Reads a file and adds it to the vector memory."""
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()
                # Avoid indexing empty files or extremely large blobs without logical splitting
                if len(content) < 10 and not content.strip():
                    return

                # In a more advanced version, we'd split the file into semantic chunks here.
                # For now, we index the whole file as one chunk for simplicity in this MVP.
                embedding = await self.embedder.get_embedding(content)
                self.memory.add_text(
                    text=content,
                    metadata={
                        "source": file_path,
                        "filename": os.path.basename(file_path)
                    },
                    embedding=embedding
                )
        except Exception as e:
            print(f"⚠️ Error processing {file_path}: {str(e)}")

