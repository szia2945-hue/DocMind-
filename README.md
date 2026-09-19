# DocMind — Ask your documents anything

A RAG-based PDF Q&A chatbot built with **Flask**, **pypdf**, **HuggingFace Inference API** (embeddings), and **Groq** (LLM). No LangChain, no PyTorch, no local models — everything runs through simple API calls.

## Features

- Multi-document chat — select 2+ PDFs and ask one combined question across all of them
- Clickable page citations that open a live PDF preview (via pdf.js) of the exact source page
- Dark / light theme toggle (saved in your browser)
- Profile page — change your password
- Auto-generated document summary shown right after upload
- Voice input for questions (mic button, uses your browser's built-in speech recognition)
- Ask in English or Urdu — the AI replies in the same language
- Admin panel (first signed-up account is automatically the admin) — see total users/docs/questions and per-user breakdown
- Streaming, ChatGPT-style typing effect for answers

> **Upgrading from an older DocMind version?** The database schema changed (new columns for summaries, admin flag, multi-doc sources). Delete your old `docmind.db` (and `instance/docmind.db` if present) before running again — it will be recreated automatically, but you'll lose old history/documents.

---

## 1. Project Structure

```
docmind/
├── app.py                 # Main app + routes (dashboard, upload, chat, history)
├── auth.py                # Login / signup / logout blueprint
├── models.py               # User, Document, Chunk, ChatHistory tables
├── extensions.py           # db + login_manager instances
├── rag.py                   # PDF extraction, chunking, embeddings, similarity, Groq call
├── requirements.txt
├── .env.example
├── .gitignore
├── runtime.txt
├── templates/
│   ├── base.html
│   ├── login.html
│   ├── signup.html
│   ├── dashboard.html
│   ├── chat.html
│   └── history.html
├── static/
│   ├── css/style.css
│   └── js/main.js
└── uploads/                # uploaded PDFs land here (created automatically)
```

---

## 2. Getting Your Free API Keys

### Groq (LLM)
1. Go to https://console.groq.com/keys
2. Sign up (free), create an API key
3. Copy it — you'll use it as `GROQ_API_KEY`

### HuggingFace (Embeddings)
1. Go to https://huggingface.co/settings/tokens
2. Sign up (free), create a new **Read** token
3. Copy it — you'll use it as `HF_API_KEY`

> Note: the free HuggingFace Inference API can be slow to "cold start" the first time it's called — `rag.py` already retries automatically if this happens.

---

## 3. Local Setup (Windows 11)

```powershell
# 1. Open PowerShell in the docmind folder
cd path\to\docmind

# 2. Create a virtual environment
python -m venv venv

# 3. Activate it
venv\Scripts\activate

# 4. Install dependencies
pip install -r requirements.txt

# 5. Create your .env file
copy .env.example .env
# Now open .env in Notepad and paste your real GROQ_API_KEY and HF_API_KEY,
# and change SECRET_KEY to any random string.

# 6. Run the app
python app.py
```

Open your browser at **http://127.0.0.1:5000**

The SQLite database (`docmind.db`) and `uploads/` folder are created automatically on first run.

---

## 4. Testing Checklist

- [ ] Sign up a new account
- [ ] Log out, log back in with username **and** with email
- [ ] Upload a small text-based PDF (not a scanned image) — confirm success message with page/chunk counts
- [ ] Go to Chat page, select the document, ask a question that's clearly answered in the PDF
- [ ] Confirm the answer includes source page numbers
- [ ] Ask a question NOT covered in the PDF — confirm the bot says it can't find it (doesn't hallucinate)
- [ ] Check Dashboard — stats (documents/questions count) update correctly
- [ ] Go to History — confirm the question/answer appears
- [ ] Delete a history record — confirm it disappears
- [ ] Export CSV — open it in Excel and confirm columns are correct
- [ ] Delete a document — confirm its chunks are gone (ask a question again, should say document not found or dropdown updates)
- [ ] Try uploading a file > 10 MB — confirm friendly error, not a crash
- [ ] Try uploading a non-PDF file — confirm rejection

---

## 5. Deployment to PythonAnywhere (Free Tier)

1. **Create account**: https://www.pythonanywhere.com → sign up for a free "Beginner" account.

2. **Upload your code**:
   - Easiest: push your project to GitHub first (see step 6 below), then in PythonAnywhere open a **Bash console** and run:
     ```bash
     git clone https://github.com/YOUR_USERNAME/docmind.git
     ```

3. **Create a virtualenv** (in the Bash console):
   ```bash
   cd docmind
   mkvirtualenv --python=python3.11 docmind-env
   pip install -r requirements.txt
   ```
   (If `mkvirtualenv` isn't available, use: `python3.11 -m venv docmind-env && source docmind-env/bin/activate && pip install -r requirements.txt`)

4. **Set environment variables**: Since PythonAnywhere's free tier doesn't always load `.env` automatically, add this near the top of `app.py`'s `create_app()` is already handled via `python-dotenv`, but you must upload a real `.env` file (create it directly on PythonAnywhere via the Files tab — do NOT commit real keys to GitHub):
   - Go to the **Files** tab, navigate to `docmind/`, create a new file named `.env`, paste in your real keys (same format as `.env.example`).

5. **Configure the Web App**:
   - Go to the **Web** tab → **Add a new web app** → choose **Manual configuration** → Python 3.11.
   - Set **Source code** to `/home/YOUR_USERNAME/docmind`
   - Set **Working directory** to `/home/YOUR_USERNAME/docmind`
   - Edit the **WSGI configuration file** (link is on the Web tab) and replace its contents with:

     ```python
     import sys
     import os

     project_home = '/home/YOUR_USERNAME/docmind'
     if project_home not in sys.path:
         sys.path.insert(0, project_home)

     os.chdir(project_home)

     from app import app as application
     ```

   - Under **Virtualenv**, set the path to: `/home/YOUR_USERNAME/.virtualenvs/docmind-env`

6. **Reload** the web app (green button on the Web tab) and visit your `YOUR_USERNAME.pythonanywhere.com` URL.

> The SQLite database file will be created automatically in your project folder the first time the app runs — it persists as long as you don't delete it.

---

## 6. Pushing to GitHub

```bash
cd docmind
git init
git add .
git commit -m "Initial commit - DocMind RAG chatbot"
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/docmind.git
git push -u origin main
```

`.gitignore` already excludes `.env`, the SQLite database, and uploaded PDFs — so your secrets and user files never get pushed.

---

## 7. Common Errors & Fixes

| Error | Cause | Fix |
|---|---|---|
| `ModuleNotFoundError: No module named 'groq'` | Dependencies not installed in the active environment | Activate your venv, run `pip install -r requirements.txt` again |
| Upload succeeds but "Failed to process PDF: PDF se koi text extract nahi ho saka" | The PDF is a scanned image with no selectable text | pypdf can only extract real text layers, not images — use an OCR'd PDF instead |
| Chat returns "Failed to reach HuggingFace API" | HF API is cold-starting, rate-limited, or key is wrong | Wait a few seconds and retry (retry logic already built in); double check `HF_API_KEY` in `.env` |
| Groq error mentioning invalid API key | Wrong or expired `GROQ_API_KEY` | Regenerate the key at console.groq.com/keys and update `.env` |
| `sqlalchemy.exc.OperationalError: no such table` | Database wasn't initialized | Delete `docmind.db` and restart `python app.py` (tables auto-create on startup) |
| 413 error on upload | File bigger than 10 MB | Reduce PDF size or raise `MAX_UPLOAD_MB` in `.env` |
| Login redirects in a loop | `SECRET_KEY` changed between requests/restarts, invalidating sessions | Set a fixed `SECRET_KEY` in `.env` instead of leaving the default |
| Works locally but 500 error on PythonAnywhere | `.env` file missing on the server, or wrong WSGI path | Confirm `.env` exists in the project folder on PythonAnywhere; recheck WSGI file paths |

---

## 8. Security Notes

- Never commit your real `.env` file — only `.env.example` should be in version control.
- Passwords are hashed with Werkzeug's `generate_password_hash` — never stored in plain text.
- Each user can only see/query/delete their own documents and history (enforced via `user_id` filters on every query).
