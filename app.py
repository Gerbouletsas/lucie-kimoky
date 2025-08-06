from flask import Flask, request, jsonify
import os, uuid
from datetime import datetime, timedelta
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS
from flask import make_response, Response
from functools import wraps

app = Flask(__name__)

# CORS (ajuste les domaines si besoin)
CORS(app, resources={r"/chat": {"origins": ["https://kimoky.com","https://www.kimoky.com"]}})

# DB (Postgres en prod, SQLite local)
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
    conv.page_url = payload.get("page_url") or conv.page_url
    conv.user_agent = request.headers.get("User-Agent")
    conv.locale = payload.get("locale") or conv.locale
    conv.ip = request.headers.get("CF-Connecting-IP") or request.remote_addr
    db.session.commit()
    return conv, sid

@app.route("/")
def home():
    return "Bienvenue sur l'Assistant Kimoky !"

@app.route("/chat", methods=["POST"])
def chat():
    if request.content_type != 'application/json':
        return jsonify({"response": "Contenu non supporté. Utilisez 'application/json'."}), 415
    try:
        data = request.get_json(force=True)
        message = (data.get("message") or "").strip()
        if not message:
            return jsonify({"response": "Le message est vide."}), 400

        # 1) Conversation + log message client
        conv, sid = get_or_create_conversation(data)
        db.session.add(Message(conversation_id=conv.id, role="user", content=message))
        db.session.commit()

        # 2) Ta logique de réponse (prompt intact)
        response = f"Merci pour votre question : « {message} ». Notre conseillère vous répondra bientôt."

        # 3) Log réponse assistante
        db.session.add(Message(conversation_id=conv.id, role="assistant", content=response))
        db.session.commit()

        # 4) Cookie de session + retour
        resp = make_response(jsonify({
            "response": response,
            "conversation_id": conv.id,
            "session_id": sid
        }))
        resp.set_cookie("lucie_sid", sid, max_age=60*60*24*180, samesite="Lax")
        return resp

    except Exception as e:
        return jsonify({"response": f"Erreur côté serveur : {str(e)}"}), 500

# --- Admin (Basic Auth) ---
ADMIN_USER = os.getenv("ADMIN_USER", "admin")
ADMIN_PASS = os.getenv("ADMIN_PASS", "change-me")

def require_auth(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        auth = request.authorization
        ok = auth and auth.username == ADMIN_USER and auth.password == ADMIN_PASS
        if not ok:
            return Response("Auth required", 401, {"WWW-Authenticate": 'Basic realm="Kimoky Admin"'})
        return f(*args, **kwargs)
    return wrapper

# --- Export CSV de tous les messages ---
@app.route("/admin/export.csv", methods=["GET"])
@require_auth
def export_csv():
    import csv
    from io import StringIO
    q = (db.session.query(Message, Conversation)
         .join(Conversation, Message.conversation_id == Conversation.id)
         .order_by(Message.created_at.asc()))
    sio = StringIO()
    w = csv.writer(sio)
    w.writerow(["conversation_id","session_id","role","content","created_at","page_url","locale","ip","user_agent"])
    for m, c in q.all():
        w.writerow([c.id, c.session_id, m.role, m.content, m.created_at.isoformat(),
                    c.page_url or "", c.locale or "", c.ip or "", (c.user_agent or "")[:2000]])
    resp = make_response(sio.getvalue())
    resp.headers["Content-Type"] = "text/csv; charset=utf-8"
    resp.headers["Content-Disposition"] = "attachment; filename=questions_clients.csv"
    return resp

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
