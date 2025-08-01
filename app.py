from flask import Flask, request, jsonify

app = Flask(__name__)

@app.route("/")
def home():
    return "Bienvenue sur l'Assistant Kimoky !"

@app.route("/chat", methods=["POST"])
def chat():
    if request.content_type != 'application/json':
        return jsonify({"response": "Contenu non supporté. Utilisez 'application/json'."}), 415

    try:
        data = request.get_json(force=True)
        message = data.get("message", "").strip()

        if not message:
            return jsonify({"response": "Le message est vide."}), 400

        # Réponse simulée pour le test
        response = f"Merci pour votre question : « {message} ». Notre conseillère vous répondra bientôt."
        return jsonify({"response": response}), 200

    except Exception as e:
        return jsonify({"response": f"Erreur côté serveur : {str(e)}"}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
