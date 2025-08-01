
import os
from vector_store import VectorStore

# Charge la clé API depuis l'environnement
openai_api_key = os.getenv("OPENAI_API_KEY")
if not openai_api_key:
    raise ValueError("La clé OPENAI_API_KEY est manquante.")

# Initialise l'index vectoriel existant
store = VectorStore(openai_api_key=openai_api_key)

# Recherche dans l'index
query = "délais de livraison"
results = store.search(query, top_k=5)

if not results:
    print("❌ Aucun résultat trouvé pour la requête :", query)
else:
    for i, res in enumerate(results, 1):
        print(f"\n--- Résultat {i} ---")
        print(res["text"])
