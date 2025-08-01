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
    Stockage vectoriel basé sur FAISS + OpenAI Embeddings, avec persistance.
    """

    def __init__(self, openai_api_key: str, embedding_model: str = "text-embedding-3-small"):
        self.openai_client = OpenAI(api_key=openai_api_key)
        self.embedding_model = embedding_model
        self.dimension = 1536  # text-embedding-3-small

        self.index = faiss.IndexFlatIP(self.dimension)  # Cosine similarity (via L2 normalization)
        self.documents = []
        self.document_processor = DocumentProcessor()

        self._load_index()

        # ✅ Chargement automatique si index vide
        if self.index.ntotal == 0:
            logger.warning("Index vide : chargement initial depuis ./data")
            self.load_documents_from_directory("./data")

    def _load_index(self):
        try:
            if os.path.exists("vector_index.faiss") and os.path.exists("documents.pkl"):
                self.index = faiss.read_index("vector_index.faiss")
                with open("documents.pkl", "rb") as f:
                    self.documents = pickle.load(f)
                logger.info(f"Index chargé avec {len(self.documents)} documents.")
        except Exception as e:
            logger.warning(f"Impossible de charger l’index existant : {e}")

    def _save_index(self):
        try:
            faiss.write_index(self.index, "vector_index.faiss")
            with open("documents.pkl", "wb") as f:
                pickle.dump(self.documents, f)
            logger.info("Index et documents enregistrés avec succès.")
        except Exception as e:
            logger.error(f"Erreur lors de l’enregistrement de l’index : {e}")

    def _get_embeddings(self, texts: List[str]) -> List[List[float]]:
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
            logger.error(f"Erreur lors du calcul des embeddings : {e}")
            raise

    def add_documents(self, file_path: str) -> bool:
        try:
            chunks = self.document_processor.process_file(file_path)
            if not chunks:
                logger.warning(f"Aucun contenu extrait de {file_path}")
                return False

            texts = [chunk["text"] for chunk in chunks]
            embeddings = self._get_embeddings(texts)
            embeddings_array = np.array(embeddings, dtype=np.float32)
            faiss.normalize_L2(embeddings_array)
            self.index.add(embeddings_array)

            for i, chunk in enumerate(chunks):
                self.documents.append({
                    "text": chunk["text"],
                    "source_file": os.path.basename(file_path),
                    "chunk_index": chunk["chunk_index"],
                    "index_id": len(self.documents)
                })

            logger.info(f"{len(chunks)} extraits ajoutés depuis {file_path}")
            self._save_index()
            return True

        except Exception as e:
            logger.error(f"Erreur lors de l’ajout de {file_path} : {e}")
            return False

    def load_documents_from_directory(self, directory: str) -> bool:
        if not os.path.exists(directory):
            logger.error(f"Dossier introuvable : {directory}")
            return False

        success_count = 0
        extensions_valides = [".txt", ".md", ".csv"]

        for fichier in os.listdir(directory):
            chemin = os.path.join(directory, fichier)
            if os.path.isdir(chemin):
                continue

            _, ext = os.path.splitext(fichier)
            if ext.lower() not in extensions_valides:
                continue

            logger.info(f"Chargement de : {fichier}")
            if self.add_documents(chemin):
                success_count += 1
            else:
                logger.warning(f"Échec du chargement de : {fichier}")

        logger.info(f"{success_count} documents chargés depuis {directory}")
        return success_count > 0

    def search(self, query: str, top_k: int = 5) -> List[Dict[str, Any]]:
        try:
            if self.index.ntotal == 0:
                logger.warning("⚠️ L’index est vide. Aucun résultat possible.")
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

            logger.info(f"{len(results)} résultats retournés pour : {query}")
            return results

        except Exception as e:
            logger.error(f"Erreur lors de la recherche : {e}")
            return []

    def get_stats(self) -> Dict[str, Any]:
        return {
            "total_documents": len(self.documents),
            "index_size": self.index.ntotal,
            "embedding_model": self.embedding_model,
            "embedding_dimension": self.dimension
        }
