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
from reportlab.lib.styles import getSampleStyleSheet
import os
import io
import json
import yagmail
import tempfile
import shutil

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
from googleapiclient.errors import HttpError

import sqlite3
import hashlib
import base64

# ========== CONSTANTES ==========
DRIVE_FOLDER_ID = "1BUgZRcBrKksC3eUytoJ5mv_nhMRdAv1d"
LOGO_LOGIN_PATH = "LOGO RDV AZUL.jpeg"
LOGO_PDF_PATH = "LOGO_RDV_AZUL-sem fundo.png"
LOGO_ICON_PATH = "LOGO_RDV_AZUL-sem fundo.png"

def get_img_as_base64(file_path):
    if not os.path.exists(file_path):
        return ""
    try:
        with open(file_path, "rb") as f:
            img_bytes = f.read()
        return base64.b64encode(img_bytes).decode()
    except Exception:
        return ""

def load_page_icon():
    if LOGO_ICON_PATH and os.path.exists(LOGO_ICON_PATH):
        try:
            img = PILImage.open(LOGO_ICON_PATH)
            img.thumbnail((32, 32), PILImage.Resampling.LANCZOS)
            temp_icon_file = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
            img.save(temp_icon_file.name, format="PNG")
            temp_icon_file.close()
            return temp_icon_file.name
        except Exception:
            return None
    else:
        if os.path.exists(LOGO_PDF_PATH):
            try:
                img = PILImage.open(LOGO_PDF_PATH)
                img.thumbnail((32, 32), PILImage.Resampling.LANCZOS)
                temp_icon_file = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
                img.save(temp_icon_file.name, format="PNG")
                temp_icon_file.close()
                return temp_icon_file.name
            except Exception:
                return None
        return None

# --- CONFIGURAÇÃO DA PÁGINA STREAMLIT ---
temp_icon_path_for_cleanup = None
try:
    page_icon_to_use = load_page_icon()
    if page_icon_to_use:
        temp_icon_path_for_cleanup = page_icon_to_use
        st.set_page_config(
            page_title="Diário de Obra - RDV",
            layout="centered",
            page_icon=page_icon_to_use
        )
    else:
        st.set_page_config(
            page_title="Diário de Obra - RDV",
            layout="centered"
        )
except Exception:
    st.set_page_config(
        page_title="Diário de Obra - RDV",
        layout="centered"
    )

# --- CREDENCIAIS GOOGLE DRIVE ---
try:
    creds_dict = dict(st.secrets["google_service_account"])
    creds = service_account.Credentials.from_service_account_info(
        creds_dict, scopes=["https://www.googleapis.com/auth/drive"]
    )
except Exception:
    st.error("Erro nas credenciais do Google Drive.")
    st.stop()

# --- FUNÇÕES AUTENTICAÇÃO (SQLite) ---
conn = sqlite3.connect('users.db')
c = conn.cursor()

def make_hashes(password):
    return hashlib.sha256(str.encode(password)).hexdigest()

def create_usertable():
    c.execute('CREATE TABLE IF NOT EXISTS userstable(username TEXT,password TEXT,role TEXT)')
    conn.commit()

def add_userdata(username, password, role):
    c.execute('INSERT INTO userstable(username,password,role) VALUES (?,?,?)',(username,password,role))
    conn.commit()

def login_user(username, password):
    c.execute('SELECT * FROM userstable WHERE username =? AND password = ?', (username,password))
    data = c.fetchall()
    if data:
        return True, data[0][2]
    return False, None

def view_all_users():
    c.execute('SELECT * FROM userstable')
    data = c.fetchall()
    return data

def init_db():
    create_usertable()
    if not view_all_users():
        add_userdata("admin", make_hashes("admin123"), "admin")
        st.success("Usuário 'admin' criado com senha 'admin123'. Por favor, altere sua senha após o primeiro login.")

# --- PDF E FOTOS ---
def draw_text_area_with_wrap(canvas_obj, text, x, y_start, max_width, line_height=14, font_size=10):
    styles = getSampleStyleSheet()
    style = styles['Normal']
    style.fontSize = font_size
    style.leading = line_height
    style.fontName = "Helvetica"
    text = text.replace('\n', '<br/>')
    p = Paragraph(text, style)
    text_width, text_height = p.wrapOn(canvas_obj, max_width, A4[1]) 
    actual_y_start = y_start - text_height
    p.drawOn(canvas_obj, x, actual_y_start)
    return actual_y_start - line_height

def draw_header(c, width, height, logo_path):
    c.setFillColor(HexColor("#0F2A4D"))
    c.rect(0, height-80, width, 80, fill=True, stroke=False)
    c.setFillColor(white)
    c.setFont("Helvetica-Bold", 18)
    c.drawCentredString(width/2, height-50, "DIÁRIO DE OBRA")
    c.setFont("Helvetica", 12)
    c.drawCentredString(width/2, height-70, "RDV ENGENHARIA")
    if os.path.exists(logo_path):
        try:
            logo = ImageReader(logo_path)
            c.drawImage(logo, 30, height-70, width=100, height=50, preserveAspectRatio=True) 
        except Exception:
            pass

def draw_info_table(c, registro, width, height, y_start, margem):
    data = [
        ["OBRA:", registro.get("Obra", "N/A")],
        ["LOCAL:", registro.get("Local", "N/A")],
        ["DATA:", registro.get("Data", "N/A")],
        ["CONTRATO:", registro.get("Contrato", "N/A")]
    ]
    col2_width = width - 100 - (2 * margem)
    table = Table(data, colWidths=[100, col2_width]) 
    table.setStyle(TableStyle([
        ('FONTNAME', (0,0), (-1,-1), 'Helvetica-Bold'),
        ('FONTSIZE', (0,0), (-1,-1), 10),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('BOTTOMPADDING', (0,0), (-1,-1), 6)
    ]))
    table_width, table_height = table.wrapOn(c, width - 2*margem, height)
    table.drawOn(c, margem, y_start - table_height)
    return y_start - table_height - 10

def draw_efetivo_table(c, efetivo_data_json, width, height, y_start, margem):
    try:
        efetivo_data = json.loads(efetivo_data_json)
    except json.JSONDecodeError:
        efetivo_data = [] 
    data = [["NOME", "FUNÇÃO", "1ª ENTRADA", "1ª SAÍDA"]]
    for item in efetivo_data:
        data.append([item.get("Nome", ""), item.get("Função", ""), item.get("Entrada", ""), item.get("Saída", "")])
    min_rows_display = 6
    while len(data) < min_rows_display + 1:
        data.append(["", "", "", ""])
    table = Table(data, colWidths=[120, 100, 80, 80])
    table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), HexColor("#0F2A4D")),
        ('TEXTCOLOR', (0,0), (-1,0), white),
        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
        ('FONTSIZE', (0,0), (-1,-1), 8),
        ('ALIGN', (0,0), (-1,-1), 'CENTER'),
        ('GRID', (0,0), (-1,-1), 0.5, lightgrey),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
    ]))
    table_width, table_height = table.wrapOn(c, width - 2*margem, height)
    table.drawOn(c, margem, y_start - table_height)
    return y_start - table_height - 10

def draw_footer(c, width, margem, current_y, registro):
    footer_height = 80 
    if current_y < (margem + footer_height + 20): 
        c.showPage()
        current_y = A4[1] - margem
    c.setFont("Helvetica", 9)
    c.setFillColor(darkgrey)
    c.rect(margem, margem, width - 2*margem, 70) 
    y_assinatura_line = margem + 45
    y_assinatura_title = margem + 30
    y_assinatura_name = margem + 15
    c.line(margem + 50, y_assinatura_line, margem + 200, y_assinatura_line)
    c.drawCentredString(margem + 125, y_assinatura_title, "Responsável Técnico")
    c.drawCentredString(margem + 125, y_assinatura_name, f"Nome: {registro.get('Responsável Empresa', 'Eng. Responsável')}")
    c.line(width - margem - 200, y_assinatura_line, width - margem - 50, y_assinatura_line)
    c.drawCentredString(width - margem - 125, y_assinatura_title, "Fiscalização")
    c.drawCentredString(width - margem - 125, y_assinatura_name, f"Nome: {registro.get('Fiscalização', 'Conforme assinatura')}")
    c.setFillColor(black)
    c.setFont("Helvetica", 8)
    c.drawString(margem + 5, margem + 5, f"Gerado em: {datetime.now().strftime('%d/%m/%Y %H:%M')}")
    return margem

def gerar_pdf(registro, fotos_paths):
    import io
    from reportlab.platypus import Table, TableStyle, Paragraph
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.enums import TA_LEFT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.colors import HexColor, black, lightgrey, white, darkgrey
    from reportlab.pdfgen import canvas
    from reportlab.lib.utils import ImageReader
    from PIL import Image as PILImage
    from pathlib import Path
    from datetime import datetime

    buffer = io.BytesIO()
    try:
        c = canvas.Canvas(buffer, pagesize=A4)
        width, height = A4
        margem = 30

        # --- Cabeçalho (personalize conforme desejar) ---
        draw_header(c, width, height, LOGO_PDF_PATH)
        y = height - 100

        # --- Tabela de informações gerais da obra ---
        y = draw_info_table(c, registro, width, height, y, margem)

        # --- Bloco Clima / Condições do Dia ---
        box_clima_h = 25
        c.rect(margem, y - box_clima_h, width - 2*margem, box_clima_h)
        c.setFont("Helvetica-Bold", 10)
        c.drawString(margem + 5, y - 15, "Condições do dia:")
        c.setFont("Helvetica", 11)
        c.drawString(margem + 120, y - 15, registro.get('Clima', 'N/A'))
        y -= (box_clima_h + 8)

        # --- Bloco Máquinas e Equipamentos ---
        maquinas_txt = registro.get('Máquinas', '').strip() or 'Nenhuma máquina/equipamento informado.'
        maquinas_lines = maquinas_txt.count('\n') + 1
        box_maquinas_h = max(28, 12 * maquinas_lines + 18)
        c.rect(margem, y - box_maquinas_h, width - 2*margem, box_maquinas_h)
        c.setFont("Helvetica-Bold", 10)
        c.drawString(margem + 5, y - 15, "Máquinas e Equipamentos:")
        c.setFont("Helvetica", 10)
        y_text_maquinas = y - 28
        draw_text_area_with_wrap(c, maquinas_txt, margem + 10, y_text_maquinas, (width - 2*margem) - 20, line_height=12)
        y -= (box_maquinas_h + 8)

        # --- Serviços Executados ---
        servicos_txt = registro.get('Serviços', '').strip() or 'Nenhum serviço executado informado.'
        servicos_lines = servicos_txt.count('\n') + 1
        box_servicos_h = max(32, 12 * servicos_lines + 18)
        c.rect(margem, y - box_servicos_h, width - 2*margem, box_servicos_h)
        c.setFont("Helvetica-Bold", 10)
        c.drawString(margem + 5, y - 15, "Serviços Executados:")
        c.setFont("Helvetica", 10)
        y_text_servicos = y - 28
        draw_text_area_with_wrap(c, servicos_txt, margem + 10, y_text_servicos, (width - 2*margem) - 20, line_height=12)
        y -= (box_servicos_h + 8)

        # --- Efetivo de Pessoal ---
        c.setFont("Helvetica-Bold", 10)
        c.drawString(margem, y - 10, "Efetivo de Pessoal:")
        y -= 18

        # --- Tabela de Efetivo (com quebra de linha no nome) ---
        try:
            efetivo_data = json.loads(registro.get("Efetivo", "[]"))
        except Exception:
            efetivo_data = []

        data = [["NOME", "FUNÇÃO", "1ª ENTRADA", "1ª SAÍDA"]]
        for item in efetivo_data:
            nome_style = ParagraphStyle(
                name='nome_style',
                fontName='Helvetica',
                fontSize=8,
                alignment=TA_LEFT,
                leading=10
            )
            nome_paragraph = Paragraph(item.get("Nome", ""), nome_style)
            funcao_paragraph = Paragraph(item.get("Função", ""), nome_style)
            data.append([
                nome_paragraph,
                funcao_paragraph,
                item.get("Entrada", ""),
                item.get("Saída", "")
            ])
        min_rows_display = 6
        while len(data) < min_rows_display + 1:
            data.append(["", "", "", ""])
        table = Table(data, colWidths=[220, 100, 65, 65])
        table.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,0), HexColor("#0F2A4D")),
            ('TEXTCOLOR', (0,0), (-1,0), white),
            ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
            ('FONTSIZE', (0,0), (-1,0), 9),
            ('FONTSIZE', (0,1), (-1,-1), 8),
            ('ALIGN', (0,0), (-1,0), 'CENTER'),
            ('ALIGN', (2,1), (3,-1), 'CENTER'),
            ('ALIGN', (0,1), (1,-1), 'LEFT'),
            ('GRID', (0,0), (-1,-1), 0.5, lightgrey),
            ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
            ('WORDWRAP', (0,1), (1,-1), 'CJK'),
        ]))
        table_width, table_height = table.wrapOn(c, width - 2*margem, height)
        table.drawOn(c, margem, y - table_height)
        y -= (table_height + 10)

        # --- Ocorrências ---
        ocorrencias_txt = registro.get('Ocorrências', '').strip() or 'Nenhuma ocorrência informada.'
        ocorrencias_lines = ocorrencias_txt.count('\n') + 1
        box_ocorrencias_h = max(25, 12 * ocorrencias_lines + 18)
        c.setFont("Helvetica-Bold", 10)
        c.drawString(margem, y - 10, "Ocorrências:")
        y -= 18
        c.rect(margem, y - box_ocorrencias_h, width - 2*margem, box_ocorrencias_h)
        y_text_ocorrencias = y - 16
        draw_text_area_with_wrap(c, ocorrencias_txt, margem + 10, y_text_ocorrencias, (width - 2*margem) - 20, line_height=12)
        y -= (box_ocorrencias_h + 10)

        # --- Fiscalização ---
        fiscal_txt = registro.get('Fiscalização', '').strip() or 'N/A'
        c.setFont("Helvetica-Bold", 10)
        c.drawString(margem, y - 10, "Fiscalização:")
        y -= 18
        box_fiscalizacao_h = 25
        c.rect(margem, y - box_fiscalizacao_h, width - 2*margem, box_fiscalizacao_h)
        c.setFont("Helvetica", 10)
        c.drawString(margem + 10, y - 16, f"Nome da Fiscalização: {fiscal_txt}")
        y -= (box_fiscalizacao_h + 10)

        # --- Rodapé (assinaturas) já logo após o conteúdo ---
        draw_footer(c, width, margem, y, registro)

        # --- Fotos nas páginas seguintes ---
        for i, foto_path in enumerate(fotos_paths):
            try:
                if not Path(foto_path).exists():
                    continue
                c.showPage()
                y_foto = height - margem
                c.setFont("Helvetica-Bold", 12)
                c.drawString(margem, y_foto, f"📷 Foto {i+1}: {Path(foto_path).name}")
                c.setFont("Helvetica", 10)
                y_foto -= 20
                img = PILImage.open(foto_path)
                img_width, img_height = img.size
                max_img_width = width - 2 * margem
                max_img_height = height - 2 * margem - (height - y_foto)
                aspect_ratio = img_width / img_height
                new_width = img_width
                new_height = img_height
                if img_width > max_img_width or img_height > max_img_height:
                    if (max_img_width / aspect_ratio) <= max_img_height:
                        new_width = max_img_width
                        new_height = max_img_width / aspect_ratio
                    else:
                        new_height = max_img_height
                        new_width = max_img_height * aspect_ratio
                    img = img.resize((int(new_width), int(new_height)), PILImage.Resampling.LANCZOS)
                x_pos_img = margem + (max_img_width - new_width) / 2
                img_y_pos = y_foto - new_height - 10 
                c.drawImage(ImageReader(img), x_pos_img, img_y_pos, width=new_width, height=new_height)
            except Exception:
                continue

        c.save()
        buffer.seek(0)
        return buffer

    except Exception as e:
        print("Erro ao gerar PDF:", e)
        return None
def processar_fotos(fotos_upload, obra_nome, data_relatorio):
    fotos_processadas_paths = []
    temp_dir_path_obj = None
    try:
        temp_dir_path_obj = Path(tempfile.mkdtemp(prefix="diario_obra_"))
        for i, foto_file in enumerate(fotos_upload):
            if foto_file is None:
                continue
            try:
                nome_foto_base = f"{obra_nome.replace(' ', '_')}_{data_relatorio.strftime('%Y-%m-%d')}_foto{i+1}"
                nome_foto_final = f"{nome_foto_base}{Path(foto_file.name).suffix}"
                caminho_foto_temp = temp_dir_path_obj / nome_foto_final
                with open(caminho_foto_temp, "wb") as f:
                    f.write(foto_file.getbuffer())
                if not caminho_foto_temp.exists():
                    raise FileNotFoundError()
                img = PILImage.open(caminho_foto_temp)
                img.thumbnail((1200, 1200), PILImage.Resampling.LANCZOS)
                img.save(caminho_foto_temp, "JPEG", quality=85)
                fotos_processadas_paths.append(str(caminho_foto_temp))
            except Exception:
                continue
        return fotos_processadas_paths
    except Exception:
        if temp_dir_path_obj and temp_dir_path_obj.exists():
            shutil.rmtree(temp_dir_path_obj)
        return []

def upload_para_drive_seguro(pdf_buffer, nome_arquivo):
    try:
        pdf_buffer.seek(0)
        service = build("drive", "v3", credentials=creds, static_discovery=False)
        media = MediaIoBaseUpload(pdf_buffer, mimetype='application/pdf', resumable=True)
        file_metadata = {'name': nome_arquivo, 'parents': [DRIVE_FOLDER_ID]}
        file = service.files().create(
            body=file_metadata,
            media_body=media,
            fields='id',
            supportsAllDrives=True
        ).execute()
        return file.get("id")
    except HttpError as error:
        st.error(f"Erro HTTP ao enviar para o Google Drive: {error}")
        return None
    except Exception:
        return None

def enviar_email(destinatarios, assunto, corpo_html, drive_id=None):
    try:
        yag = yagmail.SMTP(
            user=st.secrets["email"]["user"],
            password=st.secrets["email"]["password"],
            host='smtp.gmail.com',
            port=587,
            smtp_starttls=True,
            smtp_ssl=False,
            timeout=30
        )
        corpo_completo_final = f"""
        <html>
            <body>
                {corpo_html}
                {f'<p><a href="https://drive.google.com/file/d/{drive_id}/view">Acessar o Diário de Obra no Google Drive</a></p>' if drive_id else ''}
                <p style="color: #888; font-size: 0.8em; margin-top: 20px;">
                    Mensagem enviada automaticamente pelo Sistema Diário de Obra - RDV Engenharia
                </p>
            </body>
        </html>
        """
        yag.send(
            to=destinatarios,
            subject=assunto,
            contents=corpo_completo_final,
            headers={'X-Application': 'DiarioObraRDV'}
        )
        return True
    except Exception:
        return False

# ========== LÓGICA PRINCIPAL DO APP ==========

if 'logged_in' not in st.session_state:
    st.session_state.logged_in = False
    st.session_state.username = None
    st.session_state.role = None
if 'num_colabs_slider' not in st.session_state:
    st.session_state.num_colabs_slider = 0 
init_db()

# --- TELA DE LOGIN ---
# --- TELA DE LOGIN, FORA DE QUALQUER FUNÇÃO ---
if not st.session_state.logged_in:
    st.markdown(f"""
    <style>
        .login-container {{
            max-width: 400px;
            margin: 0 auto;
            padding: 2rem;
            box-shadow: 0 4px 8px rgba(0,0,0,0.1);
            border-radius: 10px;
            background: white;
        }}
        .logo {{
            text-align: center;
            margin-bottom: 1.5rem;
        }}
        .stButton>button {{
            width: 100%;
            background: #0F2A4D;
            color: white;
            border: none;
            padding: 10px 20px;
            font-size: 16px;
            border-radius: 5px;
            cursor: pointer;
            transition: background 0.3s ease;
        }}
        .stButton>button:hover {{
            background: #0A1C36;
        }}
        .stTextInput>div>div>input {{
            border-radius: 5px;
            border: 1px solid #ccc;
            padding: 10px;
            width: 100%;
            box-sizing: border-box;
        }}
        .stTextInput label {{
            font-weight: bold;
            color: #0F2A4D;
        }}
    </style>
    <div class="login-container">
        <div class="logo">
            <img src="data:image/jpeg;base64,{get_img_as_base64(LOGO_LOGIN_PATH)}" width="200">
        </div>
        <h3 style="text-align: center; color: #0F2A4D;">Acesso ao Sistema</h3>
    </div>
    """, unsafe_allow_html=True)

    with st.form("login_form"):
        username_input = st.text_input("Usuário", placeholder="Digite seu nome de usuário", key="login_username")
        password_input = st.text_input("Senha", type="password", key="login_password")
        submitted = st.form_submit_button("Entrar")

    if submitted:
        if username_input and password_input:
            hashed_password = make_hashes(password_input)
            authenticated, role = login_user(username_input, hashed_password)
            if authenticated:
                st.session_state["logged_in"] = True
                st.session_state["username"] = username_input
                st.session_state["role"] = role
                st.rerun()
            else:
                st.error("Credenciais inválidas. Verifique seu usuário e senha.")
        else:
            st.warning("Por favor, preencha todos os campos.")
    st.stop()

# --- MENU LATERAL E CONTROLE DE NAVEGAÇÃO ---

if 'page' not in st.session_state:
    st.session_state.page = "Diário de Obra"

st.sidebar.title(f"Bem-vindo, {st.session_state.username}!")

menu_opcoes = ["Diário de Obra", "Holerite (em breve)"]

if st.session_state.role == "admin":
    menu_opcoes.append("Gerenciamento de Usuários")

menu_opcoes.append("Sair")

escolha = st.sidebar.radio("Menu", menu_opcoes, key="menu_lateral")

if escolha == "Sair":
    st.session_state.clear()
    st.experimental_rerun()
elif escolha == "Diário de Obra":
    st.session_state.page = "Diário de Obra"
elif escolha == "Holerite (em breve)":
    st.session_state.page = "Holerite"
elif escolha == "Gerenciamento de Usuários":
    st.session_state.page = "Gerenciamento de Usuários"

if st.session_state.page == "Diário de Obra":
    render_diario_obra_page()
elif st.session_state.page == "Holerite":
    st.title("Holerite")
    st.warning("Funcionalidade em desenvolvimento... Em breve disponível.")
elif st.session_state.page == "Gerenciamento de Usuários":
    render_user_management_page()

    def render_diario_obra_page():
        @st.cache_data(ttl=3600)
        def carregar_arquivo_csv(nome_arquivo):
            if not os.path.exists(nome_arquivo):
                st.error(f"Erro: Arquivo de dados '{nome_arquivo}' não encontrado.")
                return pd.DataFrame()
            try:
                return pd.read_csv(nome_arquivo)
            except Exception as e:
                st.error(f"Erro ao ler o arquivo '{nome_arquivo}': {e}")
                return pd.DataFrame()
        obras_df = carregar_arquivo_csv("obras.csv")
        contratos_df = carregar_arquivo_csv("contratos.csv")
        colab_df = pd.DataFrame()
        colaboradores_lista = []
        try:
            colab_df = pd.read_csv("colaboradores.csv", quotechar='"', skipinitialspace=True)
            if not colab_df.empty and {"Nome", "Função"}.issubset(colab_df.columns):
                colab_df = colab_df.dropna()
                colab_df["Nome"] = colab_df["Nome"].astype(str).str.strip()
                colab_df["Função"] = colab_df["Função"].astype(str).str.strip()
                colab_df["Nome_Normalizado"] = colab_df["Nome"].str.lower().str.strip()
                colaboradores_lista = colab_df["Nome"].tolist()
            else:
                st.error("'colaboradores.csv' deve ter colunas 'Nome' e 'Função'.")
        except Exception as e:
            st.error(f"Erro ao carregar 'colaboradores.csv': {e}")
            colab_df = pd.DataFrame()
        if obras_df.empty or contratos_df.empty:
            st.stop()
        obras_lista = [""] + obras_df["Nome"].tolist()
        contratos_lista = [""] + contratos_df["Nome"].tolist()
        st.title("Relatório Diário de Obra - RDV Engenharia")
        st.subheader("Dados Gerais da Obra")
        obra = st.selectbox("Obra", obras_lista)
        local = st.text_input("Local")
        data = st.date_input("Data", datetime.today())
        contrato = st.selectbox("Contrato", contratos_lista)
        clima = st.selectbox("Condições do dia",
                             ["Bom", "Chuva", "Garoa", "Impraticável", "Feriado", "Guarda"])
        maquinas = st.text_area("Máquinas e equipamentos utilizados")
        servicos = st.text_area("Serviços executados no dia")
        st.markdown("---")
        st.subheader("Efetivo de Pessoal")
        max_colabs = len(colaboradores_lista) if colaboradores_lista else 8
        qtd_colaboradores = st.number_input(
            "Quantos colaboradores hoje?",
            min_value=1,
            max_value=max_colabs,
            value=1,
            step=1
        )
        efetivo_lista = []
        for i in range(int(qtd_colaboradores)):
            with st.container():
                with st.expander(f"Colaborador {i+1}", expanded=True):
                    nome = st.selectbox("Nome", [""] + colaboradores_lista, key=f"colab_nome_reativo_{i}")
                    funcao = ""
                    if nome and not colab_df.empty:
                        nome_normalizado = nome.strip().lower()
                        match = colab_df[colab_df["Nome_Normalizado"] == nome_normalizado]
                        if not match.empty:
                            funcao = match.iloc[0]["Função"].strip()
                    st.markdown("Função:")
                    valor_exibir = funcao if funcao else "Selecione o colaborador para exibir a função"
                    cor_valor = "#fff" if funcao else "#888"
                    st.markdown(
                        f"""
                        <div style="background:#262730;color:{cor_valor};padding:9px 14px;
                        border-radius:7px;border:1.5px solid #363636;font-size:16px;
                        font-family:inherit;margin-bottom:10px;margin-top:2px;height:38px;
                        display:flex;align-items:center;">{valor_exibir}</div>
                        """,
                        unsafe_allow_html=True
                    )
                    col1, col2 = st.columns(2)
                    with col1:
                        entrada = st.time_input("Entrada", value=datetime.strptime("08:00", "%H:%M").time(), key=f"colab_entrada_reativo_{i}")
                    with col2:
                        saida = st.time_input("Saída", value=datetime.strptime("17:00", "%H:%M").time(), key=f"colab_saida_reativo_{i}")
                    efetivo_lista.append({
                        "Nome": nome,
                        "Função": funcao,
                        "Entrada": entrada.strftime("%H:%M"),
                        "Saída": saida.strftime("%H:%M")
                    })
        st.markdown("---")
        st.subheader("Informações Adicionais")
        ocorrencias = st.text_area("Ocorrências")
        nome_empresa = st.text_input("Responsável pela empresa")
        nome_fiscal = st.text_input("Nome da fiscalização")
        fotos = st.file_uploader("Fotos do serviço", accept_multiple_files=True, type=["png", "jpg", "jpeg"])
        if st.button("Salvar e Gerar Relatório"):
            temp_dir_obj_for_cleanup = None
            fotos_processed_paths = []
            try:
                if not obra or obra == "":
                    st.error("Por favor, selecione a 'Obra'.")
                    st.stop()
                if not contrato or contrato == "":
                    st.error("Por favor, selecione o 'Contrato'.")
                    st.stop()
                if not nome_empresa:
                    st.error("Por favor, preencha o campo 'Responsável pela empresa'.")
                    st.stop()
                registro = {
                    "Obra": obra,
                    "Local": local,
                    "Data": data.strftime("%d/%m/%Y"),
                    "Contrato": contrato,
                    "Clima": clima,
                    "Máquinas": maquinas,
                    "Serviços": servicos,
                    "Efetivo": json.dumps(efetivo_lista, ensure_ascii=False),
                    "Ocorrências": ocorrencias,
                    "Responsável Empresa": nome_empresa,
                    "Fiscalização": nome_fiscal
                }
                with st.spinner("Processando fotos..."):
                    fotos_processed_paths = processar_fotos(fotos, obra, data) if fotos else []
                    if fotos_processed_paths:
                        temp_dir_obj_for_cleanup = Path(fotos_processed_paths[0]).parent
                    elif fotos:
                        st.warning("Nenhuma foto foi processada corretamente. O PDF pode não conter imagens.")
                with st.spinner("Gerando PDF..."):
                    nome_pdf = f"Diario_{obra.replace(' ', '_')}_{data.strftime('%Y-%m-%d')}.pdf"
                    pdf_buffer = gerar_pdf(registro, fotos_processed_paths)
                    if pdf_buffer is None:
                        st.error("Falha ao gerar o PDF. Verifique os logs.")
                        st.stop()
                st.download_button(
                    label="📥 Baixar Relatório PDF",
                    data=pdf_buffer,
                    file_name=nome_pdf,
                    mime="application/pdf",
                    type="primary"
                )
# ... (depois de gerar o PDF e antes do envio de e-mail) ...
                with st.spinner("Enviando para Google Drive..."):
                    try:
                        # Recria o serviço sempre que for usar (seguro para múltiplos uploads)
                        service = build("drive", "v3", credentials=creds, static_discovery=False)
                        pdf_buffer.seek(0)
                        media = MediaIoBaseUpload(pdf_buffer, mimetype='application/pdf', resumable=True)
                        file_metadata = {'name': nome_pdf, 'parents': [DRIVE_FOLDER_ID]}
                        file = service.files().create(
                            body=file_metadata,
                            media_body=media,
                            fields='id',
                            supportsAllDrives=True
                        ).execute()
                        drive_id = file.get("id")
                        if drive_id:
                            st.success(f"PDF salvo no Google Drive! ID: {drive_id}")
                            st.markdown(f"[Abrir no Drive](https://drive.google.com/file/d/{drive_id}/view)")
                            # --- Envio de e-mail, se desejar ---
                            with st.spinner("Enviando e-mail..."):
                                assunto = f"Diário de Obra - {obra} ({data.strftime('%d/%m/%Y')})"
                                corpo = f"""
                                <p>Relatório diário gerado:</p>
                                <ul>
                                    <li>Obra: {obra}</li>
                                    <li>Data: {data.strftime('%d/%m/%Y')}</li>
                                    <li>Responsável: {nome_empresa}</li>
                                </ul>
                                """
                                if enviar_email(
                                    ["administrativo@rdvengenharia.com.br"],
                                    assunto, corpo, drive_id
                                ):
                                    st.success("E-mail enviado com sucesso!")
                                else:
                                    st.warning("PDF salvo no Drive, mas falha no envio do e-mail.")
                        else:
                            st.error("Upload feito, mas não foi possível recuperar o ID do arquivo no Google Drive.")
                    except Exception as e:
                        st.error(f"Falha no upload para o Google Drive. Erro: {e}")

            finally:
                try:
                    if temp_dir_obj_for_cleanup and temp_dir_obj_for_cleanup.exists():
                        shutil.rmtree(temp_dir_obj_for_cleanup)
                except Exception:
                    pass
                try:
                    if temp_icon_path_for_cleanup and os.path.exists(temp_icon_path_for_cleanup):
                        os.remove(temp_icon_path_for_cleanup)
                except Exception:
                    pass

    def render_user_management_page():
        st.title("Gerenciamento de Usuários")
        if st.session_state.role != "admin":
            st.warning("Você não tem permissão para acessar esta página.")
            return
        st.subheader("Adicionar Novo Usuário")
        with st.form("add_user_form", key="add_user_form_key"):
            new_username = st.text_input("Nome de Usuário", key="new_username_input")
            new_password = st.text_input("Senha", type="password", key="new_password_input")
            new_role = st.selectbox("Função", ["user", "admin"], key="new_role_select")
            add_user_submitted = st.form_submit_button("Adicionar Usuário", key="add_user_submit")
            if add_user_submitted:
                if new_username and new_password:
                    hashed_new_password = make_hashes(new_password)
                    add_userdata(new_username, hashed_new_password, new_role)
                    st.success(f"Usuário '{new_username}' adicionado com sucesso como '{new_role}'.")
                else:
                    st.error("Preencha todos os campos para adicionar um novo usuário.")
        st.subheader("Usuários Existentes")
        user_data = view_all_users()
        df_users = pd.DataFrame(user_data, columns=['Username', 'Password Hash', 'Role'])
        st.dataframe(df_users, use_container_width=True)

# Renderiza a página selecionada
if st.session_state.page == "Diário de Obra":
    render_diario_obra_page()

elif st.session_state.page == "Holerite":
    st.title("Holerite")
    st.warning("Funcionalidade em desenvolvimento... Em breve disponível.")

elif st.session_state.page == "Gerenciamento de Usuários":
    render_user_management_page()
