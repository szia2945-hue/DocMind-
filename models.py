# ===========================================
# models.py
# Database ke tamam tables (models) yahan define hain:
# User, Document, Chunk, ChatHistory
# ===========================================

import json
from datetime import datetime
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

from extensions import db


class User(UserMixin, db.Model):
    """
    User table - login/signup ke liye.
    UserMixin Flask-Login ko is_authenticated, get_id() waghera
    automatically de deta hai.
    """
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    is_admin = db.Column(db.Boolean, default=False)   # Admin panel access ke liye
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationships - ek user ke multiple documents aur chats ho sakte hain
    documents = db.relationship("Document", backref="user", lazy=True, cascade="all, delete-orphan")
    chats = db.relationship("ChatHistory", backref="user", lazy=True, cascade="all, delete-orphan")

    def set_password(self, raw_password):
        # Password ko hash karke store karte hain, plain text kabhi nahi
        self.password_hash = generate_password_hash(raw_password)

    def check_password(self, raw_password):
        # Login ke waqt hash compare karta hai
        return check_password_hash(self.password_hash, raw_password)

    def __repr__(self):
        return f"<User {self.username}>"


class Document(db.Model):
    """
    Document table - har upload ki gayi PDF ka record.
    """
    __tablename__ = "documents"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    filename = db.Column(db.String(255), nullable=False)      # original file naam
    filepath = db.Column(db.String(500), nullable=False)      # disk pe kahan saved hai
    page_count = db.Column(db.Integer, default=0)
    chunk_count = db.Column(db.Integer, default=0)
    summary = db.Column(db.Text, nullable=True)   # Upload ke waqt auto-generate hone wala summary
    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Ek document ke multiple chunks hote hain
    chunks = db.relationship("Chunk", backref="document", lazy=True, cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Document {self.filename}>"


class Chunk(db.Model):
    """
    Chunk table - PDF ke text ke chote chote pieces (500 chars),
    unka embedding vector (JSON string ke tor pe) yahan store hota hai.
    """
    __tablename__ = "chunks"

    id = db.Column(db.Integer, primary_key=True)
    document_id = db.Column(db.Integer, db.ForeignKey("documents.id"), nullable=False)
    text = db.Column(db.Text, nullable=False)
    page_number = db.Column(db.Integer, nullable=False)
    embedding = db.Column(db.Text, nullable=False)   # JSON string: "[0.123, -0.45, ...]"

    def get_embedding_list(self):
        """Embedding string ko wapas Python list me convert karta hai."""
        return json.loads(self.embedding)

    def set_embedding_list(self, vector):
        """Python list ko JSON string bana ke store karta hai."""
        self.embedding = json.dumps(vector)

    def __repr__(self):
        return f"<Chunk doc={self.document_id} page={self.page_number}>"


class ChatHistory(db.Model):
    """
    ChatHistory table - har sawal-jawab ka record,
    History page aur CSV export ke liye use hota hai.

    Ab multi-document questions bhi support karta hai (document_ids me
    comma-separated IDs), aur sources_json me har source ka
    document + page detail (preview feature ke liye) store hota hai.
    """
    __tablename__ = "chat_history"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    document_id = db.Column(db.Integer, db.ForeignKey("documents.id"), nullable=True)  # legacy / primary doc
    document_ids = db.Column(db.String(500), default="")   # e.g. "3,7,9" - jab multiple docs select huay
    question = db.Column(db.Text, nullable=False)
    answer = db.Column(db.Text, nullable=False)
    source_pages = db.Column(db.String(255), default="")   # human-readable, e.g. "report.pdf p.2, notes.pdf p.1"
    sources_json = db.Column(db.Text, default="[]")        # [{"document_id":3,"filename":"a.pdf","page":2}, ...]
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def get_sources(self):
        """sources_json ko Python list me convert karta hai (preview feature ke liye)."""
        try:
            return json.loads(self.sources_json or "[]")
        except (ValueError, TypeError):
            return []

    def set_sources(self, sources_list):
        """List of dicts ko JSON string bana ke store karta hai."""
        self.sources_json = json.dumps(sources_list)

    def __repr__(self):
        return f"<ChatHistory user={self.user_id} q={self.question[:30]}>"
