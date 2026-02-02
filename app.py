import re
from collections import Counter

import streamlit as st
from wordcloud import WordCloud
import matplotlib.pyplot as plt

st.set_page_config(page_title="Nuvem em tempo real", layout="wide")
st.title("☁️ Nuvem de palavras (digitando no app)")

# -------------------------
# Estado
# -------------------------
if "palavras" not in st.session_state:
    st.session_state.palavras = []

# Stopwords PT-BR (bem básico — ajuste se quiser)
STOPWORDS_PT = {
    "a","à","ao","aos","as","às","com","como","da","das","de","do","dos","e","é","em","entre",
    "na","nas","no","nos","o","os","ou","para","por","que","se","sem","um","uma","não","nao",
    "sim","já","tá","tô","vc","vcs","você","vocês"
}

def limpar_token(t: str) -> str:
    t = t.lower().strip()
    t = re.sub(r"[^a-zà-ÿ]", "", t)  # mantém letras (com acento)
    return t

def gerar_wordcloud(palavras):
    texto = " ".join(palavras) if palavras else ""
    wc = WordCloud(
        width=1600,
        height=800,
        background_color="white",
        colormap="viridis",
        stopwords=STOPWORDS_PT,
        collocations=False,
        max_words=250
    ).generate(texto if texto else " ")
    fig, ax = plt.subplots(figsize=(16, 8))
    ax.imshow(wc, interpolation="bilinear")
    ax.axis("off")
    return fig

# -------------------------
# UI
# -------------------------
col1, col2 = st.columns([2, 1], gap="large")

with col1:
    st.subheader("Digite uma palavra e pressione Enter")
    palavra = st.text_input("Palavra", placeholder="Ex.: colaboração")

    # Adiciona automaticamente ao apertar Enter (text_input dispara rerun)
    if palavra:
        token = limpar_token(palavra)
        if token and token not in STOPWORDS_PT:
            # Evita duplicar quando a pessoa dá rerun sem mudar o texto
            # (o Streamlit reexecuta; então usamos uma chave auxiliar)
            if st.session_state.get("_ultima_adicionada") != token:
                st.session_state.palavras.append(token)
                st.session_state._ultima_adicionada = token

    st.markdown("### Nuvem de palavras")
    fig = gerar_wordcloud(st.session_state.palavras)
    st.pyplot(fig, clear_figure=True)

with col2:
    st.subheader("Controles")
    st.metric("Total de palavras", len(st.session_state.palavras))

    if st.button("↩️ Desfazer última"):
        if st.session_state.palavras:
            st.session_state.palavras.pop()

    if st.button("🧹 Limpar tudo"):
        st.session_state.palavras = []
        st.session_state._ultima_adicionada = ""

    st.markdown("### Top palavras")
    cont = Counter(st.session_state.palavras)
    top = cont.most_common(15)
    if top:
        st.table([{"palavra": p, "freq": f} for p, f in top])
    else:
        st.caption("Ainda sem dados.")

    st.markdown("### Histórico (últimas 30)")
    st.write(st.session_state.palavras[-30:])
