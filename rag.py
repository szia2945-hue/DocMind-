# ===========================================
# rag.py
# Ye file DocMind ka "dimaag" hai - RAG pipeline yahan implement hai.
# Koi LangChain nahi - sab kuch direct API calls aur numpy se.
#
# Steps:
# 1. extract_text_from_pdf()   -> PDF se text nikalna (page-wise)
# 2. chunk_text()              -> Text ko 500-char chunks me todna (50 overlap)
# 3. get_embedding()           -> HuggingFace API se embedding lena (retry ke sath)
# 4. cosine_similarity()       -> Do vectors ke beech similarity nikalna
# 5. find_top_chunks()         -> Sawal se sabse relevant chunks dhoondna
# 6. ask_groq()                -> Groq LLM ko context + sawal bhej ke jawab lena
# ===========================================

import os
import time
import json
import numpy as np
from pypdf import PdfReader
from groq import Groq
from huggingface_hub import InferenceClient

# --- Config / constants ---
# NOTE: HuggingFace ne purana "api-inference.huggingface.co" REST endpoint
# band kar diya hai (2026 me deprecated, DNS record tak nahi bacha).
# Ab embeddings huggingface_hub ke InferenceClient ke zariye milte hain.
HF_EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
CHUNK_SIZE = 500
CHUNK_OVERLAP = 50
TOP_K = 3                       # kitne top chunks context me bhejne hain
MAX_RETRIES = 3                 # HF API fail ho to kitni baar retry karein
RETRY_DELAY_SECONDS = 2

GROQ_MODEL = "openai/gpt-oss-20b"


# ===========================================
# STEP 1: PDF se text extract karna (page number ke sath)
# ===========================================
def extract_text_from_pdf(filepath):
    """
    Returns: list of dicts -> [{"page": 1, "text": "..."}, {"page": 2, "text": "..."}, ...]
    Har page ka text alag rakha jata hai taake source citation mil sake.
    """
    pages = []
    reader = PdfReader(filepath)
    for i, page in enumerate(reader.pages):
        try:
            text = page.extract_text() or ""
        except Exception:
            text = ""
        text = text.strip()
        if text:  # khali pages skip karo
            pages.append({"page": i + 1, "text": text})
    return pages


# ===========================================
# STEP 2: Text ko chunks me todna (overlap ke sath)
# ===========================================
def chunk_text(pages, chunk_size=CHUNK_SIZE, overlap=CHUNK_OVERLAP):
    """
    Input: pages = [{"page": 1, "text": "..."}, ...]
    Output: list of dicts -> [{"page": 1, "text": "chunk text..."}, ...]

    Har page ka text alag chunk hota hai (overlap page ke andar hi rakha jata hai,
    taake page number ka reference sahi rahe).
    """
    all_chunks = []
    for page_data in pages:
        page_num = page_data["page"]
        text = page_data["text"]

        start = 0
        text_len = len(text)

        if text_len <= chunk_size:
            all_chunks.append({"page": page_num, "text": text})
            continue

        while start < text_len:
            end = min(start + chunk_size, text_len)
            chunk = text[start:end]
            if chunk.strip():
                all_chunks.append({"page": page_num, "text": chunk})
            if end == text_len:
                break
            # Next chunk overlap ke sath start hoga
            start = end - overlap

    return all_chunks


# ===========================================
# STEP 3: HuggingFace API se embedding lena (retry logic ke sath)
# ===========================================
def get_embedding(text, hf_api_key, max_retries=MAX_RETRIES):
    """
    Text ko HuggingFace ke sentence-transformers/all-MiniLM-L6-v2 model se
    384-dimension vector me convert karta hai, huggingface_hub ke
    InferenceClient ke zariye (current supported tareeqa, purana REST
    endpoint ab dead hai).

    Timeout / cold-start / temporary error par retry karta hai.
    Returns: list of floats (length 384) ya None (agar sab retries fail ho jayen)
    """
    last_error = None
    for attempt in range(1, max_retries + 1):
        try:
            client = InferenceClient(provider="hf-inference", api_key=hf_api_key)
            result = client.feature_extraction(text, model=HF_EMBEDDING_MODEL)

            # result numpy array ya nested list ho sakta hai (token-level ya sentence-level)
            vector = _normalize_hf_embedding(result)
            if vector is not None:
                return vector
            last_error = "Unexpected HF response shape"
        except Exception as e:
            # Cold start, rate limit, network blip - sab yahan catch ho jate hain
            last_error = f"HF error: {e}"

        # Agla attempt karne se pehle thora rukho (model cold-start ke liye zaroori)
        if attempt < max_retries:
            time.sleep(RETRY_DELAY_SECONDS * attempt)

    print(f"[rag.py] get_embedding failed after {max_retries} attempts: {last_error}")
    return None


def _normalize_hf_embedding(result):
    """
    HuggingFace feature-extraction API kabhi kabhi nested list deta hai
    (token-level embeddings). Ye function usay ek flat 384-dim vector
    me convert karta hai (mean pooling agar zaroorat ho).
    """
    try:
        arr = np.array(result, dtype=float)
    except (ValueError, TypeError):
        return None

    if arr.ndim == 1:
        return arr.tolist()
    elif arr.ndim == 2:
        # token-level embeddings -> average pooling
        return arr.mean(axis=0).tolist()
    elif arr.ndim == 3:
        # batch of token-level embeddings -> squeeze aur average pooling
        return arr[0].mean(axis=0).tolist()
    return None


# ===========================================
# STEP 4: Cosine similarity
# ===========================================
def cosine_similarity(vec_a, vec_b):
    """Do vectors ke beech cosine similarity (-1 to 1, jitna zyada ache)."""
    a = np.array(vec_a, dtype=float)
    b = np.array(vec_b, dtype=float)
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(np.dot(a, b) / (norm_a * norm_b))


# ===========================================
# STEP 5: Query ke liye top-K sabse relevant chunks dhoondna
# ===========================================
def find_top_chunks(query_embedding, chunks, top_k=TOP_K):
    """
    chunks: list of Chunk model objects (jinke pass .get_embedding_list() hai)
    Returns: top_k chunks jo query ke sabse zyada similar hain (sorted, best first)
    """
    scored = []
    for chunk in chunks:
        try:
            chunk_vec = chunk.get_embedding_list()
        except Exception:
            continue
        score = cosine_similarity(query_embedding, chunk_vec)
        scored.append((score, chunk))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [chunk for score, chunk in scored[:top_k]]


# ===========================================
# STEP 6: Groq LLM ko context + sawal bhej ke jawab lena
# ===========================================
def _build_context_and_sources(context_chunks):
    """
    Shared helper: context_chunks (list of Chunk objects, possibly from
    MULTIPLE documents now) se:
    - context_text: Groq ko bhejne wala combined text (filename + page label ke sath)
    - sources: list of dicts [{"document_id":, "filename":, "page":}, ...] (deduped, sorted)
    """
    context_parts = []
    seen = set()
    sources = []
    for chunk in context_chunks:
        doc = chunk.document  # backref from models.py
        label = f"[{doc.filename} - Page {chunk.page_number}]"
        context_parts.append(f"{label}: {chunk.text}")

        key = (doc.id, chunk.page_number)
        if key not in seen:
            seen.add(key)
            sources.append({"document_id": doc.id, "filename": doc.filename, "page": chunk.page_number})

    # Filename, phir page number se sort karo taake output tidy rahe
    sources.sort(key=lambda s: (s["filename"], s["page"]))
    context_text = "\n\n".join(context_parts)
    return context_text, sources


SYSTEM_PROMPT = (
    "You are DocMind, a helpful assistant that answers questions strictly based on "
    "the provided document context (which may come from one or more documents). "
    "If the answer is not present in the context, say so honestly instead of making "
    "things up. Keep answers clear and concise, and mention which document/page the "
    "information came from when relevant. "
    "IMPORTANT: Always respond in the SAME language the user asked the question in - "
    "if the question is in Urdu (Roman or native script), answer in Urdu; if in English, "
    "answer in English."
)


def ask_groq(question, context_chunks, groq_api_key):
    """
    context_chunks: list of Chunk model objects (top-k relevant chunks, possibly
    from multiple documents when the user selects more than one).
    Returns: (answer_text, sources_list) where sources_list is
    [{"document_id":, "filename":, "page":}, ...]
    """
    if not context_chunks:
        return ("Maaf kijiye, in document(s) me is sawal se related koi content nahi mila.", [])

    context_text, sources = _build_context_and_sources(context_chunks)
    user_prompt = f"CONTEXT:\n{context_text}\n\nQUESTION: {question}"

    try:
        client = Groq(api_key=groq_api_key)
        completion = client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.3,
            max_tokens=1024,
        )
        answer = completion.choices[0].message.content
        return (answer, sources)
    except Exception as e:
        print(f"[rag.py] Groq API error: {e}")
        return (f"Sorry, there was an error contacting the AI model: {e}", [])


def ask_groq_stream(question, context_chunks, groq_api_key):
    """
    Streaming version of ask_groq - "typing effect" ke liye use hoti hai.
    Generator hai: token-by-token text yield karta hai (strings).
    Caller (app.py) khud pura answer accumulate kar ke DB me save karega.

    Raises an Exception if the Groq call itself fails (caller ko catch karna hoga).
    """
    if not context_chunks:
        yield "Maaf kijiye, in document(s) me is sawal se related koi content nahi mila."
        return

    context_text, _sources = _build_context_and_sources(context_chunks)
    user_prompt = f"CONTEXT:\n{context_text}\n\nQUESTION: {question}"

    client = Groq(api_key=groq_api_key)
    stream = client.chat.completions.create(
        model=GROQ_MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.3,
        max_tokens=1024,
        stream=True,
    )
    for chunk in stream:
        delta = chunk.choices[0].delta.content
        if delta:
            yield delta


def generate_summary(pages, groq_api_key, max_chars=3000):
    """
    Document upload hone ke waqt ek chota (3-4 sentence) summary auto-generate
    karta hai, dashboard/document list par dikhane ke liye.

    pages: extract_text_from_pdf() ka output -> [{"page":1,"text":"..."}, ...]
    Returns: summary string, ya None agar generation fail ho jaye
    (upload process ye None handle kar ke aage badh jata hai - summary
    optional hai, upload ko block nahi karta).
    """
    if not pages:
        return None

    combined_text = "\n".join(p["text"] for p in pages)[:max_chars]

    try:
        client = Groq(api_key=groq_api_key)
        completion = client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[
                {"role": "system", "content": "Summarize the following document in 3-4 concise sentences. Respond in English."},
                {"role": "user", "content": combined_text},
            ],
            temperature=0.3,
            max_tokens=200,
        )
        return completion.choices[0].message.content.strip()
    except Exception as e:
        print(f"[rag.py] generate_summary failed (non-fatal): {e}")
        return None


# ===========================================
# HELPER: Ek document ko process karna (upload ke waqt use hota hai)
# app.py se call hota hai. Returns: (pages_processed, chunks_created, error)
# ===========================================
def process_document(filepath, hf_api_key):
    """
    Pura pipeline: PDF -> text -> chunks -> embeddings
    Returns: list of dicts -> [{"page": 1, "text": "...", "embedding": [...]}, ...]
    Agar embedding fail ho jaye kisi chunk ke liye, usay skip kar dete hain.
    """
    pages = extract_text_from_pdf(filepath)
    if not pages:
        return [], "PDF se koi text extract nahi ho saka. Shayad ye scanned image hai."

    raw_chunks = chunk_text(pages)
    if not raw_chunks:
        return [], "PDF me text nahi mila chunk banane ke liye."

    processed_chunks = []
    for chunk in raw_chunks:
        embedding = get_embedding(chunk["text"], hf_api_key)
        if embedding is not None:
            processed_chunks.append({
                "page": chunk["page"],
                "text": chunk["text"],
                "embedding": embedding,
            })
        # agar embedding fail ho to woh chunk skip ho jayega (silent skip),
        # taake pura upload fail na ho ek chunk ki wajah se

    if not processed_chunks:
        return [], "Koi bhi chunk ka embedding nahi ban saka. HuggingFace API key check karein."

    return processed_chunks, None
