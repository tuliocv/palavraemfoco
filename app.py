# app.py
# Público: acessa sem login e digita respostas (texto curto).
# Público só vê a nuvem depois que o admin clicar em "Revelar nuvem ao público".
# Admin (login/senha): pode (1) definir a pergunta, (2) ver histórico, (3) zerar, (4) gerar relatório via ChatGPT,
# (5) controlar o botão "Revelar".
#
# requirements.txt sugerido:
# streamlit
# wordcloud
# matplotlib
# filelock
# openai
#
# (Opcional para banner via PIL: pillow — NÃO é necessário aqui)

import json
import os
import re
import time
import hmac
import base64
import colorsys
from collections import Counter
from pathlib import Path
from typing import List, Dict

import streamlit as st
import matplotlib.pyplot as plt
from wordcloud import WordCloud

# OpenAI (SDK oficial) - somente admin
try:
    from openai import OpenAI
    OPENAI_AVAILABLE = True
except Exception:
    OPENAI_AVAILABLE = False

# =============================
# CONFIG (PRECISA SER O PRIMEIRO st.*)
# =============================
st.set_page_config(page_title="WordPulse - v1", layout="wide")

# =============================
# Banner
# =============================
def add_banner(image_path: str, height_px: int = 200):
    try:
        with open(image_path, "rb") as f:
            data = base64.b64encode(f.read()).decode()
        st.markdown(
            f"""
            <style>
            .top-banner {{
                height: {height_px}px;
                background-image: url("data:image/png;base64,{data}");
                background-size: cover;
                background-position: center;
                border-radius: 12px;
                margin-bottom: 1rem;
                position: relative;
                overflow: hidden;
            }}
            .top-banner::after {{
                content: "";
                position: absolute;
                inset: 0;
                background: rgba(0,0,0,0.18);
            }}
            </style>

            <div class="top-banner"></div>
            """,
            unsafe_allow_html=True
        )
    except FileNotFoundError:
        st.warning("Banner não encontrado em assets/banner.png (ok continuar sem banner).")

add_banner("assets/banner.png", height_px=200)
st.markdown("## ☁️ WordPulse - A Nuvem de Palavras da Gerência de Avaliação")

# =============================
# CSS (espaçamento + ajustes gerais)
# =============================
st.markdown(
    """
    <style>
        .block-container { padding-top: 2.2rem; }
        h1, h2, h3 { margin-bottom: 1.2rem !important; }
        p { margin-bottom: 1.0rem !important; }
        div[data-baseweb="input"] { margin-bottom: 1.6rem; }
        div.stAlert { margin-top: 1.2rem; margin-bottom: 1.2rem; }
    </style>
    """,
    unsafe_allow_html=True
)

# =============================
# Paths / Defaults
# =============================
DATA_PATH = Path("data_words.json")
DEFAULT_QUESTION = "Digite uma palavra que represente sua percepção sobre o tema."

STOPWORDS_PT = {
    "a","à","ao","aos","as","às","com","como","da","das","de","do","dos","e","é","em","entre","para","por","pra",
    "pro","pros","pras","no","nos","na","nas","num","numa","nuns","numas","o","os","um","uma","uns","umas",
    "ou","nem","mas","porque","pois","que","quem","qual","quais","quando","onde","quanto","quantos","quantas",
    "se","sem","sobre","sob","até","apos","após","desde","durante","antes","depois","também","tb","tmb",
    "já","ainda","sempre","nunca","muito","muita","muitos","muitas","mais","menos","bem","mal","lá","la","aqui","ali",
    "cada","todo","toda","todos","todas","algo","alguem","alguém","ninguem","ninguém","mesmo","mesma","mesmos","mesmas",
    "outro","outra","outros","outras",
    "eu","tu","ele","ela","nós","nos","vós","vos","eles","elas","me","te","se","lhe","lhes",
    "minha","meu","meus","minhas","sua","seu","seus","suas","nossa","nosso","nossos","nossas",
    "essa","esse","isso","isto","esta","este","aquelas","aqueles","aquela","aquele",
    "está","estao","estão","tá","ta","tô","to","era","eram","ser","sou","são",
    "vai","vou","foi","foram","tem","têm","ter","tinha","tinham","faz","fazem","feito",
    "sim","não","nao","ok","oks","blz","beleza","tipo","assim","kk","kkk","haha","rs","rss","mds",
    "resposta","respostas","pergunta","perguntas","participante","participantes","tema","assunto",
    "aula","curso","uc","disciplina"
}

# =============================
# Lock (recomendado)
# =============================
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

# =============================
# Persistência (pergunta + respostas + controle de revelação)
# =============================
def _empty_data() -> Dict:
    return {
        "question": DEFAULT_QUESTION,
        "entries": [],                 # {"text": "...", "ts": 123}
        "public_show_cloud": False,    # 👈 público só vê após revelar
        "created_at": time.time(),
        "updated_at": time.time(),
    }

def _read_data() -> Dict:
    if not DATA_PATH.exists():
        return _empty_data()
    try:
        with open(DATA_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)

        data.setdefault("question", DEFAULT_QUESTION)
        data.setdefault("entries", [])
        data.setdefault("public_show_cloud", False)

        return data
    except Exception:
        return _empty_data()

def _write_data(data: Dict):
    data["updated_at"] = time.time()
    with open(DATA_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def load_data() -> Dict:
    return with_lock(_read_data)

def load_question() -> str:
    q = load_data().get("question", DEFAULT_QUESTION)
    return (q or DEFAULT_QUESTION).strip() or DEFAULT_QUESTION

def load_entries() -> List[Dict]:
    return load_data().get("entries", []) or []

def append_entry(text: str):
    def inner():
        data = _read_data()
        data["entries"].append({"text": text, "ts": time.time()})
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

def load_public_show_cloud() -> bool:
    return bool(load_data().get("public_show_cloud", False))

def set_public_show_cloud(show: bool):
    def inner():
        data = _read_data()
        data["public_show_cloud"] = bool(show)
        _write_data(data)
    return with_lock(inner)

# =============================
# Tokenização
# =============================
_word_re = re.compile(r"[a-zà-ÿ]+", flags=re.IGNORECASE)

def tokenizar(texto: str) -> List[str]:
    texto = (texto or "").lower().strip()
    texto = re.sub(r"\s+", " ", texto)
    tokens = _word_re.findall(texto)

    out = []
    for tk in tokens:
        tk = tk.lower().strip()
        if len(tk) < 2:
            continue
        if tk in STOPWORDS_PT:
            continue
        out.append(tk)
    return out

# =============================
# WordCloud moderno (freq -> cor e tamanho) + vertical/horizontal
# =============================
def gerar_wordcloud_fig(tokens: List[str]):
    if not tokens:
        return None

    freqs = Counter(tokens)
    if not freqs:
        return None

    max_f = max(freqs.values())

    def color_func(word, font_size, position, orientation, random_state=None, **kwargs):
        f = freqs.get(word, 1) / max_f
        hue = 0.66 - 0.66 * f  # azul -> vermelho conforme frequência
        sat = 0.95
        val = 0.95
        r, g, b = colorsys.hsv_to_rgb(hue, sat, val)
        return f"rgb({int(r*255)}, {int(g*255)}, {int(b*255)})"

    wc = WordCloud(
        width=1800,
        height=900,
        background_color="white",
        mode="RGB",
        prefer_horizontal=0.65,  # horizontal + vertical
        relative_scaling=1.0,    # diferencia bem por frequência
        min_font_size=10,
        max_font_size=260,
        max_words=250,
        collocations=False,
        random_state=42,
        margin=2
    ).generate_from_frequencies(freqs)

    wc = wc.recolor(color_func=color_func, random_state=42)

    fig, ax = plt.subplots(figsize=(16, 7), dpi=160)
    ax.imshow(wc, interpolation="bilinear")
    ax.axis("off")
    return fig

# =============================
# Admin auth
# =============================
ADMIN_USER = st.secrets.get("ADMIN_USER", os.getenv("ADMIN_USER", "admin"))
ADMIN_PASS = st.secrets.get("ADMIN_PASS", os.getenv("ADMIN_PASS", ""))  # defina nos secrets

def check_admin(user: str, pwd: str) -> bool:
    return hmac.compare_digest(user or "", ADMIN_USER or "") and hmac.compare_digest(pwd or "", ADMIN_PASS or "")

# =============================
# Session state
# =============================
st.session_state.setdefault("is_admin", False)
st.session_state.setdefault("input_answer", "")
st.session_state.setdefault("admin_question_draft", "")
st.session_state.setdefault("admin_api_key", "")
st.session_state.setdefault("relatorio", "")

# =============================
# Callback público
# =============================
def on_answer_change():
    raw = st.session_state.get("input_answer", "")
    st.session_state.input_answer = ""
    raw = (raw or "").strip()
    if not raw:
        return
    append_entry(raw[:200])

# =============================
# Sidebar admin
# =============================
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
    st.caption("Área dedicada aos administradores.")

# =============================
# Dados (carregar uma vez)
# =============================
public_show = load_public_show_cloud()
entries_all = load_entries()
respostas_all = [e.get("text", "") for e in entries_all]

# tokens só são calculados quando necessário (admin ou público após revelado)
def compute_tokens_from_respostas(respostas: List[str]) -> List[str]:
    toks: List[str] = []
    for r in respostas:
        toks.extend(tokenizar(r))
    return toks

# =============================
# UI principal
# =============================
col1, col2 = st.columns([2, 1], gap="large")

with col1:
    pergunta = load_question()

    # Caixa pergunta com tema claro/escuro
    st.markdown(
        f"""
        <style>
            .question-box {{
                font-size: 1.6rem;
                font-weight: 650;
                line-height: 1.5;
                padding: 1rem 1.2rem;
                border-left: 6px solid #22c55e;
                border-radius: 10px;
                margin-bottom: 1.6rem;
                color: #111827;
                background-color: #f8f9fa;
            }}
            @media (prefers-color-scheme: dark) {{
                .question-box {{
                    color: #e5e7eb;
                    background-color: #0f172a;
                    border-left-color: #22c55e;
                }}
            }}
        </style>
        <div class="question-box">{pergunta}</div>
        """,
        unsafe_allow_html=True
    )

    st.markdown("#### Professor, digite sua resposta e pressione Enter")
    st.text_input(
        "Resposta",
        key="input_answer",
        placeholder="Exemplo: colaboração",
        help="Sua resposta será registrada ao pressionar Enter.",
        on_change=on_answer_change,
        label_visibility="collapsed",
    )

    st.markdown("#### ☁️ Nuvem de palavras")

    # Público só vê após "Revelar"
    if (not st.session_state.is_admin) and (not public_show):
        st.info("🔒 Coleta em andamento. A nuvem será revelada pelo administrador ao final.")
    else:
        tokens_all = compute_tokens_from_respostas(respostas_all)
        fig = gerar_wordcloud_fig(tokens_all)
        if fig is None:
            st.info("Ainda não há termos suficientes. Digite uma resposta e pressione Enter.")
        else:
            st.pyplot(fig, clear_figure=True)

with col2:
    # Público: coluna leve (sem top/explorar)
    if not st.session_state.is_admin:
        st.subheader("📌 Informações")
        st.metric("Total de respostas recebidas", len(respostas_all))
        if public_show:
            st.caption("A nuvem foi revelada pelo administrador.")
        else:
            st.caption("Envie sua resposta. A nuvem será exibida ao final.")
    else:
        # ADMIN: resumo + top + explorar + controles
        st.subheader("📊 Resumo (Admin)")

        tokens_all = compute_tokens_from_respostas(respostas_all)
        cont = Counter(tokens_all)

        st.metric("Total de respostas", len(respostas_all))
        st.metric("Total de termos (filtrados)", sum(cont.values()))
        st.metric("Termos únicos", len(cont))

        st.markdown("### 🔝 Top palavras (Admin)")
        top = cont.most_common(15)
        if top:
            st.table([{"termo": t, "freq": f} for t, f in top])
        else:
            st.caption("Sem dados ainda.")

        st.divider()
        st.subheader("🔎 Explorar uma palavra (Admin)")
        termos_disponiveis = [t for t, _ in cont.most_common(80)]
        if termos_disponiveis:
            termo_sel = st.selectbox("Selecione uma palavra", termos_disponiveis, index=0)
            st.write(f"**Frequência:** {cont.get(termo_sel, 0)}")

            exemplos = [txt for txt in respostas_all if termo_sel.lower() in (txt or "").lower()]
            if exemplos:
                st.markdown("**Exemplos (até 10):**")
                for ex in exemplos[:10]:
                    st.write(f"- {ex}")
                if len(exemplos) > 10:
                    st.caption(f"Mostrando 10 de {len(exemplos)} exemplos.")
            else:
                st.caption("Nenhum exemplo encontrado.")
        else:
            st.caption("Digite respostas para habilitar a exploração.")

        st.divider()
        st.subheader("👥 Exibição para o público (Admin)")

        public_show = load_public_show_cloud()
        st.caption(f"Status atual: público {'VÊ' if public_show else 'NÃO VÊ'} a nuvem.")

        c1, c2 = st.columns(2)
        with c1:
            if st.button("🟡 Modo Coleta (ocultar do público)"):
                set_public_show_cloud(False)
                st.success("Público NÃO verá a nuvem durante a coleta.")
                st.rerun()

        with c2:
            if st.button("🟢 Revelar nuvem ao público"):
                set_public_show_cloud(True)
                st.success("Nuvem revelada ao público.")
                st.rerun()

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

        b1, b2 = st.columns(2)
        with b1:
            if st.button("💾 Salvar pergunta"):
                set_question(st.session_state.admin_question_draft)
                st.success("Pergunta atualizada.")
                st.rerun()
        with b2:
            if st.button("↩️ Restaurar padrão"):
                st.session_state.admin_question_draft = DEFAULT_QUESTION
                set_question(DEFAULT_QUESTION)
                st.info("Pergunta restaurada para o padrão.")
                st.rerun()

        # Histórico
        st.markdown("#### 🧾 Histórico (Admin)")
        modo = st.radio("Visualização", ["Somente respostas (texto)", "Com data/hora"], horizontal=True)

        if modo == "Somente respostas (texto)":
            st.write(respostas_all[-300:])
        else:
            linhas = []
            for e in entries_all[-300:]:
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
            # Quando zera, volta para coleta (opcional)
            set_public_show_cloud(False)
            st.rerun()

        # Relatório via ChatGPT (somente admin)
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
            )

            def gerar_relatorio_chatgpt(api_key: str, pergunta: str, respostas: List[str]) -> str:
                api_key = (api_key or "").strip()
                if not api_key:
                    return "⚠️ Informe a OPENAI_API_KEY no campo acima."

                client = OpenAI(api_key=api_key)

                respostas = [r.strip() for r in respostas if r and r.strip()]
                total = len(respostas)

                all_tokens2 = []
                for r in respostas:
                    all_tokens2.extend(tokenizar(r))
                top_tokens = Counter(all_tokens2).most_common(25)

                sample = respostas[:250]
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
                resp = client.responses.create(model="gpt-4.1-mini", input=prompt)
                return getattr(resp, "output_text", "") or "(sem texto retornado)"

            st.caption("O relatório usa a pergunta atual + TODAS as respostas do histórico.")

            if st.button("📄 Gerar relatório"):
                with st.spinner("Gerando relatório..."):
                    st.session_state.relatorio = gerar_relatorio_chatgpt(
                        api_key=st.session_state.admin_api_key,
                        pergunta=load_question(),
                        respostas=respostas_all,
                    )

            if st.session_state.relatorio:
                st.text_area("Relatório", st.session_state.relatorio, height=360)

# =============================
# Rodapé
# =============================
st.markdown(
    """
    <hr style="margin-top: 3rem; margin-bottom: 1rem;">
    <div style="text-align: center; font-size: 0.9rem; color: #6c757d;">
        App desenvolvido pela <strong>Gerência de Avaliação</strong> • 02/02/2026
    </div>
    """,
    unsafe_allow_html=True
)
