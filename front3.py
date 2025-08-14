# front_chat_pro.py
import streamlit as st
import requests
import uuid
import json
import re
import tempfile
import os
from datetime import datetime
from gtts import gTTS

# ------------- CONFIG -------------
BACKEND = "http://localhost:8000"
REGISTER_URL = f"{BACKEND}/register"
LOGIN_URL    = f"{BACKEND}/login"
UPLOAD_URL   = f"{BACKEND}/upload-pdf"
CHAT_URL     = f"{BACKEND}/chat"
ADMIN_USERS_URL  = f"{BACKEND}/admin/users"
ADMIN_CHATS_URL  = f"{BACKEND}/admin/chats"
DL_USERS_URL     = f"{BACKEND}/admin/download/users"
DL_CHATS_URL     = f"{BACKEND}/admin/download/chats"

st.set_page_config(page_title="EduChat Pro", layout="wide", initial_sidebar_state="expanded")

# ------------- SESSION INIT -------------
if "user" not in st.session_state:
    st.session_state.user = None  # {"email","role"}
if "session_id" not in st.session_state:
    st.session_state.session_id = str(uuid.uuid4())
if "messages" not in st.session_state:
    # each item: {"id","role":"user"|"assistant","content","mode","ts"}
    st.session_state.messages = []
if "selected_user_msg_id" not in st.session_state:
    st.session_state.selected_user_msg_id = None
if "pdf_ready" not in st.session_state:
    st.session_state.pdf_ready = False
if "current_mode" not in st.session_state:
    st.session_state.current_mode = "qa"  # qa, summary, mcq
if "last_mcq" not in st.session_state:
    st.session_state.last_mcq = None

# ------------- STYLES -------------
st.markdown(
    """
    <style>
    /* page background */
    .stApp { background-color: #f7fafc; }
    /* chat container */
    .chat-container { max-width: 900px; margin: auto; }
    .bubble { padding: 12px 16px; border-radius: 12px; margin: 6px 0; display: inline-block; max-width: 80%; }
    .user { background: linear-gradient(90deg,#1f6feb,#3aa0ff); color: white; float: right; border-bottom-right-radius: 4px; }
    .assistant { background: #ffffff; color: #0f172a; border: 1px solid #e6eef8; float: left; }
    .meta { font-size: 12px; color: #64748b; margin-bottom:6px; }
    .clear { clear: both; }
    .sidebar-history-button { width:100%; text-align: left; padding:8px 10px; border-radius:6px; margin-bottom:6px; border:1px solid transparent; }
    .sidebar-history-button:hover { background:#eef6ff; cursor:pointer; border-color:#d0e7ff; }
    </style>
    """,
    unsafe_allow_html=True,
)

# ------------- HELPERS -------------
def add_message(role: str, content: str, mode: str):
    st.session_state.messages.append({
        "id": str(uuid.uuid4()),
        "role": role,
        "content": content,
        "mode": mode,
        "ts": datetime.utcnow().isoformat()
    })

def tts_play(text: str):
    try:
        tts = gTTS(text=text, lang="ar")
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".mp3")
        tts.write_to_fp(tmp)
        tmp.flush(); tmp.close()
        audio_bytes = open(tmp.name, "rb").read()
        st.audio(audio_bytes, format="audio/mp3")
        try:
            os.unlink(tmp.name)
        except Exception:
            pass
    except Exception as e:
        st.error(f"TTS خطأ: {e}")

def send_to_backend(email: str, session_id: str, message: str, mode: str):
    try:
        data = {"email": email, "session_id": session_id, "message": message, "mode": mode}
        r = requests.post(CHAT_URL, data=data, timeout=120)
        r.raise_for_status()
        js = r.json()
        return True, js.get("answer", "") if isinstance(js, dict) else str(js)
    except Exception as e:
        return False, str(e)

def try_parse_mcq(text: str):
    try:
        m = re.search(r"```json\s*(.*?)\s*```", text, re.DOTALL)
        if m:
            text = m.group(1)
        data = json.loads(text)
        if isinstance(data, dict) and "quiz" in data:
            return data
    except Exception:
        return None
    return None

# ------------- SIDEBAR: AUTH + HISTORY + ADMIN -------------
with st.sidebar:
    st.title("EduChat Pro")
    if st.session_state.user is None:
        tabs = st.tabs(["دخول", "تسجيل"])
        with tabs[0]:
            email = st.text_input("📧 البريد الإلكتروني", key="login_email")
            password = st.text_input("🔑 كلمة المرور", type="password", key="login_password")
            if st.button("دخول", key="btn_login"):
                try:
                    r = requests.post(LOGIN_URL, data={"email": email, "password": password}, timeout=30)
                    res = r.json()
                    if res.get("status") == "ok":
                        st.session_state.user = {"email": email, "role": res.get("role","user")}
                        st.success("تم تسجيل الدخول")
                        st.experimental_rerun()
                    else:
                        st.error(res.get("msg", "فشل تسجيل الدخول"))
                except Exception as e:
                    st.error(f"خطأ اتصال: {e}")
        with tabs[1]:
            email_r = st.text_input("📧 بريد جديد", key="reg_email")
            password_r = st.text_input("🔑 كلمة المرور", type="password", key="reg_password")
            if st.button("تسجيل", key="btn_register"):
                if not email_r or not password_r:
                    st.warning("أدخل بريد وكلمة مرور")
                else:
                    try:
                        r = requests.post(REGISTER_URL, data={"email": email_r, "password": password_r}, timeout=30)
                        res = r.json()
                        if res.get("status") == "ok":
                            st.success("تم التسجيل، سجّل الدخول الآن")
                        else:
                            st.error(res.get("msg", "فشل التسجيل"))
                    except Exception as e:
                        st.error(f"خطأ اتصال: {e}")
    else:
        st.markdown(f"**{st.session_state.user['email']}**")
        st.caption(f"دور: {st.session_state.user.get('role','user')}")
        if st.button("تسجيل خروج", key="btn_logout"):
            st.session_state.user = None
            st.session_state.selected_user_msg_id = None
            st.session_state.pdf_ready = False
            st.session_state.last_mcq = None
            st.session_state.messages = []
            st.experimental_rerun()

    st.markdown("---")
    st.subheader("History")
    if st.session_state.messages:
        # show only user messages in reverse order
        for msg in reversed(st.session_state.messages):
            if msg["role"] == "user":
                short = msg["content"][:45] + ("..." if len(msg["content"])>45 else "")
                # use button-like element
                if st.button(short, key=f"hist_{msg['id']}"):
                    st.session_state.selected_user_msg_id = msg["id"]
    else:
        st.write("لا توجد محادثات بعد.")

    st.markdown("---")
    if st.session_state.user and st.session_state.user.get("role") == "admin":
        st.subheader("لوحة الأدمن")
        try:
            users = requests.get(ADMIN_USERS_URL, timeout=30).json()
            st.write(f"المستخدمون: {len(users)}")
            if st.button("عرض المستخدمين", key="admin_users"):
                st.dataframe(users)
            if st.button("تحميل users.csv", key="dl_users"):
                try:
                    resp = requests.get(DL_USERS_URL, timeout=30)
                    st.download_button("Download users.csv", data=resp.content, file_name="users.csv", mime="text/csv", key="download_users_btn")
                except Exception as e:
                    st.error(f"خطأ تنزيل: {e}")
            if st.button("تحميل chats.csv", key="dl_chats"):
                try:
                    resp = requests.get(DL_CHATS_URL, timeout=30)
                    st.download_button("Download chats.csv", data=resp.content, file_name="chats.csv", mime="text/csv", key="download_chats_btn")
                except Exception as e:
                    st.error(f"خطأ تنزيل: {e}")
            # inspect one user's chats
            emails = [u["email"] for u in users if u.get("email")]
            sel = st.selectbox("اختر مستخدماً", options=[""]+emails, key="admin_sel_user")
            if sel:
                ch = requests.get(f"{ADMIN_CHATS_URL}/{sel}", timeout=30).json()
                st.dataframe(ch)
        except Exception as e:
            st.error(f"خطأ جلب بيانات الأدمن: {e}")

# ------------- TOP HEADER / MODE / PDF UPLOAD -------------
st.markdown("<div style='max-width:1100px;margin:auto;'>", unsafe_allow_html=True)
st.title("EduChat Pro — مساعد تعليمي")
col1, col2, col3 = st.columns([3,2,1])
with col1:
    st.write("اكتب سؤالاً تعليمياً أو ارفع ملف PDF كمصدر للمحتوى.")
with col2:
    mode_ui = st.selectbox("الوضع (Mode)", ["سؤال/جواب", "ملخص", "MCQ"], key="mode_select_top")
    st.session_state.current_mode = {"سؤال/جواب":"qa","ملخص":"summary","MCQ":"mcq"}[mode_ui]
with col3:
    up = st.file_uploader("ارفع PDF (اختياري)", type=["pdf"], key="top_pdf_uploader")
    if up is not None and st.session_state.user:
        if st.button("تحميل PDF كسياق", key="btn_upload_pdf_top"):
            try:
                files = {"file": (up.name, up.getvalue(), "application/pdf")}
                data = {"session_id": st.session_state.session_id}
                r = requests.post(UPLOAD_URL, files=files, data=data, timeout=120)
                res = r.json()
                if res.get("status") == "ok":
                    st.session_state.pdf_ready = True
                    st.success(f"PDF جاهز — {res.get('pdf_chars',0)} حرف")
                else:
                    st.error("فشل رفع PDF")
            except Exception as e:
                st.error(f"خطأ رفع: {e}")

st.markdown("</div>", unsafe_allow_html=True)
st.markdown("---")

# ------------- MAIN CHAT AREA (single selected Q view or default) -------------
main_col, right_col = st.columns([3,1])
with main_col:
    st.markdown("<div class='chat-container'>", unsafe_allow_html=True)
    if st.session_state.selected_user_msg_id:
        # display only that Q & corresponding A
        user_msg = next((m for m in st.session_state.messages if m["id"] == st.session_state.selected_user_msg_id and m["role"]=="user"), None)
        if user_msg:
            # find assistant reply after this user msg
            idx = next((i for i,m in enumerate(st.session_state.messages) if m["id"]==user_msg["id"]), None)
            assistant_msg = None
            if idx is not None:
                for m in st.session_state.messages[idx+1:]:
                    if m["role"]=="assistant":
                        assistant_msg = m; break
            st.markdown(f"<div class='meta'>سؤال بتاريخ: {user_msg['ts']}</div>", unsafe_allow_html=True)
            st.markdown(f"<div class='bubble user'>{user_msg['content']}</div><div class='clear'></div>", unsafe_allow_html=True)
            st.markdown("---")
            st.markdown("<div class='meta'>إجابة الموديل:</div>", unsafe_allow_html=True)
            if assistant_msg:
                st.markdown(f"<div class='bubble assistant'>{assistant_msg['content']}</div><div class='clear'></div>", unsafe_allow_html=True)
                if st.button("🔊 استمع للإجابة", key=f"tts_single_{assistant_msg['id']}"):
                    tts_play(assistant_msg['content'])
            else:
                st.info("لم يتم الرد بعد على هذا السؤال.")
    else:
        # render full chronological conversation (grouped)
        for m in st.session_state.messages:
            if m["role"] == "user":
                st.markdown(f"<div class='meta'>سؤال • {m['ts']}</div>", unsafe_allow_html=True)
                st.markdown(f"<div class='bubble user'>{m['content']}</div><div class='clear'></div>", unsafe_allow_html=True)
            else:
                st.markdown(f"<div class='meta'>الموديل • {m['ts']}</div>", unsafe_allow_html=True)
                st.markdown(f"<div class='bubble assistant'>{m['content']}</div><div class='clear'></div>", unsafe_allow_html=True)
                if st.button("🔊 استمع", key=f"tts_{m['id']}"):
                    tts_play(m['content'])
    st.markdown("</div>", unsafe_allow_html=True)

with right_col:
    st.markdown("### أدوات سريعة")
    st.write(f"الوضع الحالي: **{mode_ui}**")
    if st.session_state.pdf_ready:
        st.success("سياق PDF مرفوع ✓")
    st.markdown("---")
    st.markdown("MCQ: إن وُجد آخر امتحان")
    if st.session_state.last_mcq:
        try:
            quiz = st.session_state.last_mcq.get("quiz", [])
            for idx, q in enumerate(quiz):
                st.markdown(f"**{idx+1}. {q.get('question','')}**")
                choices = q.get('choices', {})
                for k,v in choices.items():
                    st.write(f"{k}) {v}")
                st.markdown("---")
        except Exception:
            st.info("خطأ عرض MCQ")

st.markdown("---")

# ------------- BOTTOM: chat_input (single) -------------
if st.session_state.user is None:
    st.info("سجّل الدخول من الشريط الجانبي للبدء.")
else:
    # chat_input placeholder only via keyword to avoid duplicate-arg error
    try:
        user_input = st.chat_input(placeholder="اكتب سؤالاً تعليمياً أو اطلب ملخصًا...", key="main_chat_input")
    except Exception:
        # fallback for older streamlit versions
        user_input = st.text_input("اكتب سؤالاً تعليمياً أو اطلب ملخصًا...", key="main_fallback_input")

    if user_input:
        # add user bubble locally
        add_message("user", user_input, st.session_state.current_mode)
        # ensure selected clears to show full conversation unless wanted otherwise
        st.session_state.selected_user_msg_id = None
        # send to backend
        ok, answer = send_to_backend(st.session_state.user["email"], st.session_state.session_id, user_input, st.session_state.current_mode)
        if ok:
            add_message("assistant", answer, st.session_state.current_mode)
            # if mcq try parse and save
            if st.session_state.current_mode == "mcq":
                parsed = try_parse_mcq(answer)
                if parsed:
                    st.session_state.last_mcq = parsed
        else:
            add_message("assistant", f"⚠️ خطأ: {answer}", st.session_state.current_mode)
        # rerun to show latest
        st.rerun()


