import os
import logging
import pickle
from typing import List, Dict, Any
import numpy as np
import faiss
from openai import OpenAI

from document_processor import DocumentProcessor

logger = logging.getLogger(__name__)

class VectorStore:
    """
    FAISS-based vector store for document embeddings with OpenAI
    """
    
    def __init__(self, openai_api_key: str, embedding_model: str = "text-embedding-3-small"):
        """
        Initialize the vector store
        """
        self.openai_client = OpenAI(api_key=openai_api_key)
        self.embedding_model = embedding_model
        self.dimension = 1536  # For text-embedding-3-small

        self.index = faiss.IndexFlatIP(self.dimension)  # Cosine similarity
        self.documents = []
        self.document_processor = DocumentProcessor()

        self._load_index()

    def _load_index(self):
        try:
            if os.path.exists("vector_index.faiss") and os.path.exists("documents.pkl"):
                self.index = faiss.read_index("vector_index.faiss")
                with open("documents.pkl", "rb") as f:
                    self.documents = pickle.load(f)
                logger.info(f"Loaded index with {len(self.documents)} documents")
        except Exception as e:
            logger.warning(f"Could not load existing index: {e}")

    def _save_index(self):
        try:
            faiss.write_index(self.index, "vector_index.faiss")
            with open("documents.pkl", "wb") as f:
                pickle.dump(self.documents, f)
            logger.info("Saved index and documents")
        except Exception as e:
            logger.error(f"Could not save index: {e}")

    def _get_embeddings(self, texts: List[str]) -> List[List[float]]:
        """
        Get embeddings for texts in batches to avoid token limit
        """
        try:
            all_embeddings = []
            batch_size = 50

            for i in range(0, len(texts), batch_size):
                batch = texts[i:i + batch_size]
                response = self.openai_client.embeddings.create(
                    model=self.embedding_model,
                    input=batch
                )
                embeddings = [e.embedding for e in response.data]
                all_embeddings.extend(embeddings)

            return all_embeddings
        except Exception as e:
            logger.error(f"Error getting embeddings: {e}")
            raise

    def add_documents(self, file_path: str) -> bool:
        try:
            chunks = self.document_processor.process_file(file_path)
            if not chunks:
                logger.warning(f"No chunks from {file_path}")
                return False

            logger.info(f"Processing {len(chunks)} chunks from {file_path}")
            texts = [chunk["text"] for chunk in chunks]
            embeddings = self._get_embeddings(texts)

            embeddings_array = np.array(embeddings, dtype=np.float32)
            faiss.normalize_L2(embeddings_array)
            self.index.add(embeddings_array)

            for i, chunk in enumerate(chunks):
                self.documents.append({
                    "text": chunk["text"],
                    "file_path": file_path,
                    "chunk_index": chunk["chunk_index"],
                    "index_id": len(self.documents)
                })

            logger.info(f"Added {len(chunks)} chunks from {file_path}")
            self._save_index()
            return True

        except Exception as e:
            logger.error(f"Error adding documents from {file_path}: {e}")
            return False

    def load_documents_from_directory(self, directory: str) -> bool:
        if not os.path.exists(directory):
            logger.error(f"Directory {directory} not found")
            return False

        success_count = 0
        supported_extensions = [".txt", ".md", ".csv"]

        for filename in os.listdir(directory):
            file_path = os.path.join(directory, filename)
            if os.path.isdir(file_path):
                continue

            _, ext = os.path.splitext(filename)
            if ext.lower() not in supported_extensions:
                continue

            logger.info(f"Loading document: {filename}")
            if self.add_documents(file_path):
                success_count += 1
            else:
                logger.warning(f"Failed to load document: {filename}")

        logger.info(f"Loaded {success_count} documents from {directory}")
        return success_count > 0

    def search(self, query: str, top_k: int = 5) -> List[Dict[str, Any]]:
        try:
            if self.index.ntotal == 0:
                logger.warning("Index is empty")
                return []

            query_embedding = self._get_embeddings([query])[0]
            query_vector = np.array([query_embedding], dtype=np.float32)
            faiss.normalize_L2(query_vector)

            scores, indices = self.index.search(query_vector, min(top_k, self.index.ntotal))
            results = []

            for i, (score, idx) in enumerate(zip(scores[0], indices[0])):
                if 0 <= idx < len(self.documents):
                    doc = self.documents[idx].copy()
                    doc["similarity_score"] = float(score)
                    doc["rank"] = i + 1
                    results.append(doc)

            logger.info(f"Found {len(results)} results for query")
            return results

        except Exception as e:
            logger.error(f"Error during search: {e}")
            return []

    def get_stats(self) -> Dict[str, Any]:
        return {
            "total_documents": len(self.documents),
            "index_size": self.index.ntotal,
            "embedding_dimension": self.dimension,
            "embedding_model": self.embedding_model
        }
