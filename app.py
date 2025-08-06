from flask import Flask, request, jsonify

# 👇 Ajoute ces imports immédiatement après
import os, uuid
from datetime import datetime, timedelta
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS
from flask import make_response

app = Flask(__name__)

# Autoriser ton site (ajuste si besoin)
CORS(app, resources={r"/chat": {"origins": ["https://kimoky.com","https://www.kimoky.com"]}})

# DB (Postgres en prod, SQLite en local)
db_uri = os.getenv("DATABASE_URL", "sqlite:///kimoky_chat.db")
if db_uri.startswith("postgres://"):
    db_uri = db_uri.replace("postgres://", "postgresql://", 1)
app.config["SQLALCHEMY_DATABASE_URI"] = db_uri
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
db = SQLAlchemy(app)
# --- Modèles ---
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

with app.app_context():
    db.create_all()

from flask import make_response
IDLE_TIMEOUT = timedelta(minutes=30)

def get_or_create_conversation(payload):
    sid = (payload.get("session_id") or request.cookies.get("lucie_sid") or uuid.uuid4().hex)[:64]
    now = datetime.utcnow()
    conv = (Conversation.query
            .filter_by(session_id=sid)
            .order_by(Conversation.last_activity_at.desc())
            .first())
    if not conv or (now - conv.last_activity_at) > IDLE_TIMEOUT:
        conv = Conversation(session_id=sid, started_at=now)
        db.session.add(conv)
    conv.last_activity_at = now
    # Métadonnées (facultatif selon ce que tu envoies du front)
    conv.page_url = payload.get("page_url") or conv.page_url
    conv.user_agent = request.headers.get("User-Agent")
    conv.locale = payload.get("locale") or conv.locale
    conv.ip = request.headers.get("CF-Connecting-IP") or request.remote_addr
    db.session.commit()
    return conv, sid

@app.route("/")
def home():
    return "Bienvenue sur l'Assistant Kimoky !" def chat():

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)

