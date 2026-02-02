# app.py
# Streamlit app: público pode adicionar palavras sem login; somente admin (login+senha) pode
# (1) zerar a nuvem e (2) visualizar o histórico completo.

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
# Configurações gerais
# -----------------------------
st.set_page_config(page_title="Palavra em Foco", layout="wide")
st.title("☁️ Palavra em Foco — Nuvem ao vivo")

DATA_PATH = Path("data_words.json")  # arquivo simples para compartilhar dados entre usuários (no mesmo deploy)

# Stopwords PT-BR (ajuste livre)
STOPWORDS_PT = {
    "a","à","ao","aos","as","às","com","como","da","das","de","do","dos","e","é","em","entre",
    "na","nas","no","nos","o","os","ou","para","por","que","se","sem","um","uma","não","nao",
    "sim","já","tá","tô","vc","vcs","você","vocês","me","minha","meu","meus","minhas",
    "sua","seu","suas","seus","isso","isto","essa","esse","esta","este","aqui","ali","lá","la",
}

# -----------------------------
# Auth (admin) via secrets/env
# -----------------------------
# Streamlit Cloud: defina em .streamlit/secrets.toml:
#   ADMIN_USER="admin"
#   ADMIN_PASS="uma_senha_forte"
#
# Alternativa local: variáveis de ambiente ADMIN_USER e ADMIN_PASS
ADMIN_USER = st.secrets.get("ADMIN_USER", os.getenv("ADMIN_USER", "admin"))
ADMIN_PASS = st.secrets.get("ADMIN_PASS", os.getenv("ADMIN_PASS", ""))  # deixe vazio até configurar

def check_admin(user: str, pwd: str) -> bool:
    # compara de forma segura (evita timing leak)
    return hmac.compare_digest(user or "", ADMIN_USER or "") and hmac.compare_digest(pwd or "", ADMIN_PASS or "")

# -----------------------------
# Lock opcional (evita corrida entre usuários)
# -----------------------------
# Se quiser mais robustez, adicione "filelock" ao requirements.txt
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
    """Executa fn() com lock se filelock estiver disponível."""
    if not LOCK_AVAILABLE:
        return fn()
    lock = FileLock(str(DATA_PATH) + ".lock")
    with lock:
        return fn()

# -----------------------------
# Persistência simples
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
        data = _read_data()
        return data.get("words", []) or []
    return with_lock(inner)

def append_word(token: str):
    def inner():
        data = _read_data()
        words = data.get("words", []) or []
        words.append(token)
        data["words"] = words
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
# WordCloud render
# -----------------------------
def gerar_wordcloud_fig(words: list[str]):
    # filtra novamente por segurança
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
# Sidebar: Admin login
# -----------------------------
with st.sidebar:
    st.header("🔒 Área administrativa")

    if "is_admin" not in st.session_state:
        st.session_state.is_admin = False

    if ADMIN_PASS == "":
        st.warning("Defina ADMIN_PASS em secrets/env para habilitar login admin.")
        st.session_state.is_admin = False
    else:
        if not st.session_state.is_admin:
            user = st.text_input("Usuário", value="", placeholder="admin")
            pwd = st.text_input("Senha", value="", type="password", placeholder="••••••••")
            if st.button("Entrar"):
                if check_admin(user, pwd):
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
    st.caption("Público: pode adicionar palavras sem login. Admin: pode zerar e ver histórico.")

# -----------------------------
# UI principal
# -----------------------------
col1, col2 = st.columns([2, 1], gap="large")

with col1:
    st.subheader("Digite uma palavra e pressione Enter")

    # guarda input em session_state para limpar depois
    if "input_word" not in st.session_state:
        st.session_state.input_word = ""

    palavra = st.text_input(
        "Palavra",
        key="input_word",
        placeholder="Ex.: colaboração",
        help="A nuvem atualiza quando você pressiona Enter (Streamlit).",
    )

    # Evita re-adicionar repetidamente a mesma palavra ao rerun
    if "last_added" not in st.session_state:
        st.session_state.last_added = ""

    token = filtrar_token(palavra)
    if token and token != st.session_state.last_added:
        append_word(token)
        st.session_state.last_added = token
        st.session_state.input_word = ""  # limpa campo
        st.rerun()

    # Carrega e mostra a nuvem (dados compartilhados via arquivo)
    words_all = load_words()
    fig = gerar_wordcloud_fig(words_all)

    st.markdown("### ☁️ Nuvem de palavras (ao vivo)")
    if fig is None:
        st.info("Ainda não há palavras válidas. Digite uma palavra (ex.: “colaboração”) e pressione Enter.")
    else:
        st.pyplot(fig, clear_figure=True)

with col2:
    st.subheader("📊 Resumo")

    words_all = load_words()
    # contagem com filtro
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

    # -----------------------------
    # Controles admin
    # -----------------------------
    if st.session_state.is_admin:
        st.divider()
        st.subheader("🛠️ Controles (Admin)")

        if st.button("🧹 Zerar nuvem (limpar tudo)"):
            clear_all_words()
            st.success("Nuvem zerada.")
            st.rerun()

        st.markdown("### 🧾 Histórico completo (Admin)")
        # Mostra histórico filtrado (somente válidas) + bruto
        modo = st.radio("Visualização", ["Filtrado (válidas)", "Bruto (como salvo)"], horizontal=True)
        if modo.startswith("Filtrado"):
            st.write(filtered)
        else:
            st.write(words_all)
    else:
        st.caption("🔒 Histórico completo e botão de zerar: apenas para admin.")

# Rodapé
st.caption("Dica: se quiser que a nuvem atualize ainda mais rápido, você pode usar um botão 'Adicionar' em vez de Enter.")
