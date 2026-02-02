# app.py
# Público: acessa sem login e digita respostas (1 por vez) -> nuvem ao vivo
# Admin (login/senha): pode (1) definir a PERGUNTA exibida ao público, (2) zerar nuvem, (3) ver histórico

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
st.set_page_config(page_title="Nuvem de Palavras", layout="wide")
st.title("☁️ Nuvem de Palavras")

DATA_PATH = Path("data_words.json")

STOPWORDS_PT = {
    "a","à","ao","aos","as","às","com","como","da","das","de","do","dos","e","é","em","entre",
    "na","nas","no","nos","o","os","ou","para","por","que","se","sem","um","uma","não","nao",
    "sim","já","tá","tô","vc","vcs","você","vocês","me","minha","meu","meus","minhas",
    "sua","seu","suas","seus","isso","isto","essa","esse","esta","este","aqui","ali","lá","la",
}

DEFAULT_QUESTION = "Digite uma palavra que represente sua percepção sobre o tema."

# -----------------------------
# Admin auth via secrets/env
# -----------------------------
# Streamlit Cloud: Manage app -> Settings -> Secrets
# ADMIN_USER="admin"
# ADMIN_PASS="senha_forte"
ADMIN_USER = st.secrets.get("ADMIN_USER", os.getenv("ADMIN_USER", "admin"))
ADMIN_PASS = st.secrets.get("ADMIN_PASS", os.getenv("ADMIN_PASS", ""))  # configure no Cloud secrets

def check_admin(user: str, pwd: str) -> bool:
    return (
        hmac.compare_digest(user or "", ADMIN_USER or "")
        and hmac.compare_digest(pwd or "", ADMIN_PASS or "")
    )

# -----------------------------
# Lock (opcional, recomendado)
# -----------------------------
# requirements.txt recomendado:
# streamlit
# wordcloud
# matplotlib
# filelock
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
def _empty_data():
    return {
        "question": DEFAULT_QUESTION,
        "words": [],
        "created_at": time.time(),
        "updated_at": time.time(),
    }

def _read_data():
    if not DATA_PATH.exists():
        return _empty_data()
    try:
        with open(DATA_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
            # garante chaves
            if "question" not in data:
                data["question"] = DEFAULT_QUESTION
            if "words" not in data:
                data["words"] = []
            return data
    except Exception:
        return _empty_data()

def _write_data(data: dict):
    data["updated_at"] = time.time()
    with open(DATA_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def load_data() -> dict:
    def inner():
        return _read_data()
    return with_lock(inner)

def load_words() -> list[str]:
    return load_data().get("words", []) or []

def load_question() -> str:
    q = load_data().get("question", DEFAULT_QUESTION)
    return (q or DEFAULT_QUESTION).strip()

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

def set_question(new_q: str):
    def inner():
        data = _read_data()
        data["question"] = (new_q or DEFAULT_QUESTION).strip() or DEFAULT_QUESTION
        _write_data(data)
    return with_lock(inner)

# -----------------------------
# Texto → token
# -----------------------------
def limpar_token(t: str) -> str:
    t = (t or "").lower().strip()
    # mantém letras (inclui acentos) e remove tudo que não for letra
    t = re.sub(r"[^a-zà-ÿ]", "", t)
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

if "input_answer" not in st.session_state:
    st.session_state.input_answer = ""

if "admin_question_draft" not in st.session_state:
    st.session_state.admin_question_draft = ""

# -----------------------------
# Callback do input do público
# -----------------------------
def on_answer_change():
    raw = st.session_state.get("input_answer", "")
    token = filtrar_token(raw)

    # sempre limpa o campo (permitido no callback)
    st.session_state.input_answer = ""

    if not token:
        return

    # evita duplicar no rerun
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
    st.caption("Público: adiciona palavras. Admin: define pergunta, vê histórico e pode zerar.")

# -----------------------------
# UI principal
# -----------------------------
col1, col2 = st.columns([2, 1], gap="large")

with col1:
    # Pergunta definida pelo admin (visível ao público)
    pergunta = load_question()
    st.markdown("### Pergunta")
    st.info(pergunta)

    st.subheader("Digite sua resposta (uma palavra) e pressione Enter")
    st.text_input(
        "Resposta",
        key="input_answer",
        placeholder="Ex.: colaboração",
        help="A nuvem atualiza quando você pressiona Enter.",
        on_change=on_answer_change,
        label_visibility="collapsed",
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

    # -------- Admin controls --------
    if st.session_state.is_admin:
        st.divider()
        st.subheader("🛠️ Controles (Admin)")

        # Pergunta (cadastro/edição)
        st.markdown("#### ✍️ Pergunta exibida ao público")

        # carrega a pergunta atual como rascunho (apenas na primeira vez)
        if not st.session_state.admin_question_draft:
            st.session_state.admin_question_draft = load_question()

        st.text_area(
            "Editar pergunta",
            key="admin_question_draft",
            height=120,
            placeholder="Digite aqui a pergunta que aparecerá para os participantes…",
        )

        cbtn1, cbtn2 = st.columns(2)
        with cbtn1:
            if st.button("💾 Salvar pergunta"):
                set_question(st.session_state.admin_question_draft)
                st.success("Pergunta atualizada.")
                st.rerun()
        with cbtn2:
            if st.button("↩️ Restaurar padrão"):
                st.session_state.admin_question_draft = DEFAULT_QUESTION
                set_question(DEFAULT_QUESTION)
                st.info("Pergunta restaurada para o padrão.")
                st.rerun()

        # Zerar nuvem
        st.markdown("#### 🧹 Limpeza")
        if st.button("Zerar nuvem (limpar tudo)"):
            clear_all_words()
            st.success("Nuvem zerada.")
            st.rerun()

        # Histórico completo
        st.markdown("#### 🧾 Histórico completo (Admin)")
        modo = st.radio("Visualização", ["Filtrado (válidas)", "Bruto (como salvo)"], horizontal=True)
        st.write(filtered if modo.startswith("Filtrado") else words_all)

    else:
        st.caption("🔒 Definir pergunta, histórico completo e zerar: apenas admin.")

# -----------------------------
# Rodapé
# -----------------------------
st.markdown(
    """
    <hr style="margin-top: 3rem; margin-bottom: 1rem;">
    <div style="text-align: center; font-size: 0.9rem; color: #6c757d;">
        App desenvolvido pela <strong>Gerência de Avaliação</strong> • 02/02/2026
    </div>
    """,
    unsafe_allow_html=True
)
