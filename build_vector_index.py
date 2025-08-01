import os
from vector_store import VectorStore

# Charge la clé API depuis l'environnement
openai_api_key = os.getenv("OPENAI_API_KEY")
if not openai_api_key:
    raise ValueError("La clé OPENAI_API_KEY est manquante.")

# Initialise le vector store
store = VectorStore(openai_api_key=openai_api_key)

# Charge les documents du dossier data/
success = store.load_documents_from_directory("data")

if success:
    stats = store.get_stats()
    print(f"✅ Index créé avec succès : {stats}")
else:
    print("❌ Aucun document valide n’a été chargé.")
