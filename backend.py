import os
import re
import csv
import json
import requests
import pandas as pd
from datetime import datetime
from typing import Optional, Dict

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
import fitz  # PyMuPDF
import bcrypt

# --------------------
# Config
# --------------------
API_URL = "https://api.together.xyz/v1/chat/completions"
MODEL = "meta-llama/Meta-Llama-3.1-8B-Instruct-Turbo"
TOGETHER_API_KEY = "4c312200c83246882b4e8fc2f4841f5edb262e5f50070a86ed4983c807dc2259"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
os.makedirs(DATA_DIR, exist_ok=True)

USERS_FILE = os.path.join(DATA_DIR, "users.csv")
CHATS_FILE = os.path.join(DATA_DIR, "chats.csv")

ADMIN_EMAIL = "ahmedhassaan8802@gmail.com"
ADMIN_PASS = "ahmed112233"  # سيُخزَّن مشفّرًا

# --------------------
# App + CORS
# --------------------
app = FastAPI(title="EduChat API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_credentials=True,
    allow_methods=["*"], allow_headers=["*"],
)

# --------------------
# Storage
# --------------------
pdf_storage: Dict[str, str] = {}  # session_id -> pdf_text

# --------------------
# Utils
# --------------------
def load_csv(path: str, columns: list) -> pd.DataFrame:
    if os.path.exists(path):
        return pd.read_csv(path)
    return pd.DataFrame(columns=columns)

def save_csv(df: pd.DataFrame, path: str):
    df.to_csv(path, index=False, encoding="utf-8-sig")

def hash_pw(pw: str) -> str:
    return bcrypt.hashpw(pw.encode(), bcrypt.gensalt()).decode()

def verify_pw(pw: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(pw.encode(), hashed.encode())
    except Exception:
        return False

def ensure_admin():
    df = load_csv(USERS_FILE, ["email","password_hash","role","created_at","last_login_at"])
    if not (df["email"]==ADMIN_EMAIL).any():
        now = datetime.utcnow().isoformat()
        df.loc[len(df)] = [ADMIN_EMAIL, hash_pw(ADMIN_PASS), "admin", now, now]
        save_csv(df, USERS_FILE)
ensure_admin()

def read_pdf_bytes(file_bytes: bytes) -> str:
    doc = fitz.open(stream=file_bytes, filetype="pdf")
    parts = [page.get_text() for page in doc]
    return "\n".join(parts).strip()

def truncate(text: str, max_chars: int = 6000) -> str:
    if len(text) <= max_chars:
        return text
    return text[: int(max_chars*0.6)] + "\n...[تم الاقتصاص]...\n" + text[-int(max_chars*0.35):]

OFFTOPIC_PATTERNS = [
    r"من (صنعك|عملك|طورك|أنشأك)",
    r"مين (صنعك|عملك|طورك|اللي صنعك|انشاك)",
    r"انت (مين|منين|من اين)",
    r"(who|where).*(made|created|are you|from)",
    r"اسمك ايه",
]
EDU_REFUSAL = "لا يمكنني الإجابة عن هذا النوع من الأسئلة. أنا هنا لأساعدك في التعلم والدراسة فقط."

SYSTEM_PROMPT_BASE = (
    "أنت مساعد تعليمي عربي واضح ومنظّم. اشرح بإيجاز وبدقّة، وركّز على المفاهيم والأمثلة التعليمية."
    " تجنّب أي كلام خارج الموضوع التعليمي."
)

def is_offtopic(text: str) -> bool:
    t = (text or "").strip().lower()
    return any(re.search(p, t) for p in OFFTOPIC_PATTERNS)

def call_together(messages, max_tokens=800, temperature=0.5) -> str:
    if not TOGETHER_API_KEY:
        return "⚠️ لم يتم ضبط مفتاح Together."
    headers = {"Authorization": f"Bearer {TOGETHER_API_KEY}", "Content-Type": "application/json"}
    payload = {"model": MODEL, "messages": messages, "max_tokens": max_tokens, "temperature": temperature}
    r = requests.post(API_URL, headers=headers, json=payload, timeout=60)
    if r.status_code != 200:
        return f"⚠️ خطأ {r.status_code}: {r.text}"
    data = r.json()
    return data["choices"][0]["message"]["content"]

def log_chat(email: str, question: str, answer: str, mode: str):
    df = load_csv(CHATS_FILE, ["email","question","answer","mode","timestamp"])
    df.loc[len(df)] = [email, question, answer, mode, datetime.utcnow().isoformat()]
    save_csv(df, CHATS_FILE)

# --------------------
# Auth Endpoints
# --------------------
@app.post("/register")
def register(email: str = Form(...), password: str = Form(...)):
    users = load_csv(USERS_FILE, ["email","password_hash","role","created_at","last_login_at"])
    if (users["email"] == email).any():
        return {"status": "error", "msg": "البريد مسجل من قبل"}
    role = "admin" if email == ADMIN_EMAIL else "user"
    now = datetime.utcnow().isoformat()
    users.loc[len(users)] = [email, hash_pw(password), role, now, now]
    save_csv(users, USERS_FILE)
    return {"status": "ok", "role": role}

@app.post("/login")
def login(email: str = Form(...), password: str = Form(...)):
    users = load_csv(USERS_FILE, ["email","password_hash","role","created_at","last_login_at"])
    row = users[users["email"] == email]
    if row.empty:
        return {"status": "error", "msg": "المستخدم غير موجود"}
    if verify_pw(password, row.iloc[0]["password_hash"]):
        users.loc[users["email"] == email, "last_login_at"] = datetime.utcnow().isoformat()
        save_csv(users, USERS_FILE)
        return {"status": "ok", "role": row.iloc[0]["role"]}
    return {"status": "error", "msg": "كلمة المرور غير صحيحة"}

# --------------------
# PDF Upload
# --------------------
@app.post("/upload-pdf")
def upload_pdf(session_id: str = Form(...), file: UploadFile = File(...)):
    try:
        content = file.file.read()
        text = truncate(read_pdf_bytes(content), max_chars=6000)
        pdf_storage[session_id] = text
        return {"status": "ok", "pdf_chars": len(text)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# --------------------
# Chat (modes: qa | summary | mcq)
# --------------------
@app.post("/chat")
def chat(
    email: str = Form(...),
    session_id: str = Form(...),
    message: str = Form(...),
    mode: str = Form("qa"),
):
    if is_offtopic(message):
        answer = EDU_REFUSAL
        log_chat(email, message, answer, "guard")
        return {"status": "ok", "answer": answer}

    pdf_ctx = pdf_storage.get(session_id, "")

    messages = [{"role": "system", "content": SYSTEM_PROMPT_BASE}]
    if pdf_ctx:
        messages.append({"role": "system", "content": f"سياق مختصر من ملف PDF:\n{pdf_ctx}"})

    if mode == "summary":
        user_content = (
            "لخّص المحتوى التعليمي المتاح في نقاط واضحة بعناوين فرعية."
            " إذا لا يوجد PDF فاختصر نص سؤالي إن كان تعليمياً.\n\n"
            f"تعليمات المستخدم:\n{message}"
        )
    elif mode == "mcq":
        user_content = (
            "أنشئ امتحان MCQ من 5 أسئلة كحد أقصى اعتمادًا على السياق التعليمي (أولوية لملف PDF إن وُجد). "
            "أعد الناتج كـ JSON صالح فقط بدون أي شرح خارج JSON وبالبنية التالية تمامًا:\n"
            "{\n  \"quiz\": [\n    {\n      \"question\": \"...\",\n      \"choices\": {\"A\":\"...\",\"B\":\"...\",\"C\":\"...\",\"D\":\"...\"},\n      \"answer\": \"A|B|C|D\",\n      \"explanation\": \"...\"\n    }\n  ]\n}\n\n"
            f"موضوع/مستوى الأسئلة (اختياري):\n{message}"
        )
    else:  # qa
        user_content = (
            "أجب بإيجاز ووضوح عن السؤال أدناه. إن استندت إلى PDF فلا داعي لذكر المرجع صراحة.\n\n"
            f"السؤال:\n{message}"
        )

    messages.append({"role": "user", "content": user_content})
    answer = call_together(messages, max_tokens=900, temperature=0.5)

    log_chat(email, message, answer, mode)
    return {"status": "ok", "answer": answer}

# --------------------
# Admin: list & downloads
# --------------------
@app.get("/admin/users")
def admin_users():
    return load_csv(USERS_FILE, ["email","password_hash","role","created_at","last_login_at"]).to_dict(orient="records")

@app.get("/admin/chats/{user_email}")
def admin_chats(user_email: str):
    df = load_csv(CHATS_FILE, ["email","question","answer","mode","timestamp"])
    return df[df["email"] == user_email].to_dict(orient="records")

@app.get("/admin/download/users")
def download_users():
    if os.path.exists(USERS_FILE):
        return FileResponse(USERS_FILE, filename="users.csv", media_type="text/csv")
    return {"status": "error", "msg": "لا يوجد ملف مستخدمين"}

@app.get("/admin/download/chats")
def download_chats():
    if os.path.exists(CHATS_FILE):
        return FileResponse(CHATS_FILE, filename="chats.csv", media_type="text/csv")
    return {"status": "error", "msg": "لا يوجد ملف محادثات"}
