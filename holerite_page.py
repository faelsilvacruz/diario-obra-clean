import streamlit as st
import sqlite3

def render_holerite_page():
    st.title("📄 Holerites - RDV Engenharia")

    # Verificar se o usuário está logado
    if "username" not in st.session_state or not st.session_state["username"]:
        st.warning("Por favor, faça login para visualizar seus holerites.")
        return

    nome_colaborador = st.session_state["username"]

    conn = sqlite3.connect("holerites.db")
    cursor = conn.cursor()

    cursor.execute("""
        SELECT mes, ano, link_google_drive
        FROM holerites
        WHERE nome_colaborador LIKE ?
        ORDER BY ano DESC, mes DESC
    """, (f"%{nome_colaborador}%",))
    resultados = cursor.fetchall()
    conn.close()

    st.markdown("""
        <style>
        .holerite-card {
            background-color: #0F2A4D;
            color: white;
            padding: 15px;
            border-radius: 10px;
            margin-bottom: 15px;
            box-shadow: 2px 2px 5px rgba(0,0,0,0.2);
        }
        .holerite-card a {
            color: #FFD700;
            text-decoration: none;
            font-weight: bold;
        }
        .holerite-card a:hover {
            text-decoration: underline;
        }
        </style>
    """, unsafe_allow_html=True)

    if resultados:
        st.success(f"Holorites disponíveis para: **{nome_colaborador}**")
        for mes, ano, link in resultados:
            st.markdown(f"""
                <div class="holerite-card">
                    📅 <strong>{mes}/{ano}</strong><br>
                    🔗 <a href="{link}" target="_blank">Clique aqui para abrir o Holerite</a>
                </div>
            """, unsafe_allow_html=True)
    else:
        st.info("Nenhum holerite disponível para você no momento.")
