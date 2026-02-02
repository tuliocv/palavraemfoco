# app.py
# Público: acessa sem login e digita respostas (texto curto). A nuvem atualiza ao vivo.
# Admin (login/senha): pode (1) definir a pergunta, (2) ver histórico, (3) zerar, (4) gerar relatório via ChatGPT.
#
# IMPORTANTE:
# - A API Key do ChatGPT é informada pelo admin na hora (não fica no GitHub).
# - Para Streamlit Cloud: configure ADMIN_USER / ADMIN_PASS em Secrets (Manage app -> Settings -> Secrets).
#
# requirements.txt sugerido:
# streamlit
# wordcloud
# matplotlib
# filelock
# openai

import json
import os
import re
import time
import hmac
from collections import Counter
from pathlib import Path
from typing import List, Dict, Optional

import streamlit as st
from wordcloud import WordCloud
import matplotlib.pyplot as plt

# OpenAI (SDK oficial)
try:
    from openai import OpenAI
    OPENAI_AVAILABLE = True
except Exception:
    OPENAI_AVAILABLE = False


# -----------------------------
# Config
# -----------------------------
st.set_page_config(page_title="WordPulse - v1", layout="wide")
st.markdown("## ☁️ WordPulse - A Nuvem de Palavras da Gerência de Avaliação")

DATA_PATH = Path("data_words.json")

DEFAULT_QUESTION = "Digite uma palavra que represente sua percepção sobre o tema."

# Stopwords PT-BR (mais completa; ajuste livre)
STOPWORDS_PT = {
    # artigos / preposições / conjunções
    "a","à","ao","aos","as","às","com","como","da","das","de","do","dos","e","é","em","entre","para","por","pra",
    "pro","pros","pra","pras","no","nos","na","nas","num","numa","nuns","numas","o","os","um","uma","uns","umas",
    "ou","nem","mas","porque","pois","que","quem","qual","quais","quando","onde","quanto","quantos","quantas",
    "se","sem","sobre","sob","até","apos","após","desde","durante","antes","depois","também","tb","tmb",
    "já","ainda","sempre","nunca","muito","muita","muitos","muitas","mais","menos","bem","mal","lá","la","aqui","ali",
    "cada","todo","toda","todos","todas","algo","alguem","alguém","ninguem","ninguém","mesmo","mesma","mesmos","mesmas",
    "outro","outra","outros","outras",

    # pronomes / formas comuns
    "eu","tu","ele","ela","nós","nos","vós","vos","eles","elas","me","te","se","lhe","lhes",
    "minha","meu","meus","minhas","sua","seu","seus","suas","nossa","nosso","nossos","nossas",
    "essa","esse","isso","isto","esta","este","aquelas","aqueles","aquela","aquele",
    "está","estao","estão","tá","ta","tô","to","era","eram","ser","sou","são",
    "vai","vou","foi","foram","tem","têm","ter","tinha","tinham","faz","fazem","feito",

    # respostas curtas / internetês
    "sim","não","nao","ok","oks","blz","beleza","tipo","assim","kk","kkk","haha","rs","rss","mds",

    # ruído típico
    "resposta","respostas","pergunta","perguntas","participante","participantes","tema","assunto",
    "aula","curso","uc","disciplina"  # remova se quiser contar esses termos
}

# -----------------------------
# Admin auth via secrets/env
# -----------------------------
# No Streamlit Cloud, use Secrets (não commitar):
# ADMIN_USER="admin"
# ADMIN_PASS="senha_forte"
ADMIN_USER = st.secrets.get("ADMIN_USER", os.getenv("ADMIN_USER", "admin"))
ADMIN_PASS = st.secrets.get("ADMIN_PASS", os.getenv("ADMIN_PASS", ""))  # deixe vazio até configurar

def check_admin(user: str, pwd: str) -> bool:
    return (
        hmac.compare_digest(user or "", ADMIN_USER or "")
        and hmac.compare_digest(pwd or "", ADMIN_PASS or "")
    )


# -----------------------------
# Lock (recomendado)
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
# Persistência (pergunta + respostas)
# -----------------------------
def _empty_data() -> Dict:
    return {
        "question": DEFAULT_QUESTION,
        "entries": [],  # lista de {"text": "...", "ts": 1234567890}
        "created_at": time.time(),
        "updated_at": time.time(),
    }

def _read_data() -> Dict:
    if not DATA_PATH.exists():
        return _empty_data()
    try:
        with open(DATA_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        if "question" not in data:
            data["question"] = DEFAULT_QUESTION
        if "entries" not in data:
            data["entries"] = []
        return data
    except Exception:
        return _empty_data()

def _write_data(data: Dict):
    data["updated_at"] = time.time()
    with open(DATA_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def load_data() -> Dict:
    def inner():
        return _read_data()
    return with_lock(inner)

def load_question() -> str:
    q = load_data().get("question", DEFAULT_QUESTION)
    q = (q or DEFAULT_QUESTION).strip()
    return q if q else DEFAULT_QUESTION

def load_entries() -> List[Dict]:
    return load_data().get("entries", []) or []

def append_entry(text: str):
    def inner():
        data = _read_data()
        entries = data.get("entries", []) or []
        entries.append({"text": text, "ts": time.time()})
        data["entries"] = entries
        _write_data(data)
    return with_lock(inner)

def clear_all_entries():
    def inner():
        data = _read_data()
        data["entries"] = []
        _write_data(data)
    return with_lock(inner)

def set_question(new_q: str):
    def inner():
        data = _read_data()
        data["question"] = (new_q or DEFAULT_QUESTION).strip() or DEFAULT_QUESTION
        _write_data(data)
    return with_lock(inner)


# -----------------------------
# Texto → tokens (para nuvem)
# -----------------------------
_word_re = re.compile(r"[a-zà-ÿ]+", flags=re.IGNORECASE)

def normalizar_texto(t: str) -> str:
    t = (t or "").lower().strip()
    t = re.sub(r"\s+", " ", t)
    return t

def tokenizar(texto: str) -> List[str]:
    texto = normalizar_texto(texto)
    tokens = _word_re.findall(texto)
    # remove stopwords, tokens muito curtos e números (já filtrados pelo regex)
    out = []
    for tk in tokens:
        tk = tk.strip().lower()
        if len(tk) < 2:
            continue
        if tk in STOPWORDS_PT:
            continue
        out.append(tk)
    return out


# -----------------------------
# WordCloud
# -----------------------------
import numpy as np
from collections import Counter

def gerar_wordcloud_fig(tokens: list[str]):
    if not tokens:
        return None

    freqs = Counter(tokens)
    if not freqs:
        return None

    wc = WordCloud(
        width=1800,
        height=900,
        background_color=None,      # fundo transparente (moderno)
        mode="RGBA",
        colormap="magma",           # paleta moderna (alternativas: viridis, plasma, inferno)
        prefer_horizontal=0.92,
        relative_scaling=0.4,
        min_font_size=12,
        max_words=220,
        collocations=False,
        contour_width=2,
        contour_color="#111827",    # cinza escuro elegante
        random_state=42
    ).generate_from_frequencies(freqs)

    fig, ax = plt.subplots(figsize=(16, 7), dpi=160)
    ax.imshow(wc, interpolation="bilinear")
    ax.axis("off")
    fig.patch.set_alpha(0.0)       # remove fundo branco do matplotlib
    return fig

"""
def gerar_wordcloud_fig(tokens: List[str]) -> Optional[plt.Figure]:
    if not tokens:
        return None

    text = " ".join(tokens).strip()
    if not text:
        return None

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
"""

# -----------------------------
# Estado
# -----------------------------
if "is_admin" not in st.session_state:
    st.session_state.is_admin = False

if "input_answer" not in st.session_state:
    st.session_state.input_answer = ""

if "admin_question_draft" not in st.session_state:
    st.session_state.admin_question_draft = ""

if "admin_api_key" not in st.session_state:
    st.session_state.admin_api_key = ""  # o admin digita na hora

if "relatorio" not in st.session_state:
    st.session_state.relatorio = ""

# -----------------------------
# Callback público: adiciona resposta
# -----------------------------
def on_answer_change():
    raw = st.session_state.get("input_answer", "")
    st.session_state.input_answer = ""  # limpa campo (OK no callback)
    raw = (raw or "").strip()
    if not raw:
        return
    # limita tamanho para evitar abuso acidental
    raw = raw[:200]
    append_entry(raw)


# -----------------------------
# ChatGPT (somente admin) - gerar relatório
# -----------------------------
def gerar_relatorio_chatgpt(api_key: str, pergunta: str, respostas: List[str]) -> str:
    if not OPENAI_AVAILABLE:
        return "⚠️ O pacote 'openai' não está instalado. Adicione 'openai' no requirements.txt."

    api_key = (api_key or "").strip()
    if not api_key:
        return "⚠️ Informe a OPENAI_API_KEY no campo de Admin para gerar o relatório."

    client = OpenAI(api_key=api_key)

    # reduz volume: pega todas (até um limite) e também um resumo estatístico simples
    # (você pode ajustar limites para custo/velocidade)
    respostas = [r.strip() for r in respostas if r and r.strip()]
    total = len(respostas)

    # tokens para estatísticas
    all_tokens = []
    for r in respostas:
        all_tokens.extend(tokenizar(r))
    top_tokens = Counter(all_tokens).most_common(25)

    # amostra das respostas (para contexto qualitativo)
    sample = respostas[:250]  # limite simples
    respostas_bullets = "\n".join(f"- {s}" for s in sample)

    top_tokens_text = "\n".join([f"- {w}: {c}" for w, c in top_tokens])

    prompt = f"""
Você é um analista de pesquisa educacional. Gere um relatório em português (tom institucional, claro e objetivo)
com base na pergunta e nas respostas coletadas.

Pergunta:
{pergunta}

Métricas rápidas:
- Total de respostas: {total}

Top termos (após filtragem de stopwords):
{top_tokens_text if top_tokens_text else "- (sem termos suficientes)"}

Respostas (amostra/lista):
{respostas_bullets if respostas_bullets else "- (sem respostas)"}

Regras:
- Não invente dados que não estejam nas respostas.
- Se houver ambiguidade/baixa evidência, sinalize como hipótese.

Estrutura do relatório:
1) Visão geral (2–4 linhas)
2) Principais temas percebidos (bullet points)
3) Interpretações e possíveis significados (curto e direto)
4) Pontos de atenção (viés, ruído, termos ambíguos, respostas muito curtas)
5) Recomendações práticas (3 a 6 ações)
6) Síntese final (1 parágrafo)
"""

    resp = client.responses.create(
        model="gpt-4.1-mini",
        input=prompt,
    )
    return getattr(resp, "output_text", "") or "(sem texto retornado)"


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
    st.caption("Área dedicado aos administradores.")


# -----------------------------
# UI principal
# -----------------------------
col1, col2 = st.columns([2, 1], gap="large")

with col1:
    pergunta = load_question()

    #st.markdown("## Pergunta")
    #st.info(pergunta)

    #st.markdown("### Pergunta")

    st.markdown(
    f"""
    <div style="
        font-size: 1.6rem;
        font-weight: 600;
        line-height: 1.4;
        padding: 1rem 1.2rem;
        border-left: 6px solid #4CAF50;
        background-color: #f8f9fa;
        border-radius: 6px;
        margin-bottom: 1rem;
    ">
        {pergunta}
    </div>
    """,
    unsafe_allow_html=True
    )




    
    st.markdown("### Professor, digite sua resposta e pressione Enter")
    st.text_input(
        "Resposta",
        key="input_answer",
        placeholder="Exemplo: colaboração",
        help="A nuvem atualiza quando você pressiona Enter.",
        on_change=on_answer_change,
        label_visibility="collapsed",
    )

    entries = load_entries()
    # tokens para nuvem
    tokens = []
    for e in entries:
        tokens.extend(tokenizar(e.get("text", "")))

    st.markdown("### ☁️ Nuvem de palavras")
    fig = gerar_wordcloud_fig(tokens)
    if fig is None:
        st.info("Ainda não há termos suficientes. Digite uma resposta e pressione Enter.")
    else:
        st.pyplot(fig, clear_figure=True)

with col2:
    st.subheader("📊 Resumo")

    entries = load_entries()
    respostas_brutas = [e.get("text", "") for e in entries]

    tokens = []
    for r in respostas_brutas:
        tokens.extend(tokenizar(r))

    cont = Counter(tokens)

    st.metric("Total de respostas", len(respostas_brutas))
    st.metric("Total de termos (filtrados)", sum(cont.values()))
    st.metric("Termos únicos", len(cont))

    st.markdown("### 🔝 Top palavras")
    top = cont.most_common(15)
    if top:
        st.table([{"termo": t, "freq": f} for t, f in top])
    else:
        st.caption("Sem dados ainda.")

    # -------- Admin controls --------
    if st.session_state.is_admin:
        st.divider()
        st.subheader("🛠️ Controles (Admin)")

        # Pergunta
        st.markdown("#### ✍️ Pergunta exibida ao público")
        if not st.session_state.admin_question_draft:
            st.session_state.admin_question_draft = load_question()

        st.text_area(
            "Editar pergunta",
            key="admin_question_draft",
            height=110,
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

        # Histórico
        st.markdown("#### 🧾 Histórico (Admin)")
        modo = st.radio("Visualização", ["Somente respostas (texto)", "Com data/hora"], horizontal=True)

        if modo == "Somente respostas (texto)":
            st.write(respostas_brutas[-300:])  # mostra as últimas 300
        else:
            linhas = []
            for e in entries[-300:]:
                ts = e.get("ts", None)
                dt = time.strftime("%d/%m/%Y %H:%M:%S", time.localtime(ts)) if ts else ""
                linhas.append({"data_hora": dt, "resposta": e.get("text", "")})
            st.dataframe(linhas, use_container_width=True, hide_index=True)

        # Zerar
        st.markdown("#### 🧹 Limpeza")
        if st.button("Zerar nuvem (limpar respostas)"):
            clear_all_entries()
            st.success("Respostas apagadas. Nuvem zerada.")
            st.session_state.relatorio = ""
            st.rerun()

        # Relatório via ChatGPT
        st.divider()
        st.subheader("🧠 Relatório automático (ChatGPT)")

        if not OPENAI_AVAILABLE:
            st.warning("O pacote 'openai' não está instalado. Inclua 'openai' no requirements.txt.")
        else:
            st.text_input(
                "OPENAI_API_KEY (digite na hora — não será salva no GitHub)",
                key="admin_api_key",
                type="password",
                placeholder="sk-...",
                help="A chave fica apenas na sessão do navegador (não é persistida em arquivo).",
            )

            st.caption("O relatório usa a pergunta atual + respostas coletadas (com amostra e top termos).")

            if st.button("📄 Gerar relatório"):
                with st.spinner("Gerando relatório..."):
                    st.session_state.relatorio = gerar_relatorio_chatgpt(
                        api_key=st.session_state.admin_api_key,
                        pergunta=pergunta,
                        respostas=respostas_brutas,
                    )

            if st.session_state.relatorio:
                st.text_area("Relatório", st.session_state.relatorio, height=360)

    else:
        st.caption(":)")

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
