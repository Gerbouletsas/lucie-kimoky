from flask import Flask, request, jsonify
import os, uuid
from datetime import datetime, timedelta
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS
from flask import make_response, send_file
import json
import csv
from io import StringIO, BytesIO

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

@app.route("/admin")
def admin_dashboard():
    """Interface d'administration pour consulter les conversations"""
    try:
        # Statistiques générales
        total_conversations = Conversation.query.count()
        total_messages = Message.query.count()
        
        # Conversations récentes (10 dernières)
        recent_conversations = (Conversation.query
                              .order_by(Conversation.last_activity_at.desc())
                              .limit(10)
                              .all())
        
        # Messages récents
        recent_messages = (Message.query
                         .order_by(Message.created_at.desc())
                         .limit(20)
                         .all())
        
        # Générer HTML
        html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Admin - Conversations Lucie</title>
            <style>
                body {{ font-family: Arial, sans-serif; margin: 40px; background: #f5f5f5; }}
                .container {{ max-width: 1200px; margin: 0 auto; background: white; padding: 30px; border-radius: 10px; }}
                h1 {{ color: #333; border-bottom: 2px solid #007bff; padding-bottom: 10px; }}
                h2 {{ color: #666; margin-top: 30px; }}
                .stats {{ display: flex; gap: 20px; margin: 20px 0; }}
                .stat-box {{ background: #007bff; color: white; padding: 20px; border-radius: 8px; text-align: center; flex: 1; }}
                .export-buttons {{ margin: 20px 0; text-align: right; }}
                .export-btn {{ color: white; padding: 10px 15px; text-decoration: none; border-radius: 5px; margin: 0 5px; display: inline-block; }}
                .export-btn:hover {{ opacity: 0.8; }}
                .conversation {{ border: 1px solid #ddd; margin: 10px 0; padding: 15px; border-radius: 5px; background: #fafafa; }}
                .message {{ margin: 10px 0; padding: 10px; border-radius: 5px; }}
                .user {{ background: #e3f2fd; border-left: 4px solid #2196f3; }}
                .assistant {{ background: #f1f8e9; border-left: 4px solid #4caf50; }}
                .timestamp {{ color: #666; font-size: 12px; }}
                table {{ width: 100%; border-collapse: collapse; margin: 20px 0; }}
                th, td {{ padding: 12px; text-align: left; border-bottom: 1px solid #ddd; }}
                th {{ background: #f8f9fa; }}
                .truncate {{ max-width: 300px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
            </style>
        </head>
        <body>
            <div class="container">
                <h1>🌸 Administration Lucie - Conversations</h1>

                <div class="export-buttons">
                    <a href="/admin/export/json" class="export-btn" style="background: #28a745;">
                        📄 Export JSON
                    </a>
                    <a href="/admin/export/csv" class="export-btn" style="background: #17a2b8;">
                        📊 Export CSV
                    </a>
                    <a href="/admin/export/excel" class="export-btn" style="background: #007bff;">
                        📈 Export Excel
                    </a>
                </div>
                
                <div class="stats">
                    <div class="stat-box">
                        <h3>{total_conversations}</h3>
                        <p>Conversations totales</p>
                    </div>
                    <div class="stat-box">
                        <h3>{total_messages}</h3>
                        <p>Messages totaux</p>
                    </div>
                    <div class="stat-box">
                        <h3>{total_messages // 2 if total_messages > 0 else 0}</h3>
                        <p>Questions clients</p>
                    </div>
                </div>
                
                <h2>📊 Conversations récentes</h2>
                <table>
                    <tr>
                        <th>Session ID</th>
                        <th>Début</th>
                        <th>Dernière activité</th>
                        <th>Page</th>
                        <th>Messages</th>
                    </tr>
        """
        
        for conv in recent_conversations:
            message_count = Message.query.filter_by(conversation_id=conv.id).count()
            page_url = conv.page_url or "Non spécifiée"
            if page_url and len(page_url) > 50:
                page_url = page_url[:50] + "..."
                
            html += f"""
                    <tr>
                        <td><a href="/admin/conversation/{conv.session_id}" style="color: #007bff; text-decoration: none;">{conv.session_id[:12]}...</a></td>
                        <td>{conv.started_at.strftime('%d/%m/%Y %H:%M')}</td>
                        <td>{conv.last_activity_at.strftime('%d/%m/%Y %H:%M')}</td>
                        <td class="truncate">{page_url}</td>
                        <td>{message_count}</td>
                    </tr>
            """
        
        html += """
                </table>
                
                <h2>💬 Messages récents</h2>
        """
        
        for msg in recent_messages:
            # Récupérer la conversation pour ce message
            conv = Conversation.query.get(msg.conversation_id)
            role_class = msg.role
            role_emoji = "👤" if msg.role == "user" else "🌸"
            role_text = "Client" if msg.role == "user" else "Lucie"
            
            content = msg.content
            if len(content) > 200:
                content = content[:200] + "..."
            
            page_info = f" - {conv.page_url}" if conv and conv.page_url else ""
            
            html += f"""
                <div class="message {role_class}">
                    <strong>{role_emoji} {role_text}</strong>
                    <span class="timestamp">({msg.created_at.strftime('%d/%m/%Y %H:%M')}{page_info})</span>
                    <p>{content}</p>
                </div>
            """
        
        html += """
            </div>
        </body>
        </html>
        """
        
        return html
        
    except Exception as e:
        return f"<h1>Erreur</h1><p>{str(e)}</p>"

@app.route("/admin/conversation/<session_id>")
def view_conversation(session_id):
    """Voir une conversation complète"""
    try:
        conv = Conversation.query.filter_by(session_id=session_id).first()
        if not conv:
            return "<h1>Conversation non trouvée</h1>"
            
        messages = (Message.query
                   .filter_by(conversation_id=conv.id)
                   .order_by(Message.created_at.asc())
                   .all())
        
        html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Conversation {session_id}</title>
            <style>
                body {{ font-family: Arial, sans-serif; margin: 40px; background: #f5f5f5; }}
                .container {{ max-width: 800px; margin: 0 auto; background: white; padding: 30px; border-radius: 10px; }}
                .message {{ margin: 15px 0; padding: 15px; border-radius: 8px; }}
                .user {{ background: #e3f2fd; border-left: 4px solid #2196f3; }}
                .assistant {{ background: #f1f8e9; border-left: 4px solid #4caf50; }}
                .timestamp {{ color: #666; font-size: 12px; margin-bottom: 5px; }}
                .back {{ color: #007bff; text-decoration: none; }}
            </style>
        </head>
        <body>
            <div class="container">
                <a href="/admin" class="back">← Retour au dashboard</a>
                <h1>💬 Conversation {session_id[:12]}...</h1>
                <p><strong>Débutée :</strong> {conv.started_at.strftime('%d/%m/%Y à %H:%M')}</p>
                <p><strong>Dernière activité :</strong> {conv.last_activity_at.strftime('%d/%m/%Y à %H:%M')}</p>
                {f'<p><strong>Page :</strong> {conv.page_url}</p>' if conv.page_url else ''}
                
                <hr>
        """
        
        for msg in messages:
            role_emoji = "👤" if msg.role == "user" else "🌸"
            role_text = "Client" if msg.role == "user" else "Lucie"
            
            html += f"""
                <div class="message {msg.role}">
                    <div class="timestamp">{role_emoji} {role_text} - {msg.created_at.strftime('%d/%m/%Y à %H:%M:%S')}</div>
                    <p>{msg.content}</p>
                </div>
            """
        
        html += """
            </div>
        </body>
        </html>
        """
        
        return html
        
    except Exception as e:
        return f"<h1>Erreur</h1><p>{str(e)}</p>"

@app.route("/admin/export/json")
def export_json():
    """Export des conversations au format JSON"""
    try:
        conversations = Conversation.query.all()
        data = []
        
        for conv in conversations:
            messages = Message.query.filter_by(conversation_id=conv.id).order_by(Message.created_at.asc()).all()
            
            conv_data = {
                "session_id": conv.session_id,
                "started_at": conv.started_at.isoformat(),
                "last_activity_at": conv.last_activity_at.isoformat(),
                "page_url": conv.page_url,
                "user_agent": conv.user_agent,
                "locale": conv.locale,
                "ip": conv.ip,
                "messages": [
                    {
                        "role": msg.role,
                        "content": msg.content,
                        "created_at": msg.created_at.isoformat()
                    }
                    for msg in messages
                ]
            }
            data.append(conv_data)
        
        # Créer le fichier JSON
        json_data = json.dumps(data, indent=2, ensure_ascii=False)
        
        # Créer un objet BytesIO
        output = BytesIO()
        output.write(json_data.encode('utf-8'))
        output.seek(0)
        
        return send_file(
            output,
            as_attachment=True,
            download_name=f'conversations_lucie_{datetime.now().strftime("%Y%m%d_%H%M%S")}.json',
            mimetype='application/json'
        )
        
    except Exception as e:
        return f"<h1>Erreur d'export JSON</h1><p>{str(e)}</p>"

@app.route("/admin/export/csv")
def export_csv():
    """Export des conversations au format CSV"""
    try:
        # Récupérer tous les messages (sans jointure problématique)
        messages = Message.query.order_by(Message.created_at.asc()).all()
        
        output = StringIO()
        writer = csv.writer(output)
        
        # En-têtes
        writer.writerow([
            'Date/Heure',
            'Session ID',
            'Role',
            'Message',
            'Page URL',
            'Locale',
            'IP'
        ])
        
        # Données
        for msg in messages:
            # Récupérer la conversation associée
            conv = Conversation.query.get(msg.conversation_id)
            
            writer.writerow([
                msg.created_at.strftime('%d/%m/%Y %H:%M:%S'),
                conv.session_id if conv else 'Inconnu',
                'Client' if msg.role == 'user' else 'Lucie',
                msg.content,
                conv.page_url if conv else '',
                conv.locale if conv else '',
                conv.ip if conv else ''
            ])
        
        # Créer BytesIO à partir du StringIO
        output.seek(0)
        mem = BytesIO()
        mem.write(output.getvalue().encode('utf-8'))
        mem.seek(0)
        
        return send_file(
            mem,
            as_attachment=True,
            download_name=f'conversations_lucie_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv',
            mimetype='text/csv'
        )
        
    except Exception as e:
        return f"<h1>Erreur d'export CSV</h1><p>{str(e)}</p>"

@app.route("/admin/export/excel")
def export_excel():
    """Export des conversations au format Excel"""
    try:
        import pandas as pd
        
        # Récupérer tous les messages
        messages = Message.query.order_by(Message.created_at.asc()).all()
        
        # Préparer les données pour pandas
        data = []
        for msg in messages:
            # Récupérer la conversation associée
            conv = Conversation.query.get(msg.conversation_id)
            
            data.append({
                'Date/Heure': msg.created_at.strftime('%d/%m/%Y %H:%M:%S'),
                'Session ID': conv.session_id if conv else 'Inconnu',
                'Role': 'Client' if msg.role == 'user' else 'Lucie',
                'Message': msg.content,
                'Page URL': conv.page_url if conv else '',
                'Locale': conv.locale if conv else '',
                'IP': conv.ip if conv else '',
                'Durée session (min)': round((conv.last_activity_at - conv.started_at).total_seconds() / 60, 1) if conv else 0
            })
        
        # Créer le DataFrame
        df = pd.DataFrame(data)
        
        # Créer le fichier Excel en mémoire
        output = BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df.to_excel(writer, sheet_name='Conversations', index=False)
            
            # Ajouter une feuille avec les statistiques
            stats_data = {
                'Métrique': [
                    'Nombre total de conversations',
                    'Nombre total de messages',
                    'Nombre de questions clients'
                ],
                'Valeur': [
                    Conversation.query.count(),
                    Message.query.count(),
                    Message.query.filter_by(role='user').count()
                ]
            }
            stats_df = pd.DataFrame(stats_data)
            stats_df.to_excel(writer, sheet_name='Statistiques', index=False)
        
        output.seek(0)
        
        return send_file(
            output,
            as_attachment=True,
            download_name=f'conversations_lucie_{datetime.now().strftime("%Y%m%d_%H%M%S")}.xlsx',
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )
        
    except ImportError:
        return "<h1>Erreur</h1><p>Pour utiliser l'export Excel, ajoutez 'openpyxl' à votre requirements.txt</p>"
    except Exception as e:
        return f"<h1>Erreur d'export Excel</h1><p>{str(e)}</p>"
        
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
