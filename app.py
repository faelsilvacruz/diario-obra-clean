import streamlit as st
import pandas as pd
from datetime import datetime
from pathlib import Path
from PIL import Image as PILImage
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader
from reportlab.lib.colors import HexColor, black, lightgrey, white, darkgrey
from reportlab.platypus import Table, TableStyle, Paragraph
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
import os
import io
import json
import yagmail
import tempfile
import shutil

# --- INÍCIO DO BLOCO DE DEBUG ---
st.write("DEBUG: Aplicação Streamlit iniciada. Ponto 1.")
st.write(f"DEBUG: Caminho da logo de login: {st.session_state.get('LOGO_LOGIN_PATH', 'Não definido')}")
st.write(f"DEBUG: Caminho da logo PDF: {st.session_state.get('LOGO_PDF_PATH', 'Não definido')}")
st.write(f"DEBUG: Caminho da logo ícone: {st.session_state.get('LOGO_ICON_PATH', 'Não definido')}")

# Google API imports
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
from googleapiclient.errors import HttpError

# Autenticação de Usuário imports
import sqlite3
import hashlib
import base64

# ✅ CONSTANTES
# ID da pasta no Google Drive onde os arquivos CSV e PDFs serão armazenados
# Substitua pelo ID real da sua pasta no Google Drive
# Certifique-se de que este ID está também no seu .streamlit/secrets.toml sob [google_drive] folder_id = "SEU_ID"
DRIVE_FOLDER_ID = st.secrets["google_drive"]["folder_id"] 
# Caminhos para as logos (ajuste se necessário. Devem estar na mesma pasta do app.py)
LOGO_LOGIN_PATH = "LOGO RDV AZUL.jpeg" # Para a tela de login
LOGO_PDF_PATH = "LOGO_RDV_AZUL-sem fundo.png" # Para o cabeçalho do PDF
LOGO_ICON_PATH = "LOGO_RDV_AZUL-sem fundo.png" # Usando a mesma logo do PDF para o ícone da página

# ✅ CONFIGURAÇÃO STREAMLIT
st.set_page_config(
    page_title="RDV Engenharia - Relatório Diário de Obra",
    page_icon=PILImage.open(LOGO_ICON_PATH) if os.path.exists(LOGO_ICON_PATH) else "👷‍♂️",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ✅ FUNÇÕES AUXILIARES DE IMAGEM
@st.cache_data(ttl=3600)
def get_img_as_base64(file_path):
    """Carrega uma imagem e a converte para base64 para uso em Markdown/HTML."""
    try:
        with open(file_path, "rb") as f:
            return base64.b64encode(f.read()).decode()
    except FileNotFoundError:
        st.error(f"Erro: Arquivo de imagem não encontrado em {file_path}. Verifique o caminho.")
        return None
    except Exception as e:
        st.error(f"Erro ao carregar imagem {file_path}: {e}")
        return None

# Variável global para armazenar o caminho temporário do ícone (se usado) para limpeza
temp_icon_path_for_cleanup = None

def clear_icon_temp_file():
    """Tenta limpar o arquivo temporário usado para o ícone da página."""
    global temp_icon_path_for_cleanup
    if temp_icon_path_for_cleanup and os.path.exists(temp_icon_path_for_cleanup):
        try:
            os.remove(temp_icon_path_for_cleanup)
            temp_icon_path_for_cleanup = None # Reset
            # st.info("Arquivo temporário do ícone limpo com sucesso.") # Para depuração
        except Exception as e:
            st.warning(f"Erro ao tentar limpar arquivo temporário do ícone: {str(e)}. Por favor, verifique os logs.")

# ✅ FUNÇÕES AUXILIARES DE AUTENTICAÇÃO (SQLite)
DB_NAME = "users.db" # Nome do arquivo do banco de dados SQLite

def make_hashes(password):
    """Gera um hash SHA256 da senha."""
    return hashlib.sha256(str.encode(password)).hexdigest()

def check_hashes(password, hashed_password):
    """Verifica se a senha fornecida corresponde ao hash armazenado."""
    return make_hashes(password) == hashed_password

def create_usertable():
    """Cria a tabela de usuários se ela não existir no banco de dados."""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS userstable (
            username TEXT UNIQUE,
            password TEXT,
            role TEXT
        )
    ''')
    conn.commit()
    conn.close()

def add_userdata(username, password, role="user"):
    """Adiciona um novo usuário ao banco de dados."""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    try:
        c.execute('INSERT INTO userstable (username, password, role) VALUES (?,?,?)', (username, password, role))
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        # st.error(f"Usuário '{username}' já existe.") # Comentado para evitar erro duplicado na UI
        return False
    finally:
        conn.close()

def login_user(username, password):
    """Tenta autenticar um usuário e retorna suas informações (usuário e função) se bem-sucedido."""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('SELECT * FROM userstable WHERE username = ?', (username,))
    data = c.fetchone()
    conn.close()
    if data:
        if check_hashes(password, data[1]):
            return {"username": data[0], "role": data[2]}
    return None

def view_all_users():
    """Retorna uma lista de todos os usuários registrados (apenas nome e função)."""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('SELECT username, role FROM userstable') # Não retornar o hash da senha por segurança
    data = c.fetchall()
    conn.close()
    return data

# ✅ FUNÇÕES AUXILIARES GOOGLE DRIVE
@st.cache_resource(ttl=3600)
def get_drive_service():
    """Autentica com o Google Drive API usando st.secrets."""
    try:
        creds = service_account.Credentials.from_service_account_info(
            st.secrets["gcp_service_account"],
            scopes=['https://www.googleapis.com/auth/drive']
        )
        return build('drive', 'v3', credentials=creds)
    except Exception as e:
        st.error(f"Erro ao autenticar com o Google Drive: {e}")
        st.info("Verifique se o `secrets.toml` está configurado corretamente com as credenciais da conta de serviço do GCP.")
        return None

@st.cache_data(ttl=3600) # Cache para não recarregar os dados do Drive a cada interação
def load_data_from_drive(folder_id, file_name):
    """Carrega um arquivo CSV do Google Drive e retorna um DataFrame."""
    service = get_drive_service()
    if not service:
        return pd.DataFrame()

    try:
        query = f"name = '{file_name}' and '{folder_id}' in parents and trashed = false"
        results = service.files().list(q=query, fields="files(id, name)").execute()
        items = results.get('files', [])

        if not items:
            # st.warning(f"Arquivo '{file_name}' não encontrado na pasta do Google Drive (ID: {folder_id}).") # Comentado para não poluir a UI
            return pd.DataFrame()

        file_id = items[0]['id']

        request = service.files().get_media(fileId=file_id)
        file_content = io.BytesIO(request.execute())
        
        return pd.read_csv(file_content)

    except HttpError as error:
        st.error(f"Erro ao acessar o Google Drive (HTTP) para '{file_name}': {error}")
        st.info("Verifique se o serviço do Drive está configurado e se as permissões estão corretas para a conta de serviço.")
        return pd.DataFrame()
    except Exception as e:
        st.error(f"Erro ao carregar '{file_name}' do Google Drive: {e}")
        return pd.DataFrame()

def create_drive_folder_if_not_exists(service, parent_folder_id, folder_name):
    """Cria uma pasta no Google Drive se ela não existir e retorna seu ID."""
    try:
        query = f"name = '{folder_name}' and '{parent_folder_id}' in parents and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
        results = service.files().list(q=query, fields="files(id, name)").execute()
        items = results.get('files', [])

        if items:
            return items[0]['id'] # Pasta já existe

        file_metadata = {
            'name': folder_name,
            'mimeType': 'application/vnd.google-apps.folder',
            'parents': [parent_folder_id]
        }
        folder = service.files().create(body=file_metadata, fields='id').execute()
        return folder.get('id')
    except Exception as e:
        st.error(f"Erro ao criar/verificar pasta '{folder_name}' no Google Drive: {e}")
        return None

def upload_file_to_drive(service, folder_id, file_name, file_content_bytes, mime_type):
    """Faz upload de um arquivo para o Google Drive."""
    try:
        file_metadata = {
            'name': file_name,
            'parents': [folder_id]
        }
        media = MediaIoBaseUpload(io.BytesIO(file_content_bytes), mimetype=mime_type, resumable=True)
        
        uploaded_file = service.files().create(body=file_metadata, media_body=media, fields='id').execute()
        return uploaded_file.get('id')
    except HttpError as error:
        st.error(f"Erro ao fazer upload para o Google Drive (HTTP): {error}")
        st.info("Verifique as permissões da conta de serviço para escrita na pasta.")
        return None
    except Exception as e:
        st.error(f"Erro desconhecido ao fazer upload para o Google Drive: {e}")
        return None

# ✅ FUNÇÃO AUXILIAR DE ENVIO DE E-MAIL
def send_email(subject, html_body, recipients, attachments=None):
    """Envia um e-mail com HTML e anexos."""
    try:
        yag = yagmail.SMTP({st.secrets["gmail"]["username"]: st.secrets["gmail"]["sender_name"]},
                           st.secrets["gmail"]["app_password"])

        yag.send(
            to=recipients,
            subject=subject,
            contents=html_body,
            attachments=attachments
        )
        return True
    except Exception as e:
        st.error(f"Falha ao enviar e-mail: {e}")
        st.info("""
        Verifique as configurações de e-mail no seu `secrets.toml`:
        1. `username` deve ser seu endereço de e-mail completo (ex: `seu.email@gmail.com`).
        2. `app_password` deve ser uma **Senha de Aplicativo (App Password)**, não sua senha normal do Gmail.
           Para gerar uma senha de aplicativo: Vá em Configurações da Conta Google -> Segurança -> Verificação em duas etapas (deve estar ativada) -> Senhas de app.
        """)
        return False

# ✅ FUNÇÃO AUXILIAR DE GERAÇÃO DE PDF
def generate_pdf(data, efetivo_lista, buffer, image_paths, drive_service, drive_folder_id):
    """
    Gera o relatório diário de obra em PDF.
    data: dicionário com os dados gerais do relatório.
    efetivo_lista: lista de dicionários com os dados dos colaboradores.
    buffer: BytesIO object para escrever o PDF.
    image_paths: lista de caminhos para as imagens a serem incluídas.
    drive_service: serviço autenticado do Google Drive (não diretamente usado aqui, mas passado para consistência).
    drive_folder_id: ID da pasta raiz no Drive (não diretamente usado aqui, mas passado para consistência).
    """
    c = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4

    # Estilos de parágrafo
    styles = getSampleStyleSheet()
    normal_style = styles['Normal']
    normal_style.fontSize = 10
    normal_style.leading = 12

    heading_style = ParagraphStyle(
        'HeadingStyle',
        parent=styles['h2'],
        fontSize=14,
        alignment=1, # Centro
        spaceAfter=10,
        textColor=HexColor('#004A7F') # Azul RDV
    )

    subheading_style = ParagraphStyle(
        'SubHeadingStyle',
        parent=styles['h3'],
        fontSize=12,
        spaceAfter=5,
        textColor=HexColor('#004A7F')
    )

    # Coordenadas iniciais
    y_pos = height - 50
    margin = 50

    # Cabeçalho da página
    def draw_header(canvas_obj, y_start):
        logo_path = LOGO_PDF_PATH
        if os.path.exists(logo_path):
            try:
                logo = ImageReader(logo_path)
                logo_width = 80 # Ajuste conforme necessário
                logo_height = 80 * (logo.getSize()[1] / logo.getSize()[0]) # Proporcional
                canvas_obj.drawImage(logo, margin, y_start - logo_height / 2, width=logo_width, height=logo_height, mask='auto')
            except Exception as e:
                st.warning(f"Não foi possível carregar a logo para o PDF: {e}")
        
        canvas_obj.setFont("Helvetica-Bold", 18)
        canvas_obj.setFillColor(HexColor('#004A7F')) # Azul RDV
        canvas_obj.drawString(margin + 90, y_start - 10, "Relatório Diário de Obra")
        canvas_obj.setFont("Helvetica", 10)
        canvas_obj.drawString(margin + 90, y_start - 25, "RDV Engenharia")
        canvas_obj.setStrokeColor(HexColor('#004A7F'))
        canvas_obj.line(margin, y_start - 40, width - margin, y_start - 40) # Linha divisória
        return y_start - 60 # Nova posição Y

    y_pos = draw_header(c, y_pos)

    # Dados Gerais
    c.setFillColor(black)
    p = Paragraph("Dados Gerais da Obra", subheading_style)
    p.wrapOn(c, width - 2 * margin, height)
    p.drawOn(c, margin, y_pos - p.height)
    y_pos -= (p.height + 5)

    data_rows = [
        ["**Obra:**", data.get("Obra", "")],
        ["**Local:**", data.get("Local", "")],
        ["**Data:**", data.get("Data", "")],
        ["**Contrato:**", data.get("Contrato", "")],
        ["**Condições do dia:**", data.get("Clima", "")],
        ["**Máquinas e equipamentos utilizados:**", data.get("Maquinas", "")],
        ["**Serviços executados no dia:**", data.get("Servicos", "")],
    ]
    
    table_style = TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), white),
        ('TEXTCOLOR', (0, 0), (-1, -1), black),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
        ('FONTNAME', (1, 0), (1, -1), 'Helvetica'),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('GRID', (0, 0), (-1, -1), 0.5, lightgrey),
        ('LEFTPADDING', (0,0), (-1,-1), 5),
        ('RIGHTPADDING', (0,0), (-1,-1), 5),
        ('TOPPADDING', (0,0), (-1,-1), 5),
        ('BOTTOMPADDING', (0,0), (-1,-1), 5),
    ])

    # Para lidar com quebras de linha em textos longos
    formatted_data_rows = []
    for row in data_rows:
        key_p = Paragraph(row[0], normal_style)
        value_p = Paragraph(row[1], normal_style)
        formatted_data_rows.append([key_p, value_p])

    col_widths = [width * 0.3, width * 0.7 - 2 * margin]
    data_table = Table(formatted_data_rows, colWidths=col_widths)
    data_table.setStyle(table_style)

    table_height = data_table.wrapOn(c, width - 2 * margin, height)[1]
    if y_pos - table_height < margin:
        c.showPage()
        y_pos = draw_header(c, height - 50)
        p = Paragraph("Dados Gerais da Obra (continuação)", subheading_style)
        p.wrapOn(c, width - 2 * margin, height)
        p.drawOn(c, margin, y_pos - p.height)
        y_pos -= (p.height + 5)

    data_table.drawOn(c, margin, y_pos - table_height)
    y_pos -= (table_height + 15)

    # Efetivo de Pessoal
    p = Paragraph("Efetivo de Pessoal", subheading_style)
    p.wrapOn(c, width - 2 * margin, height)
    p.drawOn(c, margin, y_pos - p.height)
    y_pos -= (p.height + 5)

    if efetivo_lista:
        efetivo_header = ["Nome", "Função", "Entrada", "Saída"]
        efetivo_data = [efetivo_header] + [[e['Nome'], e['Função'], e['Entrada'], e['Saída']] for e in efetivo_lista]
        
        efetivo_table_style = TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), HexColor('#D3D3D3')), # Cinza claro para o cabeçalho
            ('TEXTCOLOR', (0, 0), (-1, 0), black),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 10),
            ('GRID', (0, 0), (-1, -1), 0.5, lightgrey),
            ('LEFTPADDING', (0,0), (-1,-1), 5),
            ('RIGHTPADDING', (0,0), (-1,-1), 5),
            ('TOPPADDING', (0,0), (-1,-1), 5),
            ('BOTTOMPADDING', (0,0), (-1,-1), 5),
        ])

        col_widths_efetivo = [(width - 2 * margin) / 4] * 4
        efetivo_table = Table(efetivo_data, colWidths=col_widths_efetivo)
        efetivo_table.setStyle(efetivo_table_style)

        table_height_efetivo = efetivo_table.wrapOn(c, width - 2 * margin, height)[1]
        if y_pos - table_height_efetivo < margin:
            c.showPage()
            y_pos = draw_header(c, height - 50)
            p = Paragraph("Efetivo de Pessoal (continuação)", subheading_style)
            p.wrapOn(c, width - 2 * margin, height)
            p.drawOn(c, margin, y_pos - p.height)
            y_pos -= (p.height + 5)

        efetivo_table.drawOn(c, margin, y_pos - table_height_efetivo)
        y_pos -= (table_height_efetivo + 15)
    else:
        c.setFont("Helvetica", 10)
        c.drawString(margin, y_pos - 10, "Nenhum colaborador registrado para o dia.")
        y_pos -= 25

    # Informações Adicionais
    p = Paragraph("Informações Adicionais", subheading_style)
    p.wrapOn(c, width - 2 * margin, height)
    p.drawOn(c, margin, y_pos - p.height)
    y_pos -= (p.height + 5)

    info_adic_rows = [
        ["**Ocorrências:**", data.get("Ocorrencias", "")],
        ["**Responsável pela empresa:**", data.get("Nome da Empresa", "")],
        ["**Nome da fiscalização:**", data.get("Nome da Fiscalizacao", "")],
    ]
    
    formatted_info_adic_rows = []
    for row in info_adic_rows:
        key_p = Paragraph(row[0], normal_style)
        value_p = Paragraph(row[1], normal_style)
        formatted_info_adic_rows.append([key_p, value_p])

    info_adic_table = Table(formatted_info_adic_rows, colWidths=col_widths)
    info_adic_table.setStyle(table_style)

    table_height_info_adic = info_adic_table.wrapOn(c, width - 2 * margin, height)[1]
    if y_pos - table_height_info_adic < margin:
        c.showPage()
        y_pos = draw_header(c, height - 50)
        p = Paragraph("Informações Adicionais (continuação)", subheading_style)
        p.wrapOn(c, width - 2 * margin, height)
        p.drawOn(c, margin, y_pos - p.height)
        y_pos -= (p.height + 5)

    info_adic_table.drawOn(c, margin, y_pos - table_height_info_adic)
    y_pos -= (table_height_info_adic + 15)

    # Inclusão de fotos (se houver)
    if image_paths:
        c.showPage()
        y_pos = draw_header(c, height - 50) # Redesenha cabeçalho
        p = Paragraph("Fotos do Serviço", heading_style)
        p.wrapOn(c, width - 2 * margin, height)
        p.drawOn(c, margin, y_pos - p.height)
        y_pos -= (p.height + 10)

        img_width = (width - 3 * margin) / 2 # Largura para 2 imagens por linha
        img_height = 150 # Altura fixa para uniformidade
        current_x = margin
        row_count = 0

        for img_path in image_paths:
            if not os.path.exists(img_path):
                st.warning(f"Arquivo de imagem não encontrado: {img_path}. Será pulado no PDF.")
                continue

            try:
                img = ImageReader(img_path)
                aspect_ratio = img.getSize()[1] / img.getSize()[0]
                scaled_height = img_width * aspect_ratio
                
                # Se a imagem for muito alta, ajusta para a altura máxima e recalcula a largura
                if scaled_height > img_height:
                    scaled_width = img_height / aspect_ratio
                    scaled_height = img_height
                else:
                    scaled_width = img_width

                # Verifica se há espaço para a imagem
                if y_pos - scaled_height - 20 < margin: # 20 de padding
                    c.showPage()
                    y_pos = draw_header(c, height - 50)
                    p = Paragraph("Fotos do Serviço (continuação)", heading_style)
                    p.wrapOn(c, width - 2 * margin, height)
                    p.drawOn(c, margin, y_pos - p.height)
                    y_pos -= (p.height + 10)
                    current_x = margin # Reseta X para nova página
                    row_count = 0

                c.drawImage(img, current_x, y_pos - scaled_height - 10, width=scaled_width, height=scaled_height, preserveAspectRatio=True, mask='auto')
                
                current_x += img_width + margin # Move para a próxima coluna
                row_count += 1

                if row_count % 2 == 0: # 2 imagens por linha
                    current_x = margin
                    y_pos -= (scaled_height + 20) # Move para a próxima linha
                    row_count = 0 # Reinicia contagem de colunas

            except Exception as e:
                st.warning(f"Erro ao incluir foto {img_path} no PDF: {e}")
        
        # Ajusta y_pos se a última linha não foi completa
        if row_count % 2 != 0:
            y_pos -= (scaled_height + 20)

    # Finaliza PDF
    c.save()
    buffer.seek(0)
    return buffer

# ✅ FUNÇÕES DE RENDERIZAÇÃO DE PÁGINAS

def render_login_page():
    """Renderiza a página de login e criação de conta."""
    create_usertable() # Garante que a tabela de usuários existe
    st.title("Login RDV Engenharia")

    login_logo_b64 = get_img_as_base64(LOGO_LOGIN_PATH)
    if login_logo_b64:
        st.markdown(f"""
        <style>
        .login-logo {{
            text-align: center;
            margin-bottom: 20px;
        }}
        .login-logo img {{
            max-width: 250px; /* Ajuste o tamanho da logo */
            height: auto;
        }}
        </style>
        <div class="login-logo">
            <img src="data:image/png;base64,{login_logo_b64}">
        </div>
        """, unsafe_allow_html=True)
    else:
        st.header("Login") # Fallback se a logo não carregar

    username = st.text_input("Usuário", key="login_username")
    password = st.text_input("Senha", type='password', key="login_password")

    col1, col2 = st.columns(2)

    with col1:
        if st.button("Login", key="login_button"):
            user_info = login_user(username, password)
            if user_info:
                st.session_state.logged_in = True
                st.session_state.username = user_info["username"]
                st.session_state.role = user_info["role"]
                st.success(f"Bem-vindo(a), {st.session_state.username}! Você logou como {st.session_state.role}.")
                st.rerun() # Recarrega a página para exibir a interface logada
            else:
                st.error("Usuário ou senha inválidos.")
    with col2:
        if st.button("Criar Conta", key="show_create_account_button"):
            st.session_state.show_create_account = True
            st.rerun() # Recarrega para exibir o formulário de criação

    # Formulário de criação de nova conta
    if st.session_state.get('show_create_account', False):
        st.subheader("Criar Nova Conta")
        with st.form("create_new_user_form", clear_on_submit=True):
            new_username = st.text_input("Novo Usuário", key="new_username_input")
            new_password = st.text_input("Nova Senha", type="password", key="new_password_input")
            new_role = st.selectbox("Função", ["user", "admin"], key="new_role_select") # Permitir criar admin, mas com cuidado.
            create_account_submitted = st.form_submit_button("Registrar", key="register_new_user_button")

            if create_account_submitted:
                if new_username and new_password:
                    hashed_new_password = make_hashes(new_password)
                    if add_userdata(new_username, hashed_new_password, new_role):
                        st.success(f"Conta '{new_username}' criada com sucesso como '{new_role}'.")
                        st.session_state.show_create_account = False # Esconde após criar
                        st.rerun() # Recarrega para voltar à tela de login
                    else:
                        st.error(f"Não foi possível criar a conta. O usuário '{new_username}' já existe.")
                else:
                    st.error("Por favor, preencha todos os campos para criar uma nova conta.")

def render_diario_obra_page():
    """Renderiza a página principal do Relatório Diário de Obra."""
    # Inicialização do estado para o slider de colaboradores
    # Usaremos 'num_colabs_slider' para controlar a quantidade de campos dinâmicos
    if 'num_colabs_slider' not in st.session_state:
        st.session_state.num_colabs_slider = 0 # Inicia com 0 para não exibir campos antes de interagir

    st.title("Relatório Diário de Obra - RDV Engenharia")

    # --- Carregamento de dados do Google Drive ---
    # As funções get_drive_service e load_data_from_drive são cacheadas
    # para evitar múltiplos acessos desnecessários ao Drive.
    
    obras_df = load_data_from_drive(DRIVE_FOLDER_ID, "obras.csv")
    contratos_df = load_data_from_drive(DRIVE_FOLDER_ID, "contratos.csv")
    colab_df = load_data_from_drive(DRIVE_FOLDER_ID, "colaboradores.csv")

    # Garante que os DataFrames não estão vazios antes de tentar acessá-los e usa as colunas corretas
    obras_lista = [""]
    if not obras_df.empty and 'Obra' in obras_df.columns:
        obras_lista = [""] + obras_df["Obra"].drop_duplicates().sort_values().tolist()
    else:
        st.warning("Não foi possível carregar ou formatar 'obras.csv' do Google Drive. Verifique a pasta e o arquivo. Usando lista vazia de obras.")
    
    contratos_lista = [""]
    if not contratos_df.empty and 'Contrato' in contratos_df.columns:
        contratos_lista = [""] + contratos_df["Contrato"].drop_duplicates().sort_values().tolist()
    else:
        st.warning("Não foi possível carregar ou formatar 'contratos.csv' do Google Drive. Verifique a pasta e o arquivo. Usando lista vazia de contratos.")

    colaboradores_lista = []
    if not colab_df.empty and {"Nome", "Função"}.issubset(colab_df.columns):
        colaboradores_lista = colab_df["Nome"].drop_duplicates().sort_values().tolist()
    else:
        st.warning("Não foi possível carregar ou formatar 'colaboradores.csv' do Google Drive. Certifique-se de que ele tem as colunas 'Nome' e 'Função'. Usando lista vazia de colaboradores.")
    # --- Fim do carregamento de dados ---

    # ✅ Seção 1: Dados Gerais da Obra (FORA DO FORMULÁRIO PRINCIPAL)
    # Estes campos são renderizados independentemente do botão de submit do formulário final,
    # permitindo interação imediata (ex: seleção de obra pode carregar outros dados).
    st.subheader("Dados Gerais da Obra")
    obra = st.selectbox("Obra", obras_lista, key="obra_select_top")
    local = st.text_input("Local", key="local_input_top")
    data = st.date_input("Data", value=datetime.today(), key="data_input_top")
    contrato = st.selectbox("Contrato", contratos_lista, key="contrato_select_top")
    clima = st.selectbox("Condições do dia",
                         ["Bom", "Chuva", "Garoa", "Impraticável", "Feriado", "Guarda"],
                         key="clima_select_top")
    maquinas = st.text_area("Máquinas e equipamentos utilizados", key="maquinas_text_top")
    servicos = st.text_area("Serviços executados no dia", key="servicos_text_top")

    st.markdown("---") # Linha separadora visual

    # ✅ Seção 2: Efetivo de Pessoal (SLIDER E CAMPOS MOVIDOS PARA FORA DO FORMULÁRIO PRINCIPAL)
    # Este slider controla dinamicamente a quantidade de campos de colaborador.
    # Por estar fora do `st.form`, sua interação causa uma re-execução imediata do script,
    # atualizando os campos em tempo real.
    st.subheader("Efetivo de Pessoal")
    max_colabs_for_slider = len(colaboradores_lista) if colaboradores_lista else 20

    qtd_colaboradores_input = st.slider(
        "Quantos colaboradores hoje?",
        min_value=0,
        max_value=max_colabs_for_slider,
        value=st.session_state.num_colabs_slider, # O valor inicial vem do session_state
        step=1,
        key="slider_colabs_dynamic", # Chave única para este slider
        # on_change é importante para atualizar o session_state imediatamente ao mover o slider
        on_change=lambda: st.session_state.update(num_colabs_slider=st.session_state.slider_colabs_dynamic)
    )

    efetivo_lista = []
    # O loop `for` abaixo é renderizado com base no valor ATUAL de `qtd_colaboradores_input`,
    # que é atualizado a cada interação com o slider.
    for i in range(qtd_colaboradores_input):
        with st.expander(f"Colaborador {i+1}", expanded=True):
            nome = st.selectbox("Nome", [""] + colaboradores_lista, key=f"colab_nome_dynamic_{i}")
            funcao = ""
            # Preenche a função automaticamente se o nome for selecionado e existir no DataFrame
            if nome and not colab_df.empty and nome in colab_df["Nome"].values:
                funcao = colab_df.loc[colab_df["Nome"] == nome, "Função"].values[0]
            
            funcao = st.text_input("Função", value=funcao, key=f"colab_funcao_dynamic_{i}")
            
            col1, col2 = st.columns(2)
            with col1:
                entrada = st.time_input("Entrada",
                                        value=datetime.strptime("08:00", "%H:%M").time(),
                                        key=f"colab_entrada_dynamic_{i}")
            with col2:
                saida = st.time_input("Saída",
                                       value=datetime.strptime("17:00", "%H:%M").time(),
                                       key=f"colab_saida_dynamic_{i}")
            
            efetivo_lista.append({
                "Nome": nome,
                "Função": funcao,
                "Entrada": entrada.strftime("%H:%M"),
                "Saída": saida.strftime("%H:%M")
            })

    st.markdown("---") # Linha separadora visual

    # ✅ FORMULÁRIO PRINCIPAL DE SUBMISSÃO (AGORA APENAS INFORMAÇÕES ADICIONAIS E BOTÃO)
    # Este formulário agrupa as informações adicionais e o botão de submit.
    # Os valores dos campos FORA deste form (`obra`, `local`, `maquinas`, etc.)
    # serão acessados diretamente no bloco `if submitted:`.
    with st.form(key="relatorio_final_submit_form", clear_on_submit=False):
        # Seção 3: Informações Adicionais (Pode continuar dentro do form)
        st.subheader("Informações Adicionais")
        ocorrencias = st.text_area("Ocorrências", key="ocorrencias_text_form")
        nome_empresa = st.text_input("Responsável pela empresa", key="responsavel_input_form")
        nome_fiscal = st.text_input("Nome da fiscalização", key="fiscalizacao_input_form")
        
        fotos = st.file_uploader("Fotos do serviço",
                                accept_multiple_files=True,
                                type=["png", "jpg", "jpeg"],
                                key="fotos_uploader_form")

        # Botão de submit (DENTRO do form)
        submitted = st.form_submit_button("✅ Salvar e Gerar Relatório", key="submit_button_main")

    # Lógica de processamento após submissão (CORRETAMENTE FORA do form)
    if submitted:
        temp_image_paths = []
        temp_dir_obj_for_cleanup = None # Garante que a variável é inicializada

        try:
            # Validações dos campos que estavam fora do form mas são cruciais para o relatório
            if not obra or obra == "":
                st.error("Por favor, selecione a 'Obra'.")
                return # Retorna para não continuar a execução em caso de erro
            if not contrato or contrato == "":
                st.error("Por favor, selecione o 'Contrato'.")
                return
            if not nome_empresa:
                st.error("Por favor, preencha o campo 'Responsável pela empresa'.")
                return
            
            # Coleta de dados do formulário (incluindo os que foram definidos fora do form principal)
            report_data = {
                "Obra": obra,
                "Local": local,
                "Data": data.strftime("%d/%m/%Y"), # Converte a data para string formatada
                "Contrato": contrato,
                "Clima": clima,
                "Maquinas": maquinas,
                "Servicos": servicos,
                "Ocorrencias": ocorrencias,
                "Nome da Empresa": nome_empresa,
                "Nome da Fiscalizacao": nome_fiscal,
            }

            # Processa e salva fotos temporariamente
            if fotos:
                # Cria um diretório temporário para salvar as fotos
                temp_dir_obj = tempfile.TemporaryDirectory()
                temp_dir_path = Path(temp_dir_obj.name)
                temp_dir_obj_for_cleanup = temp_dir_obj # Guarda para limpeza posterior

                with st.spinner("Processando fotos..."):
                    for uploaded_file in fotos:
                        # Sanitiza o nome do arquivo para evitar problemas de caminho
                        sanitized_name = "".join(c for c in uploaded_file.name if c.isalnum() or c in ('.', '_', '-')).strip()
                        if not sanitized_name:
                            # Fallback para nome único se o nome sanitizado for vazio
                            sanitized_name = f"foto_temp_{datetime.now().strftime('%Y%m%d%H%M%S%f')}.jpg"
                        
                        temp_img_path = temp_dir_path / sanitized_name
                        try:
                            with open(temp_img_path, "wb") as f:
                                f.write(uploaded_file.read())
                            temp_image_paths.append(str(temp_img_path))
                        except Exception as e:
                            st.warning(f"Não foi possível salvar a foto '{uploaded_file.name}' temporariamente: {e}")
                    
                    if not temp_image_paths and fotos:
                        st.warning("⚠️ Nenhuma foto foi processada. O PDF pode não conter imagens.")
            
            # Geração do PDF
            pdf_file_name = f"RDV_{obra.replace(' ', '_')}_{data.strftime('%Y%m%d')}.pdf"
            pdf_buffer = io.BytesIO() # Buffer para o PDF

            with st.spinner("Gerando PDF..."):
                generate_pdf(report_data, efetivo_lista, pdf_buffer, temp_image_paths, get_drive_service(), DRIVE_FOLDER_ID)
                
                if pdf_buffer is None or pdf_buffer.getvalue() == b'':
                    st.error("Falha crítica ao gerar o PDF. O buffer está vazio. Por favor, tente novamente ou verifique os logs para detalhes.")
                    return
                
                # Botão de download do PDF
                st.download_button(
                    label="📥 Baixar Relatório PDF",
                    data=pdf_buffer.getvalue(), # Conteúdo do buffer para download
                    file_name=pdf_file_name,
                    mime="application/pdf",
                    type="primary"
                )

            # Upload do PDF para o Google Drive
            drive_id = None
            with st.spinner("Enviando relatório para o Google Drive..."):
                pdf_buffer.seek(0) # Volta o ponteiro do buffer para o início para leitura
                service = get_drive_service()
                
                # Cria uma subpasta diária no Drive para organizar os PDFs
                today_folder_name = datetime.now().strftime("%Y-%m-%d")
                daily_folder_id = create_drive_folder_if_not_exists(service, DRIVE_FOLDER_ID, today_folder_name)
                
                if daily_folder_id:
                    drive_id = upload_file_to_drive(service, daily_folder_id, pdf_file_name, pdf_buffer.getvalue(), "application/pdf")

                    if drive_id:
                        st.success(f"PDF salvo com sucesso no Google Drive! ID: {drive_id}")
                        st.markdown(f"**[Clique aqui para abrir no Google Drive](https://drive.google.com/file/d/{drive_id}/view)**")

                        # Enviar e-mail de notificação
                        with st.spinner("Enviando e-mail de notificação..."):
                            assunto_email = f"📋 Novo Diário de Obra - {obra} ({data.strftime('%d/%m/%Y')})"
                            corpo_email_html = f"""
                            <p>Olá, equipe RDV!</p>
                            <p>O diário de obra foi preenchido com sucesso:</p>
                            <ul>
                                <li><strong>Obra:</strong> {obra}</li>
                                <li><strong>Local:</strong> {local}</li>
                                <li><strong>Data:</strong> {data.strftime('%d/%m/%Y')}</li>
                                <li><strong>Responsável:</strong> {nome_empresa}</li>
                            </ul>
                            <p>Você pode acessar o relatório diretamente no Google Drive através deste link: <a href="https://drive.google.com/file/d/{drive_id}/view">Abrir no Google Drive</a></p>
                            <p>Atenciosamente,</p>
                            <p>Equipe RDV Engenharia</p>
                            """
                            destinatarios_email = [
                                "comercial@rdvengenharia.com.br", # Adicione os emails de destino
                                "administrativo@rdvengenharia.com.br"
                            ]
                            
                            if send_email(assunto_email, corpo_email_html, destinatarios_email, attachments=None):
                                st.success("📨 E-mail de notificação enviado com sucesso!")
                            else:
                                st.warning("""
                                ⚠️ O PDF foi salvo no Google Drive, mas o e-mail de notificação não foi enviado.
                                Por favor, verifique os detalhes do erro acima ou nos logs para depuração.
                                **Possíveis soluções:**
                                1. Verifique sua conexão com a internet.
                                2. Confira as configurações de e-mail (usuário e senha) no seu arquivo `.streamlit/secrets.toml`.
                                3. Certifique-se de estar usando uma **Senha de Aplicativo (App Password)** do Gmail para a senha, se a Verificação em Duas Etapas estiver ativada na sua conta de e-mail.
                                """)
                    else:
                        st.error("O upload do PDF para o Google Drive falhou. O e-mail de notificação não foi enviado.")
                else:
                    st.error("Não foi possível criar/encontrar a pasta diária no Google Drive. O upload do PDF falhou.")

        except Exception as e:
            st.error(f"Ocorreu um erro inesperado durante o processamento do relatório: {str(e)}. Por favor, tente novamente.")
        finally:
            # Limpeza de arquivos temporários de fotos
            if temp_dir_obj_for_cleanup:
                try:
                    temp_dir_obj_for_cleanup.cleanup() # Limpa o diretório temporário das fotos
                except Exception as e:
                    st.warning(f"Erro ao tentar limpar diretório temporário de fotos: {str(e)}. Por favor, verifique os logs.")

def render_user_management_page():
    """Renderiza a página de gerenciamento de usuários (apenas para administradores)."""
    st.title("Gerenciamento de Usuários")

    if st.session_state.role != "admin":
        st.warning("Você não tem permissão para acessar esta página.")
        return

    st.subheader("Adicionar Novo Usuário")
    with st.form("add_user_form", clear_on_submit=True):
        new_username = st.text_input("Nome de Usuário", key="add_user_username")
        new_password = st.text_input("Senha", type="password", key="add_user_password")
        new_role = st.selectbox("Função", ["user", "admin"], key="add_user_role")
        add_user_submitted = st.form_submit_button("Adicionar Usuário", key="add_user_submit_button")

        if add_user_submitted:
            if new_username and new_password:
                hashed_new_password = make_hashes(new_password)
                if add_userdata(new_username, hashed_new_password, new_role):
                    st.success(f"Usuário '{new_username}' adicionado com sucesso como '{new_role}'.")
                else:
                    st.error(f"Não foi possível adicionar o usuário '{new_username}'. Ele já existe ou ocorreu um erro.")
            else:
                st.error("Preencha todos os campos para adicionar um novo usuário.")

    st.subheader("Usuários Existentes")
    user_data = view_all_users()
    df_users = pd.DataFrame(user_data, columns=['Username', 'Role']) # Não exibir senhas
    st.dataframe(df_users)


# ✅ LÓGICA PRINCIPAL DO APP

if __name__ == "__main__":
    # Inicialização do estado da sessão do Streamlit
    if 'logged_in' not in st.session_state:
        st.session_state.logged_in = False
    if 'username' not in st.session_state:
        st.session_state.username = None
    if 'role' not in st.session_state:
        st.session_state.role = None
    if 'page' not in st.session_state:
        st.session_state.page = "login" # Página inicial é o login
    if 'show_create_account' not in st.session_state:
        st.session_state.show_create_account = False # Estado para controlar o formulário de criação de conta

    # Limpa o arquivo temporário do ícone (se houver) ao iniciar/encerrar a sessão
    clear_icon_temp_file()

    # Cria a tabela de usuários se não existir
    create_usertable()
    
    # Bloco para criar o primeiro admin, se necessário.
    # DEVE SER REMOVIDO OU DESABILITADO APÓS A CRIAÇÃO DO PRIMEIRO ADMIN NO DEPLOY FINAL POR SEGURANÇA.
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('SELECT COUNT(*) FROM userstable WHERE role = "admin"')
    admin_count = c.fetchone()[0]
    conn.close() # Feche a conexão imediatamente após a consulta

    if admin_count == 0 and not st.session_state.logged_in: # Só mostra se não há admins e não está logado
        st.info("Parece que não há administradores registrados. Por favor, crie o primeiro admin para continuar.")
        with st.form("create_first_admin_form", clear_on_submit=True):
            first_admin_username = st.text_input("Usuário do Primeiro Admin", value="admin_rdv", key="first_admin_user_input")
            first_admin_password = st.text_input("Senha do Primeiro Admin", type="password", value="admin_rdv_senha", key="first_admin_pass_input")
            create_admin_button = st.form_submit_button("Criar Primeiro Admin", key="create_first_admin_button_submit")

            if create_admin_button:
                if first_admin_username and first_admin_password:
                    hashed_password = make_hashes(first_admin_password)
                    if add_userdata(first_admin_username, hashed_password, "admin"):
                        st.success(f"Usuário '{first_admin_username}' criado com sucesso como 'admin'. Por favor, use-o para logar.")
                        st.warning("🚨 **ATENÇÃO:** Altere a senha padrão IMEDIATAMENTE após o primeiro login. Remova ou desabilite este bloco no seu deploy final para maior segurança!")
                        st.session_state.show_create_account = False # Resetar se for para login
                        st.rerun() # Força a re-execução para ir para a tela de login
                    else:
                        st.error("Não foi possível criar o usuário admin. Talvez já exista um usuário com esse nome. Tente fazer login.")
                else:
                    st.error("Preencha o nome de usuário e a senha para o primeiro admin.")
        # Se estamos neste bloco (admin_count == 0 e não logado), não renderize mais nada por enquanto
        st.stop() # Interrompe a execução para não continuar para o login/páginas
    
    # Se já há admins ou o admin acabou de ser criado, prosseguir para o login ou para a página logada
    if not st.session_state.logged_in:
        render_login_page()
    else:
        # Seções da barra lateral
        st.sidebar.title(f"Bem-vindo(a), {st.session_state.username}!")
        st.sidebar.write(f"Função: **{st.session_state.role.upper()}**")

        page_options = ["Diário de Obra"]
        if st.session_state.role == "admin":
            page_options.append("Gerenciamento de Usuários")
        page_options.append("Sair")
        
        selected_page = st.sidebar.radio("Navegação", page_options, key="main_navigation")

        # Lógica de navegação
        if selected_page == "Diário de Obra":
            render_diario_obra_page()
        elif selected_page == "Gerenciamento de Usuários":
            if st.session_state.role == "admin": # Verificação extra de segurança
                render_user_management_page()
            else:
                st.error("Acesso negado: Você não tem permissão para gerenciar usuários.")
                # Redireciona para a página padrão se tentar acessar sem permissão
                st.session_state.page = "Diário de Obra" 
                st.rerun()
        elif selected_page == "Sair":
            st.session_state.logged_in = False
            st.session_state.username = None
            st.session_state.role = None
            st.session_state.page = "login" # Redireciona para a página de login
            st.success("Deslogado com sucesso.")
            st.rerun() # Força a re-execução para limpar a interface e mostrar o login
