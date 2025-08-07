import os
import csv
import logging

logger = logging.getLogger(__name__)

class DocumentProcessor:
    def process_file(self, file_path):
        """Traite un fichier et le découpe en chunks"""
        chunks = []
        filename = os.path.basename(file_path)
        ext = os.path.splitext(file_path)[1].lower()
        
        try:
            if ext == ".txt" or ext == ".md":
                with open(file_path, "r", encoding="utf-8") as f:
                    text = f.read()
                    paragraphs = text.split("\n\n")
                    for i, para in enumerate(paragraphs):
                        if para.strip():
                            chunks.append({
                                "text": para.strip(),
                                "chunk_index": i
                            })
                            
            elif ext == ".csv":
                with open(file_path, newline='', encoding="utf-8") as f:
                    reader = csv.reader(f)
                    buffer = []
                    chunk_index = 0
                    max_lines_per_chunk = 5  # Découpage optimisé
                    
                    for row in reader:
                        line = " | ".join(cell.strip() for cell in row if cell)
                        if line:
                            buffer.append(line)
                            
                        if len(buffer) >= max_lines_per_chunk:
                            chunks.append({
                                "text": " ".join(buffer),
                                "chunk_index": chunk_index
                            })
                            buffer = []
                            chunk_index += 1
                    
                    # Ajouter le dernier chunk s'il reste des données
                    if buffer:
                        chunks.append({
                            "text": " ".join(buffer),
                            "chunk_index": chunk_index
                        })
            else:
                logger.warning(f"Format de fichier non supporté: {ext}")
                
        except Exception as e:
            logger.error(f"Erreur lors du traitement de {file_path}: {e}")
            
        logger.info(f"Fichier {filename} traité: {len(chunks)} chunks créés")
        return chunks
