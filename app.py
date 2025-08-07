from flask import Flask, request, jsonify
import os, uuid
from datetime import datetime, timedelta
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS
from flask import make_response

# Import de vos modules
from chat_handler import ChatHandler
from vector_store import VectorStore

app = Flask(__name__)

# CORS - autoriser votre site
CORS(app, resources={r"/chat": {"origins": ["https://kimoky.com", "https://www.kimoky.com"]}})

# Configuration base de données
db_uri = os.getenv("DATABASE_URL", "sqlite:///kimoky_chat.db")
if db_uri.startswith("postgres://"):
    db_uri = db_uri.replace("postgres://", "postgresql://", 1)

app.config["SQLALCHEMY_DATABASE_URI"] = db_uri
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)

# --- Modèles de base de données ---
class Conversation(db.Model):
    __tablename__ = "conversations"
    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.String(64), index=True, nullable=False)
    started_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    last_activity_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    page_url = db.Column(db.Text)
    user_agent = db.Column(db.Text)
    locale = db.Column(db.String(16))
    ip = db.Column(db.String(64))

class Message(db.Model):
    __tablename__ = "messages"
    id = db.Column(db.Integer, primary_key=True)
    conversation_id = db.Column(db.Integer, db.ForeignKey("conversations.id"), index=True, nullable=False)
    role = db.Column(db.String(16), nullable=False)   # "user" | "assistant"
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

# Création des tables
with app.app_context():
    db.create_all()

# Configuration
IDLE_TIMEOUT = timedelta(minutes=30)

# Initialisation du système Lucie
try:
    openai_api_key = os.getenv("OPENAI_API_KEY")
    if not openai_api_key:
        raise ValueError("OPENAI_API_KEY non trouvée dans les variables d'environnement")
    
    # Initialisation du vector store (avec la clé API)
    vector_store = VectorStore(openai_api_key)
    
    # Initialisation du chat handler
    lucie = ChatHandler(openai_api_key, vector_store)
    
    print("✅ Système Lucie initialisé avec succès")
    
except Exception as e:
    print(f"❌ Erreur lors de l'initialisation de Lucie: {e}")
    lucie = None

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

@app.route("/")
def home():
    status = "✅ En ligne" if lucie else "❌ Erreur d'initialisation"
    return f"🌸 Assistant Lucie - Kimoky {status}"

@app.route("/chat", methods=["POST"])
def chat():
    """Endpoint principal du chat"""
    if not lucie:
        return jsonify({"response": "Le système Lucie n'est pas disponible actuellement. Veuillez nous excuser."}), 503
    
    try:
        # Vérification du format JSON
        if not request.is_json:
            return jsonify({"response": "Format de requête incorrect."}), 400
        
        data = request.get_json()
        message = data.get("message", "").strip()
        
        if not message:
            return jsonify({"response": "Votre message semble vide. Comment puis-je vous aider ? 🌸"}), 400
        
        # Gestion de la conversation
        conversation, session_id = get_or_create_conversation(data)
        
        # Obtenir la réponse de Lucie (votre système original)
        is_mobile = data.get("is_mobile", False)
        response = lucie.get_response(message, is_mobile=is_mobile)
        
        # Sauvegarder les messages en base de données
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
            "response": "Je rencontre une difficulté technique. Pouvez-vous réessayer dans un moment ? 💌"
        }), 500

@app.route("/health")
def health():
    """Endpoint de santé pour Render"""
    lucie_status = "ok" if lucie else "error"
    return jsonify({
        "status": "healthy", 
        "lucie": lucie_status,
        "timestamp": datetime.utcnow().isoformat()
    })

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
