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
st.set_page_config(page_title="Nuvem de Palavras", layout="wide")
st.title("☁️ Nuvem de Palavras")

DATA_PATH = Path("data_words.json")

DEFAULT_QUESTION = "Digite uma palavra ou pequena frase que represente sua percepção sobre o tema."

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
2)
