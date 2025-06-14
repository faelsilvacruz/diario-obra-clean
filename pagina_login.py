import streamlit as st
import sqlite3
import hashlib

# Funções de hash para senha
def make_hashes(password):
    return hashlib.sha256(str.encode(password)).hexdigest()

def check_hashes(password, hashed_text):
    return make_hashes(password) == hashed_text

# Conexão com banco de dados
conn = sqlite3.connect('users.db')
c = conn.cursor()

def login_user(username, password):
    c.execute('SELECT * FROM userstable WHERE username =? AND password = ?', (username, password))
    data = c.fetchall()
    return data

# Estilo customizado
st.markdown(
    """
    <style>
    body {
        background-color: #0F2A4D;
    }
    .stApp {
        background-color: #0F2A4D;
    }
    .login-box {
        background-color: white;
        padding: 40px 30px;
        border-radius: 12px;
        box-shadow: 0px 0px 20px rgba(0,0,0,0.5);
        text-align: center;
        max-width: 400px;
        margin: auto;
        margin-top: 80px;
    }
    .login-title {
        color: #0F2A4D;
        font-size: 24px;
        margin-bottom: 20px;
    }
    .logo-img {
        margin-top: 30px;
    }
    </style>
    """, unsafe_allow_html=True
)

def main():
    st.markdown('<div class="login-box">', unsafe_allow_html=True)
    st.markdown('<div class="login-title">Acesso ao Diário de Obra</div>', unsafe_allow_html=True)

    username = st.text_input('Usuário')
    password = st.text_input('Senha', type='password')

    if st.button('Entrar'):
        hashed_pswd = make_hashes(password)
        result = login_user(username, hashed_pswd)
        if result:
            st.success(f'Bem-vindo, {username}! Login realizado com sucesso.')
            st.info('Aqui você carregaria o restante do app...')
        else:
            st.error('Usuário ou senha inválidos.')

    # Logo abaixo
    st.markdown('<div class="logo-img">', unsafe_allow_html=True)
    st.image('logo_rdv.png', width=150)
    st.markdown('</div>', unsafe_allow_html=True)

    st.markdown('</div>', unsafe_allow_html=True)

if __name__ == '__main__':
    main()
