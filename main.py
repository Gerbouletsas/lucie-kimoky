from flask import Flask, request, jsonify
from flask_cors import CORS
import os
import logging
logging.basicConfig(level=logging.DEBUG)

from chat_handler import ChatHandler
from vector_store import VectorStore

app = Flask(__name__)
CORS(app)

openai_api_key = os.getenv("OPENAI_API_KEY")
if not openai_api_key:
    raise ValueError("La clé OPENAI_API_KEY est manquante.")

vector_store = VectorStore(openai_api_key=openai_api_key)
lucie = ChatHandler(openai_api_key=openai_api_key, vector_store=vector_store)

@app.route("/")
def home():
    return "Lucie est en ligne 🌸"

@app.route("/chat", methods=["POST"])
def chat():
    try:
        data = request.get_json(force=True)
        message = data.get("message", "").strip()
        if not message:
            return jsonify({"response": "Je n’ai pas compris votre message."}), 400
        response = lucie.get_response(message)
        return jsonify({"response": response})
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"response": "Une erreur est survenue côté serveur."}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
