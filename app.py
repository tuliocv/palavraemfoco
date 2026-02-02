# app.py
import json
import os
import re
import time
import hmac
from collections import Counter
from pathlib import Path

import streamlit as st
from wordcloud import WordCloud
import matplotlib.pyplot as plt

# -----------------------------
# Config
# -----------------------------
st.set_page_config(page_title="Palavra em Foco", layout="wide")
st.title("☁️ Wordpulse - a nuvem de palavras da Gerência de Avaliação")

DATA_PATH = Path("data_words.json")

STOPWORDS_PT = {
    "a","à","ao","aos","as","às","com","como","da","das","de","do","dos","e","é","em","entre",
    "na","nas","no","nos","o","os","ou","para","por","que","se","sem","um","uma","não","nao",
    "sim","já","tá","tô","vc","vcs","você","vocês","me","minha","meu","meus","minhas",
    "sua","seu","suas","seus","isso","isto","essa","esse","esta","este","aqui","ali","lá","la",
}

# -----------------------------
# Admin auth via secrets/env
# -----------------------------
ADMIN_USER = st.secrets.get("ADMIN_USER", os.getenv("ADMIN_USER", "admin"))
ADMIN_PASS = st.secrets.get("ADMIN_PASS", os.getenv("ADMIN_PASS", ""))  # configure no Cloud secrets

def check_admin(user: str, pwd: str) -> bool:
    return (
        hmac.compare_digest(user or "", ADMIN_USER or "")
        and hmac.compare_digest(pwd or "", ADMIN_PASS or "")
    )

# -----------------------------
# Lock (opcional)
# -----------------------------
try:
    from filelock import FileLock
    LOCK_AVAILABLE = True
except Exception:
    LOCK_AVAILABLE = False

def with_lock(fn):
    if not LOCK_AVAILABLE:
        return fn()
    lock = FileLock(str(DATA_PATH) + ".lock")
    with lock:
        return fn()

# -----------------------------
# Persistência
# -----------------------------
def _read_data():
    if not DATA_PATH.exists():
        return {"words": [], "created_at": time.time(), "updated_at": time.time()}
    try:
        with open(DATA_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"words": [], "created_at": time.time(), "updated_at": time.time()}

def _write_data(data: dict):
    data["updated_at"] = time.time()
    with open(DATA_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def load_words() -> list[str]:
    def inner():
        return (_read_data().get("words", []) or [])
    return with_lock(inner)

def append_word(token: str):
    def inner():
        data = _read_data()
        data["words"] = (data.get("words", []) or []) + [token]
        _write_data(data)
    return with_lock(inner)

def clear_all_words():
    def inner():
        data = _read_data()
        data["words"] = []
        _write_data(data)
    return with_lock(inner)

# -----------------------------
# Texto → token
# -----------------------------
def limpar_token(t: str) -> str:
    t = (t or "").lower().strip()
    t = re.sub(r"[^a-zà-ÿ]", "", t)  # mantém letras com acento
    return t

def filtrar_token(token: str) -> str | None:
    token = limpar_token(token)
    if not token:
        return None
    if token in STOPWORDS_PT:
        return None
    if len(token) < 2:
        return None
    return token

# -----------------------------
# WordCloud
# -----------------------------
def gerar_wordcloud_fig(words: list[str]):
    valid = []
    for w in words:
        w2 = filtrar_token(w)
        if w2:
            valid.append(w2)

    if not valid:
        return None

    text = " ".join(valid)

    wc = WordCloud(
        width=1600,
        height=800,
        background_color="white",
        colormap="viridis",
        stopwords=STOPWORDS_PT,
        collocations=False,
        max_words=250,
    ).generate(text)

    fig, ax = plt.subplots(figsize=(16, 8))
    ax.imshow(wc, interpolation="bilinear")
    ax.axis("off")
    return fig

# -----------------------------
# Estado
# -----------------------------
if "is_admin" not in st.session_state:
    st.session_state.is_admin = False

if "last_added" not in st.session_state:
    st.session_state.last_added = ""

if "input_word" not in st.session_state:
    st.session_state.input_word = ""

# -----------------------------
# Callback do input (AQUI é o segredo)
# -----------------------------
def on_word_change():
    raw = st.session_state.get("input_word", "")
    token = filtrar_token(raw)

    # Sempre limpa o campo (sem erro, porque estamos no callback)
    st.session_state.input_word = ""

    if not token:
        return

    # Evita duplicar no rerun
    if token == st.session_state.get("last_added", ""):
        return

    append_word(token)
    st.session_state.last_added = token

# -----------------------------
# Sidebar admin
# -----------------------------
with st.sidebar:
    st.header("🔒 Área administrativa")

    if ADMIN_PASS == "":
        st.warning("Admin desabilitado: defina ADMIN_PASS nos Secrets/ENV.")
        st.session_state.is_admin = False
    else:
        if not st.session_state.is_admin:
            u = st.text_input("Usuário", value="", placeholder="admin", key="admin_user")
            p = st.text_input("Senha", value="", type="password", placeholder="••••••••", key="admin_pass")
            if st.button("Entrar"):
                if check_admin(u, p):
                    st.session_state.is_admin = True
                    st.success("Login admin ok.")
                    st.rerun()
                else:
                    st.error("Usuário ou senha inválidos.")
        else:
            st.success("Admin autenticado.")
            if st.button("Sair"):
                st.session_state.is_admin = False
                st.rerun()

    st.divider()
    st.caption("Público: adiciona palavras. Admin: vê histórico completo e pode zerar.")

# -----------------------------
# UI principal
# -----------------------------
col1, col2 = st.columns([2, 1], gap="large")

with col1:
    st.subheader("Digite uma palavra e pressione Enter")
    st.text_input(
        "Palavra",
        key="input_word",
        placeholder="Ex.: colaboração",
        help="A nuvem atualiza quando você pressiona Enter.",
        on_change=on_word_change,
    )

    words_all = load_words()
    fig = gerar_wordcloud_fig(words_all)

    st.markdown("### ☁️ Nuvem de palavras (ao vivo)")
    if fig is None:
        st.info("Ainda não há palavras válidas. Digite uma palavra e pressione Enter.")
    else:
        st.pyplot(fig, clear_figure=True)

with col2:
    st.subheader("📊 Resumo")

    words_all = load_words()
    filtered = [w for w in (filtrar_token(x) for x in words_all) if w]
    c = Counter(filtered)

    st.metric("Total de palavras", len(filtered))
    st.metric("Palavras únicas", len(c))

    st.markdown("### 🔝 Top palavras")
    top = c.most_common(15)
    if top:
        st.table([{"palavra": p, "freq": f} for p, f in top])
    else:
        st.caption("Sem dados ainda.")

    # Admin controls
    if st.session_state.is_admin:
        st.divider()
        st.subheader("🛠️ Controles (Admin)")

        if st.button("🧹 Zerar nuvem (limpar tudo)"):
            clear_all_words()
            st.success("Nuvem zerada.")
            st.rerun()

        st.markdown("### 🧾 Histórico completo (Admin)")
        modo = st.radio("Visualização", ["Filtrado (válidas)", "Bruto (como salvo)"], horizontal=True)
        st.write(filtered if modo.startswith("Filtrado") else words_all)
    else:
        st.caption("🔒 Histórico completo e zerar: apenas admin.")


st.markdown(
    """
    <hr style="margin-top: 3rem; margin-bottom: 1rem;">
    <div style="text-align: center; font-size: 0.9rem; color: #6c757d;">
        App desenvolvido pela <strong>Gerência de Avaliação</strong> • 02/02/2026
    </div>
    """,
    unsafe_allow_html=True
)

