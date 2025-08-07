from flask import Flask, request, jsonify
import os, uuid
from datetime import datetime, timedelta
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS
from flask import make_response
import openai

app = Flask(__name__)

# Configuration CORS
CORS(app, resources={r"/chat": {"origins": ["https://kimoky.com", "https://www.kimoky.com"]}})

# Configuration OpenAI
openai.api_key = os.getenv("OPENAI_API_KEY")

# Configuration base de données
db_uri = os.getenv("DATABASE_URL", "sqlite:///kimoky_chat.db")
if db_uri.startswith("postgres://"):
    db_uri = db_uri.replace("postgres://", "postgresql://", 1)

app.config["SQLALCHEMY_DATABASE_URI"] = db_uri
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)

# --- Modèles de base de données ---
class Conversation(db.Model):
    __tablename__ = "conversations"  # Correction: double underscore
    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.String(64), index=True, nullable=False)
    started_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    last_activity_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    page_url = db.Column(db.Text)
    user_agent = db.Column(db.Text)
    locale = db.Column(db.String(16))
    ip = db.Column(db.String(64))

class Message(db.Model):
    __tablename__ = "messages"  # Correction: double underscore
    id = db.Column(db.Integer, primary_key=True)
    conversation_id = db.Column(db.Integer, db.ForeignKey("conversations.id"), index=True, nullable=False)
    role = db.Column(db.String(16), nullable=False)
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

# Créer les tables
with app.app_context():
    db.create_all()

# Configuration
IDLE_TIMEOUT = timedelta(minutes=30)

def get_or_create_conversation(payload):
    """Récupère ou crée une conversation"""
    sid = (payload.get("session_id") or request.cookies.get("lucie_sid") or uuid.uuid4().hex)[:64]
    now = datetime.utcnow()
    
    conv = (Conversation.query
            .filter_by(session_id=sid)
            .order_by(Conversation.last_activity_at.desc())
            .first())
    
    if not conv or (now - conv.last_activity_at) > IDLE_TIMEOUT:
        conv = Conversation(session_id=sid, started_at=now)
        db.session.add(conv)
    
    # Mettre à jour les informations
    conv.last_activity_at = now
    conv.page_url = payload.get("page_url") or conv.page_url
    conv.user_agent = request.headers.get("User-Agent")
    conv.locale = payload.get("locale") or conv.locale
    conv.ip = request.headers.get("CF-Connecting-IP") or request.remote_addr
    
    db.session.commit()
    return conv, sid

def get_ai_response(message):
    """Obtient une réponse de l'IA"""
    try:
        response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=[
                {
                    "role": "system", 
                    "content": """Tu es Lucie, l'assistante virtuelle de Kimoky, une boutique de kimonos japonais élégants.

Ton rôle:
- Aide les clients avec leurs questions sur les kimonos
- Donne des conseils de style et de taille
- Explique les différents types de kimonos (yukata, furisode, etc.)
- Reste polie, chaleureuse et professionnelle
- Réponds en français
- Si tu ne sais pas, oriente vers le service client

Garde tes réponses concises mais utiles."""
                },
                {"role": "user", "content": message}
            ],
            max_tokens=200,
            temperature=0.7
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        return f"Désolée, je rencontre une difficulté technique. Pouvez-vous réessayer ? (Erreur: {str(e)})"

@app.route("/")
def home():
    return "🌸 Assistant Lucie - Kimoky est en ligne !"

@app.route("/chat", methods=["POST"])
def chat():
    """Endpoint principal du chat"""
    try:
        # Vérification du contenu
        if not request.is_json:
            return jsonify({"response": "Format JSON requis."}), 400
        
        data = request.get_json()
        message = data.get("message", "").strip()
        
        if not message:
            return jsonify({"response": "Votre message semble vide. Pouvez-vous reformuler votre question ?"}), 400
        
        # Gestion de la conversation
        conversation, session_id = get_or_create_conversation(data)
        
        # Obtenir la réponse de l'IA
        response = get_ai_response(message)
        
        # Sauvegarder les messages en base
        user_msg = Message(
            conversation_id=conversation.id, 
            role="user", 
            content=message
        )
        assistant_msg = Message(
            conversation_id=conversation.id, 
            role="assistant", 
            content=response
        )
        
        db.session.add_all([user_msg, assistant_msg])
        db.session.commit()
        
        # Créer la réponse avec cookie de session
        resp = make_response(jsonify({"response": response}))
        resp.set_cookie(
            "lucie_sid", 
            session_id, 
            max_age=30*24*3600, 
            httponly=True, 
            secure=True,
            samesite='None'
        )
        
        return resp
        
    except Exception as e:
        print(f"Erreur dans /chat: {e}")
        return jsonify({
            "response": "Je rencontre une difficulté technique. Pouvez-vous réessayer dans quelques instants ?"
        }), 500

@app.route("/health")
def health():
    """Endpoint de santé pour Render"""
    return jsonify({"status": "healthy", "timestamp": datetime.utcnow().isoformat()})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
