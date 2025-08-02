import logging
from typing import List, Dict, Any
from openai import OpenAI

from vector_store import VectorStore

logger = logging.getLogger(__name__)

class ChatHandler:
    def __init__(self, openai_api_key: str, vector_store: VectorStore):
        self.openai_client = OpenAI(api_key=openai_api_key)
        self.vector_store = vector_store
        self.model = "gpt-4o"
        self.temperature = 0.3

        self.system_prompt = """
Tu es **Lucie**, la conseillère digitale de la marque Kimoky (https://kimoky.com), une boutique spécialisée dans les kimonos modernes, élégants et inspirés de l’esthétique japonaise. Tu accompagnes chaque visiteur avec douceur, précision et élégance.

🎯 Ton rôle :
1. Guider les clientes et clients dans le choix du kimono idéal selon leur morphologie, le style recherché (chic, nuit, décontracté, plage…), la matière (satin, coton…) ou la saison.
2. Répondre de façon concise, fluide et rassurante à toutes les questions pratiques : livraison, retours, échanges, tailles, suivi de commande, sécurité, contact client.

✨ Ton ton est toujours :
- poétique, chaleureux, professionnel et fluide
- fidèle à l’univers raffiné de Kimoky
- orienté conseil, inspiration et confiance

📌 Règles :
- Tu ne donnes **jamais de prix**
- Tu ne passes **jamais commande**
- Tu ne dis **jamais que tu es une IA ou un chatbot**
- Tu restes toujours polie, rassurante et élégante
- Tu peux proposer des liens utiles vers https://kimoky.com si cela aide

🖋️ Tu peux utiliser **1 à 2 emojis élégants maximum** (ex : ✨, 🌸, 📦, 💌), uniquement s’ils renforcent la clarté ou l’émotion. Jamais d’emojis trop familiers (😍🔥😂…).

💬 Si une question est floue, reformule-la avec tact. Si la personne semble perdue, guide-la avec douceur.

🎁 Exemples de ton :
- « Ce modèle long en satin fluide sublimera les silhouettes élancées ✨ »
- « Vous pouvez suivre votre commande directement sur notre page de suivi 📦 »
- « Pour une soirée douce à la maison, optez pour un kimono mi-long en coton léger. »

Tu es **Lucie**, la voix élégante et bienveillante de Kimoky 🌸
        """

    def get_response(self, question: str, is_mobile: bool = False) -> str:
        try:
            context_docs = self.vector_store.search(question, top_k=5)
            context = self._build_context(context_docs)

            if context.strip().startswith("Aucun document"):
                return "Je n’ai pas trouvé cette information dans notre base. Vous pouvez consulter notre page FAQ ou nous écrire à boutique@kimoky.com 💌"

            user_prompt = self._create_user_prompt(question, context)

            response = self.openai_client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": self.system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=self.temperature,
                max_tokens=400 if is_mobile else 800
            )

            answer = response.choices[0].message.content

            # Supprimer le préfixe [Kimoky] s'il apparaît
            if answer.strip().startswith("[Kimoky]"):
                answer = answer.strip().replace("[Kimoky]", "", 1).lstrip()

            logger.info(f"Generated response for question: {question[:50]}...")
            return answer

        except Exception as e:
            logger.error(f"Error generating response: {e}")
            return "Je suis désolée, une erreur s’est produite. N’hésitez pas à nous recontacter ou à consulter notre page d’aide."

    def _build_context(self, context_docs: List[Dict[str, Any]]) -> str:
        if not context_docs:
            return "Aucun document de référence trouvé."

        context_parts = []
        for i, doc in enumerate(context_docs, 1):
            source = doc.get("source_file", "Document")
            text = doc.get("text", "")
            score = doc.get("similarity_score", 0)
            context_parts.append(f"[Document {i} - {source} (pertinence: {score:.2f})]:\n{text}\n")

        return "\n".join(context_parts)

    def _create_user_prompt(self, question: str, context: str) -> str:
        return f"""QUESTION : {question}

CONTEXTE :
{context}

Réponds de façon concise, chaleureuse et professionnelle, en t’appuyant sur le contexte si possible. Si le contexte est insuffisant, propose une réponse rassurante ou un lien vers le site Kimoky."""

    def _categorize_question(self, question: str) -> str:
        question_lower = question.lower()
        if any(word in question_lower for word in ["livraison", "expédition", "délai", "transport"]):
            return "livraison"
        elif any(word in question_lower for word in ["retour", "échange", "remboursement", "cgv"]):
            return "retours"
        elif any(word in question_lower for word in ["taille", "sizing", "mesure", "morphologie"]):
            return "taille"
        elif any(word in question_lower for word in ["matière", "composition", "entretien", "lavage"]):
            return "produit"
        else:
            return "general"
