# ===========================================
# app.py
# DocMind ki main application file.
# Yahan app factory, main blueprint (dashboard/upload/chat/history)
# aur error handlers define hain.
# ===========================================

import os
import io
import csv
import functools
from datetime import datetime

from flask import (
    Flask, Blueprint, render_template, request, redirect,
    url_for, flash, jsonify, Response, send_from_directory, stream_with_context, abort
)
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename
from werkzeug.security import check_password_hash
from dotenv import load_dotenv

from extensions import db, login_manager
from models import User, Document, Chunk, ChatHistory
from rag import process_document, get_embedding, find_top_chunks, ask_groq, ask_groq_stream, generate_summary
from auth import auth_bp

# .env file se environment variables load karo
load_dotenv()

ALLOWED_EXTENSIONS = {"pdf"}


# ===========================================
# APP FACTORY
# ===========================================
def create_app():
    app = Flask(__name__)

    # --- Config ---
    app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "dev-secret-key-change-me")
    app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv("DATABASE_URL", "sqlite:///docmind.db")
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["UPLOAD_FOLDER"] = os.getenv("UPLOAD_FOLDER", "uploads")
    max_mb = int(os.getenv("MAX_UPLOAD_MB", "10"))
    app.config["MAX_CONTENT_LENGTH"] = max_mb * 1024 * 1024

    # Upload folder create karo agar exist nahi karta
    os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)

    # --- Extensions init ---
    db.init_app(app)
    login_manager.init_app(app)

    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))

    # --- Blueprints register ---
    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)

    # --- Database tables create (agar exist nahi karte) ---
    with app.app_context():
        db.create_all()

    # --- Error handlers ---
    @app.errorhandler(413)
    def file_too_large(e):
        flash("File is too large. Maximum upload size is 10 MB.", "error")
        return redirect(url_for("main.dashboard")), 413

    @app.errorhandler(404)
    def not_found(e):
        return render_template("base.html", error_message="Page not found (404)."), 404

    @app.errorhandler(500)
    def server_error(e):
        return render_template("base.html", error_message="Internal server error. Please try again."), 500

    return app


# ===========================================
# MAIN BLUEPRINT - dashboard, upload, chat, history
# ===========================================
main_bp = Blueprint("main", __name__)


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def admin_required(view_func):
    """Decorator - sirf is_admin=True users ko route access karne deta hai."""
    @functools.wraps(view_func)
    @login_required
    def wrapped(*args, **kwargs):
        if not current_user.is_admin:
            flash("You don't have permission to access the admin panel.", "error")
            return redirect(url_for("main.dashboard"))
        return view_func(*args, **kwargs)
    return wrapped


@main_bp.route("/")
def index():
    # Root URL -> agar login hai to dashboard, warna login page
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))
    return redirect(url_for("auth.login"))


@main_bp.route("/dashboard")
@login_required
def dashboard():
    # User ke tamam documents (naye pehle)
    documents = Document.query.filter_by(user_id=current_user.id).order_by(Document.uploaded_at.desc()).all()

    # Recent 5 chats
    recent_chats = ChatHistory.query.filter_by(user_id=current_user.id).order_by(ChatHistory.created_at.desc()).limit(5).all()

    # Statistics
    total_docs = len(documents)
    total_questions = ChatHistory.query.filter_by(user_id=current_user.id).count()

    return render_template(
        "dashboard.html",
        documents=documents,
        recent_chats=recent_chats,
        total_docs=total_docs,
        total_questions=total_questions,
    )


@main_bp.route("/upload", methods=["POST"])
@login_required
def upload_document():
    """PDF upload handle karta hai: save -> extract -> chunk -> embed -> DB me save."""
    if "pdf_file" not in request.files:
        flash("No file selected.", "error")
        return redirect(url_for("main.dashboard"))

    file = request.files["pdf_file"]

    if file.filename == "":
        flash("No file selected.", "error")
        return redirect(url_for("main.dashboard"))

    if not allowed_file(file.filename):
        flash("Only PDF files are allowed.", "error")
        return redirect(url_for("main.dashboard"))

    # Filename safe banate hain aur unique prefix lagate hain (overwrite se bachne ke liye)
    safe_name = secure_filename(file.filename)
    unique_name = f"{current_user.id}_{int(datetime.utcnow().timestamp())}_{safe_name}"
    from flask import current_app
    filepath = os.path.join(current_app.config["UPLOAD_FOLDER"], unique_name)
    file.save(filepath)

    hf_api_key = os.getenv("HF_API_KEY")
    if not hf_api_key:
        flash("Server misconfiguration: HF_API_KEY missing. Contact admin.", "error")
        return redirect(url_for("main.dashboard"))

    # --- RAG pipeline: extract -> chunk -> embed ---
    processed_chunks, error = process_document(filepath, hf_api_key)

    if error:
        # Agar processing fail hui to uploaded file delete kar do
        if os.path.exists(filepath):
            os.remove(filepath)
        flash(f"Failed to process PDF: {error}", "error")
        return redirect(url_for("main.dashboard"))

    # Page count = unique page numbers jo chunks me hain
    page_count = len(set(c["page"] for c in processed_chunks))

    # --- Auto-summary generate karo (Groq se) ---
    # Ye optional hai - fail ho jaye to bhi upload rukna nahi chahiye.
    groq_api_key = os.getenv("GROQ_API_KEY")
    summary_text = None
    if groq_api_key:
        try:
            from rag import extract_text_from_pdf
            pages_for_summary = extract_text_from_pdf(filepath)
            summary_text = generate_summary(pages_for_summary, groq_api_key)
        except Exception as e:
            print(f"[app.py] Summary generation skipped due to error: {e}")

    # --- Document record DB me banao ---
    new_doc = Document(
        user_id=current_user.id,
        filename=file.filename,
        filepath=filepath,
        page_count=page_count,
        chunk_count=len(processed_chunks),
        summary=summary_text,
    )
    db.session.add(new_doc)
    db.session.flush()  # taake new_doc.id mil jaye chunks ke liye

    for c in processed_chunks:
        chunk_row = Chunk(document_id=new_doc.id, text=c["text"], page_number=c["page"])
        chunk_row.set_embedding_list(c["embedding"])
        db.session.add(chunk_row)

    db.session.commit()

    flash(f"'{file.filename}' uploaded successfully! ({page_count} pages, {len(processed_chunks)} chunks)", "success")
    return redirect(url_for("main.dashboard"))


@main_bp.route("/document/<int:doc_id>/delete", methods=["POST"])
@login_required
def delete_document(doc_id):
    doc = Document.query.filter_by(id=doc_id, user_id=current_user.id).first_or_404()

    # File disk se bhi delete karo
    if os.path.exists(doc.filepath):
        try:
            os.remove(doc.filepath)
        except OSError:
            pass

    db.session.delete(doc)   # cascade se chunks bhi delete ho jayenge
    db.session.commit()

    flash(f"'{doc.filename}' deleted.", "success")
    return redirect(url_for("main.dashboard"))


@main_bp.route("/chat")
@login_required
def chat_page():
    documents = Document.query.filter_by(user_id=current_user.id).order_by(Document.uploaded_at.desc()).all()
    if not documents:
        flash("Please upload a PDF document first to start chatting.", "error")
        return redirect(url_for("main.dashboard"))
    return render_template("chat.html", documents=documents)


@main_bp.route("/api/ask", methods=["POST"])
@login_required
def api_ask():
    """
    Streaming AJAX endpoint jo chat.html se call hota hai.
    Expects JSON: {"question": "...", "document_ids": [3, 7]}   (multi-doc support)
                  (backward-compatible: "document_id": 3 bhi accept hota hai)

    Response: text/plain, newline-delimited JSON (NDJSON) - har line ek event hai:
      {"type": "token", "text": "..."}          -> har token jaise AI likhta hai (typing effect)
      {"type": "done", "sources": [...]}        -> stream khatam, sources ki final list
      {"type": "error", "message": "..."}       -> koi bhi error
    """
    data = request.get_json(silent=True) or {}
    question = (data.get("question") or "").strip()

    # Multi-doc aur single-doc (legacy) dono support karo
    document_ids = data.get("document_ids")
    if not document_ids:
        single_id = data.get("document_id")
        document_ids = [single_id] if single_id else []
    document_ids = [int(d) for d in document_ids if d]

    if not question:
        return jsonify({"error": "Question cannot be empty."}), 400
    if not document_ids:
        return jsonify({"error": "Please select at least one document."}), 400

    # Sirf current_user ke apne documents allow karo (security check)
    docs = Document.query.filter(Document.id.in_(document_ids), Document.user_id == current_user.id).all()
    if not docs:
        return jsonify({"error": "Document(s) not found."}), 404
    valid_doc_ids = [d.id for d in docs]

    hf_api_key = os.getenv("HF_API_KEY")
    groq_api_key = os.getenv("GROQ_API_KEY")
    if not hf_api_key or not groq_api_key:
        return jsonify({"error": "Server misconfiguration: API keys missing."}), 500

    # --- Step 1: Sawal ka embedding banao (streaming shuru hone se pehle) ---
    query_embedding = get_embedding(question, hf_api_key)
    if query_embedding is None:
        return jsonify({"error": "Failed to reach HuggingFace API. Please try again shortly."}), 503

    # --- Step 2: Top-K relevant chunks dhoondo (SAB selected documents me se) ---
    all_chunks = Chunk.query.filter(Chunk.document_id.in_(valid_doc_ids)).all()
    top_chunks = find_top_chunks(query_embedding, all_chunks, top_k=5 if len(valid_doc_ids) > 1 else 3)

    def generate():
        import json as _json
        full_answer = ""
        try:
            for token in ask_groq_stream(question, top_chunks, groq_api_key):
                full_answer += token
                yield _json.dumps({"type": "token", "text": token}) + "\n"
        except Exception as e:
            print(f"[app.py] Streaming error: {e}")
            yield _json.dumps({"type": "error", "message": f"Error contacting the AI model: {e}"}) + "\n"
            return

        # Stream khatam - sources nikal ke history save karo
        _context_text, sources = _build_sources_only(top_chunks)

        history_row = ChatHistory(
            user_id=current_user.id,
            document_id=valid_doc_ids[0],
            document_ids=",".join(str(d) for d in valid_doc_ids),
            question=question,
            answer=full_answer,
            source_pages=", ".join(f"{s['filename']} p.{s['page']}" for s in sources),
        )
        history_row.set_sources(sources)
        db.session.add(history_row)
        db.session.commit()

        yield _json.dumps({"type": "done", "sources": sources}) + "\n"

    return Response(stream_with_context(generate()), mimetype="text/plain")


def _build_sources_only(context_chunks):
    """api_ask ke liye chota helper - rag.py wala _build_context_and_sources reuse karta hai."""
    from rag import _build_context_and_sources
    return _build_context_and_sources(context_chunks)


@main_bp.route("/document/<int:doc_id>/file")
@login_required
def serve_document_file(doc_id):
    """
    PDF preview feature ke liye - pdf.js is route se file fetch karta hai
    taake chat me jis page se answer aya usay render kar sake.
    Ownership check zaroori hai taake koi doosre user ki file na dekh sake.
    """
    doc = Document.query.filter_by(id=doc_id, user_id=current_user.id).first()
    if not doc:
        abort(404)

    directory = os.path.dirname(os.path.abspath(doc.filepath))
    filename = os.path.basename(doc.filepath)
    return send_from_directory(directory, filename, mimetype="application/pdf")


@main_bp.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    """User profile page - password change yahan se hoti hai."""
    if request.method == "POST":
        current_password = request.form.get("current_password", "")
        new_password = request.form.get("new_password", "")
        confirm_password = request.form.get("confirm_password", "")

        if not current_user.check_password(current_password):
            flash("Current password is incorrect.", "error")
            return redirect(url_for("main.profile"))

        if len(new_password) < 6:
            flash("New password must be at least 6 characters long.", "error")
            return redirect(url_for("main.profile"))

        if new_password != confirm_password:
            flash("New passwords do not match.", "error")
            return redirect(url_for("main.profile"))

        current_user.set_password(new_password)
        db.session.commit()
        flash("Password updated successfully.", "success")
        return redirect(url_for("main.profile"))

    doc_count = Document.query.filter_by(user_id=current_user.id).count()
    question_count = ChatHistory.query.filter_by(user_id=current_user.id).count()
    return render_template("profile.html", doc_count=doc_count, question_count=question_count)


@main_bp.route("/admin")
@admin_required
def admin_panel():
    """
    Admin panel - sirf is_admin=True users dekh sakte hain.
    Sabse pehla signup automatically admin ban jata hai (auth.py me).
    """
    total_users = User.query.count()
    total_docs = Document.query.count()
    total_questions = ChatHistory.query.count()

    # Har user ka breakdown (username, doc count, question count)
    users = User.query.order_by(User.created_at.asc()).all()
    user_stats = []
    for u in users:
        user_stats.append({
            "username": u.username,
            "email": u.email,
            "is_admin": u.is_admin,
            "joined": u.created_at,
            "doc_count": Document.query.filter_by(user_id=u.id).count(),
            "question_count": ChatHistory.query.filter_by(user_id=u.id).count(),
        })

    return render_template(
        "admin.html",
        total_users=total_users,
        total_docs=total_docs,
        total_questions=total_questions,
        user_stats=user_stats,
    )


@main_bp.route("/history")
@login_required
def history():
    all_history = ChatHistory.query.filter_by(user_id=current_user.id).order_by(ChatHistory.created_at.desc()).all()
    return render_template("history.html", history=all_history)


@main_bp.route("/history/<int:record_id>/delete", methods=["POST"])
@login_required
def delete_history(record_id):
    record = ChatHistory.query.filter_by(id=record_id, user_id=current_user.id).first_or_404()
    db.session.delete(record)
    db.session.commit()
    flash("Record deleted.", "success")
    return redirect(url_for("main.history"))


@main_bp.route("/history/export")
@login_required
def export_history():
    """Chat history ko CSV file ke tor pe export karta hai."""
    records = ChatHistory.query.filter_by(user_id=current_user.id).order_by(ChatHistory.created_at.desc()).all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Date", "Question", "Answer", "Source Pages"])

    for r in records:
        writer.writerow([
            r.created_at.strftime("%Y-%m-%d %H:%M:%S"),
            r.question,
            r.answer,
            r.source_pages,
        ])

    csv_data = output.getvalue()
    output.close()

    return Response(
        csv_data,
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=docmind_history.csv"},
    )


# ===========================================
# LOCAL RUN (python app.py)
# ===========================================
app = create_app()

if __name__ == "__main__":
    import webbrowser
    import threading

    def open_browser():
        webbrowser.open("http://127.0.0.1:5000")

    # Server start hone ke thodi der baad browser khud khul jayega
    threading.Timer(1.5, open_browser).start()
    app.run(debug=True, host="127.0.0.1", port=5000)
