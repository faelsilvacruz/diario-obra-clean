# ✅ IMPORTS
import streamlit as st
import pandas as pd
from datetime import datetime
from pathlib import Path
from PIL import Image as PILImage
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader
from reportlab.lib.colors import HexColor, black, lightgrey, white, darkgrey # Adicionado white e darkgrey
from reportlab.platypus import Table, TableStyle, Paragraph
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet # Adicionado getSampleStyleSheet
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

# Para Autenticação de Usuário
import sqlite3
import hashlib
import base64 # Necessário para a logo no login

# ✅ CONSTANTES
DRIVE_FOLDER_ID = "1BUgZRcBrKksC3eUytoJ5mv_nhMRdAv1d"
LOGO_LOGIN_PATH = "LOGO RDV AZUL.jpeg" # Use a logo com fundo para a tela de login
LOGO_PDF_PATH = "LOGO_RDV_AZUL-sem fundo.png" # Use a logo sem fundo para o PDF

# Converte a logo para Base64 para ser usada como ícone da página
# Adicione esta linha APÓS a definição de get_img_as_base64 e LOGO_PDF_PATH
LOGO_PDF_BASE64 = get_img_as_base64(LOGO_PDF_PATH)
st.set_page_config(page_title="Diário de Obra - RDV", layout="centered", icon=f"data:image/png;base64,{LOGO_PDF_BASE64}")

# ✅ CREDENCIAIS GOOGLE DRIVE
try:
    creds_dict = dict(st.secrets["google_service_account"])
    creds = service_account.Credentials.from_service_account_info(
        creds_dict, scopes=["https://www.googleapis.com/auth/drive"]
    )
except KeyError:
    st.error("Erro: Credenciais da Service Account do Google Drive não encontradas. Por favor, verifique se 'google_service_account' está configurado em seu arquivo .streamlit/secrets.toml.")
    st.stop()
except Exception as e:
    st.error(f"Erro ao carregar credenciais do Google Drive: {e}")
    st.stop()

# ✅ FUNÇÕES DE AUTENTICAÇÃO DE USUÁRIO
def make_hashes(password):
    return hashlib.sha256(str.encode(password)).hexdigest()

def check_hashes(password, hashed_text):
    if make_hashes(password) == hashed_text:
        return True
    return False

# DB Management
conn = sqlite3.connect('users.db')
c = conn.cursor()

def create_usertable():
    c.execute('CREATE TABLE IF NOT EXISTS userstable(username TEXT,password TEXT,role TEXT)')

def add_userdata(username, password, role):
    c.execute('INSERT INTO userstable(username,password,role) VALUES (?,?,?)',(username,password,role))
    conn.commit()

def login_user(username, password):
    c.execute('SELECT * FROM userstable WHERE username =? AND password = ?', (username,password))
    data = c.fetchall()
    if data:
        return True, data[0][2] # Retorna True e a role
    return False, None

def view_all_users():
    c.execute('SELECT * FROM userstable')
    data = c.fetchall()
    return data

def init_db():
    create_usertable()
    # Adiciona um usuário administrador padrão se o banco de dados estiver vazio
    if not view_all_users():
        add_userdata("admin", make_hashes("admin123"), "admin")
        st.success("Usuário 'admin' criado com senha 'admin123'. Por favor, altere sua senha!")


# ✅ FUNÇÃO PARA CARREGAR LOGO COMO BASE64 (PARA O LOGIN)
def get_img_as_base64(file_path):
    if not os.path.exists(file_path):
        # Em ambiente Streamlit Cloud, o caminho pode ser diferente ou a imagem pode não ser acessível facilmente
        # Para debug, podemos tentar caminhos relativos ou absolutos.
        # Mas para o deploy, o ideal é que esteja na raiz do projeto.
        st.error(f"Erro: Arquivo da logo '{file_path}' não encontrado. Verifique o caminho e se está na mesma pasta do 'app.py'.")
        return ""
    try:
        with open(file_path, "rb") as f:
            img_bytes = f.read()
        return base64.b64encode(img_bytes).decode()
    except Exception as e:
        st.error(f"Erro ao carregar a logo para Base64: {e}")
        return ""

# ✅ NOVO: Funções auxiliares para desenhar partes do PDF

def draw_text_area_with_wrap(canvas_obj, text, x, y_start, max_width, line_height=14, font_size=10):
    styles = getSampleStyleSheet()
    style = styles['Normal']
    style.fontSize = font_size
    style.leading = line_height
    style.fontName = "Helvetica"
    p = Paragraph(text, style)
    text_width, text_height = p.wrapOn(canvas_obj, max_width, A4[1]) 
    actual_y_start = y_start - text_height
    p.drawOn(canvas_obj, x, actual_y_start)
    return actual_y_start - line_height 

def draw_header(c, width, height, logo_path):
    c.setFillColor(HexColor("#0F2A4D")) # Cor azul escuro da RDV
    c.rect(0, height-80, width, 80, fill=True, stroke=False)
    c.setFillColor(white) # Texto branco para o cabeçalho
    c.setFont("Helvetica-Bold", 18)
    c.drawCentredString(width/2, height-50, "DIÁRIO DE OBRA")
    c.setFont("Helvetica", 12)
    c.drawCentredString(width/2, height-70, "RDV ENGENHARIA")
    
    if os.path.exists(logo_path):
        try:
            logo = ImageReader(logo_path)
            c.drawImage(logo, 30, height-70, width=100, height=50, preserveAspectRatio=True) 
        except Exception as e:
            print(f"Erro ao carregar a logo '{logo_path}' para o PDF: {e}")

def draw_info_table(c, registro, width, height, y_start, margem):
    data = [
        ["OBRA:", registro.get("Obra", "N/A")],
        ["LOCAL:", registro.get("Local", "N/A")],
        ["DATA:", registro.get("Data", "N/A")],
        ["CONTRATO:", registro.get("Contrato", "N/A")]
    ]
    
    table = Table(data, colWidths=[100, width - 100 - (2 * margem)]) 
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
        st.warning("Erro ao decodificar JSON do efetivo para o PDF. Verifique o formato dos dados.")
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

# ✅ FUNÇÃO DE GERAÇÃO DE PDF (AGORA USANDO AS NOVAS FUNÇÕES AUXILIARES)
def gerar_pdf(registro, fotos_paths):
    buffer = io.BytesIO()
    try:
        c = canvas.Canvas(buffer, pagesize=A4)
        width, height = A4
        margem = 30

        # --- Desenha o Cabeçalho ---
        draw_header(c, width, height, LOGO_PDF_PATH)
        y = height - 100 

        # --- Desenha Tabela de Dados Principais ---
        y = draw_info_table(c, registro, width, height, y, margem)
        
        # --- SEÇÃO SERVIÇOS EXECUTADOS / ANOTAÇÕES DA EMPRESA ---
        c.setFont("Helvetica-Bold", 10)
        c.drawCentredString(width / 2, y - 10, "Serviços Executados / Anotações da Empresa")
        c.setFont("Helvetica", 10)
        y -= 25

        # (1) CLIMA
        box_clima_h = 20
        c.rect(margem, y - box_clima_h, width - 2*margem, box_clima_h)
        c.drawString(margem + 5, y - 15, f"(1)- CLIMA: {registro.get('Clima', 'N/A')}")
        y -= (box_clima_h + 5)

        # (2) MÁQUINAS E EQUIPAMENTOS
        box_maquinas_h = 60
        c.rect(margem, y - box_maquinas_h, width - 2*margem, box_maquinas_h)
        c.drawString(margem + 5, y - 15, "(2)- MÁQUINAS E EQUIPAMENTOS:")
        y_text_maquinas = y - 30
        draw_text_area_with_wrap(c, registro.get('Máquinas', 'Nenhuma máquina/equipamento informado.'), margem + 15, y_text_maquinas, (width - 2*margem) - 20, line_height=12)
        y -= (box_maquinas_h + 5)

        # (3) SERVIÇOS EXECUTADOS
        box_servicos_h = 100
        c.rect(margem, y - box_servicos_h, width - 2*margem, box_servicos_h)
        c.drawString(margem + 5, y - 15, "(3)- SERVIÇOS EXECUTADOS:")
        y_text_servicos = y - 30
        draw_text_area_with_wrap(c, registro.get('Serviços', 'Nenhum serviço executado informado.'), margem + 15, y_text_servicos, (width - 2*margem) - 20, line_height=12)
        y -= (box_servicos_h + 5)

        # --- Desenha Tabela de Efetivo de Pessoal ---
        c.setFont("Helvetica-Bold", 10)
        c.drawString(margem, y - 10, "(4)- EFETIVO DE PESSOAL")
        y -= 25
        y = draw_efetivo_table(c, registro.get("Efetivo", "[]"), width, height, y, margem) 

        # --- SEÇÃO (5) OUTRAS OCORRÊNCIAS ---
        c.setFont("Helvetica-Bold", 10)
        c.drawString(margem, y - 10, "(5)- OUTRAS OCORRÊNCIAS:")
        c.setFont("Helvetica", 10)
        y -= 25
        
        box_ocorrencias_h = 60
        c.rect(margem, y - box_ocorrencias_h, width - 2*margem, box_ocorrencias_h)
        y_text_ocorrencias = y - 15
        draw_text_area_with_wrap(c, registro.get('Ocorrências', 'Nenhuma ocorrência informada.'), margem + 5, y_text_ocorrencias, (width - 2*margem) - 10, line_height=12)
        y -= (box_ocorrencias_h + 10)

        # --- SEÇÃO ANOTAÇÕES DA FISCALIZAÇÃO ---
        c.setFont("Helvetica-Bold", 10)
        c.drawCentredString(width / 2, y - 10, "ANOTAÇÕES DA FISCALIZAÇÃO")
        c.setFont("Helvetica", 10)
        y -= 25
        
        box_fiscalizacao_h = 80
        c.rect(margem, y - box_fiscalizacao_h, width - 2*margem, box_fiscalizacao_h)
        c.drawString(margem + 5, y - box_fiscalizacao_h + 10, f"Nome da Fiscalização: {registro.get('Fiscalização', 'N/A')}")
        y -= (box_fiscalizacao_h + 10)

        # --- SEÇÃO MAPA PLUVIOMÉTRICO ---
        c.setFont("Helvetica-Bold", 10)
        c.drawCentredString(width / 2, y - 10, "Mapa Pluviométrico")
        c.setFont("Helvetica", 10)
        y -= 25

        mapa_pluv_data = [
            ["00:00 às 3:00", ""], ["3:00 às 6:00", ""], ["6:00 às 9:00", ""],
            ["9:00 às 12:00", ""], ["12:00 às 15:00", ""], ["15:00 às 18:00", ""],
            ["18:00 às 21:00", ""], ["21:00 às 23:59", ""]
        ]

        table_pluv = Table(mapa_pluv_data, colWidths=[80, (width - 2*margem - 80)])
        table_pluv.setStyle(TableStyle([
            ('GRID', (0,0), (-1,-1), 0.5, black),
            ('ALIGN', (0,0), (-1,-1), 'LEFT'),
            ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
            ('LEFTPADDING', (0,0), (-1,-1), 5),
            ('RIGHTPADDING', (0,0), (-1,-1), 5),
            ('TOPPADDING', (0,0), (-1,-1), 3),
            ('BOTTOMPADDING', (0,0), (-1,-1), 3),
        ]))
        table_pluv_width, table_pluv_height = table_pluv.wrapOn(c, width - 2*margem, height)
        table_pluv.drawOn(c, margem, y - table_pluv_height)
        y -= (table_pluv_height + 10)
        
        # Legenda das cores do Mapa Pluviométrico
        clima_legend = [
            ["BOM", HexColor("#ADD8E6")], 
            ["CHUVA", HexColor("#87CEEB")], 
            ["GAROA", HexColor("#6495ED")], 
            ["IMPRATICÁVEL", HexColor("#FF0000")], 
            ["FERIADO", HexColor("#008000")], 
            ["GUARDA", HexColor("#FFA500")] 
        ]
        legend_x_offset = width / 2 + 30
        legend_y_start = y + table_pluv_height / 2 + 10
        
        c.setFont("Helvetica", 8)
        for i, (text, color) in enumerate(clima_legend):
            c.setFillColor(color)
            c.rect(legend_x_offset, legend_y_start - (i * 15), 10, 10, fill=1)
            c.setFillColor(black)
            c.drawString(legend_x_offset + 15, legend_y_start - (i * 15) + 2, text)

        # --- Desenha o Rodapé ---
        draw_footer(c, width, margem, y, registro)

        # --- Adição de Fotos ---
        for i, foto_path in enumerate(fotos_paths):
            try:
                if not Path(foto_path).exists():
                    st.warning(f"A foto '{Path(foto_path).name}' não foi encontrada e será ignorada no PDF.")
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
                
                if img_width > max_img_width or img_height > max_img_height:
                    if (max_img_width / aspect_ratio) <= max_img_height:
                        new_width = max_img_width
                        new_height = max_img_width / aspect_ratio
                    else:
                        new_height = max_img_height
                        new_width = max_img_height * aspect_ratio
                    img = img.resize((int(new_width), int(new_height)), PILImage.LANCZOS)
                else: 
                    new_width = img_width
                    new_height = img_height
                
                x_pos_img = margem + (max_img_width - new_width) / 2
                img_y_pos = y_foto - new_height - 10 
                
                c.drawImage(ImageReader(img), x_pos_img, img_y_pos, width=new_width, height=new_height)

            except Exception as e:
                st.warning(f"Erro ao adicionar a foto '{Path(foto_path).name}' ao PDF: {str(e)}. A foto será ignorada.")
                continue

        c.save()
        buffer.seek(0)
        return buffer

    except Exception as e:
        st.error(f"Erro crítico ao gerar o documento PDF: {str(e)}")
        return None

# ✅ FUNÇÃO DE UPLOAD PARA GOOGLE DRIVE
def upload_para_drive_seguro(pdf_buffer, nome_arquivo):
    try:
        pdf_buffer.seek(0)
        service = build("drive", "v3", credentials=creds, static_discovery_docs=False) # static_discovery_docs=False é importante no deploy
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
        st.error(f"Erro HTTP ao enviar para o Google Drive: Status {error.resp.status}. Detalhes: {error.content.decode('utf-8')}")
        st.error("Por favor, verifique as **permissões da sua Service Account** e se a **pasta de destino no Google Drive está compartilhada** corretamente com ela (permissão de 'Editor').")
        return None
    except Exception as e:
        st.error(f"Erro inesperado ao tentar enviar o PDF para o Google Drive: {e}")
        return None

# ✅ FUNÇÃO DE ENVIO DE E-MAIL REVISADA
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
        
    except KeyError:
        st.error("Erro: Credenciais de e-mail não encontradas em '.streamlit/secrets.toml'. Por favor, verifique.")
        return False
    except Exception as e:
        st.error(f"Falha no envio do e-mail: {str(e)}")
        return False


# --- LÓGICA PRINCIPAL DO APP (COM LOGIN) ---

# Inicializa o estado da sessão e o banco de dados de usuários
if 'logged_in' not in st.session_state:
    st.session_state.logged_in = False
    st.session_state.username = None
    st.session_state.role = None
init_db() # Garante que o DB é criado/inicializado na primeira execução

# --- Tela de Login ---
if not st.session_state.logged_in:
    # Layout personalizado para a tela de login
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
            background: #0F2A4D; /* Sua cor principal */
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
    """, unsafe_allow_html=True)

    with st.form("Login"):
        username_input = st.text_input("Usuário", placeholder="Digite seu nome de usuário")
        password_input = st.text_input("Senha", type="password")
        submitted = st.form_submit_button("Entrar")
        
        if submitted:
            if username_input and password_input:
                hashed_password = make_hashes(password_input) # Hash da senha digitada
                authenticated, role = login_user(username_input, hashed_password) # Autentica com a senha hashed
                if authenticated:
                    st.session_state["logged_in"] = True
                    st.session_state["username"] = username_input
                    st.session_state["role"] = role
                    st.rerun()
                else:
                    st.error("Credenciais inválidas. Verifique seu usuário e senha.")
            else:
                st.warning("Por favor, preencha todos os campos.")
    
    st.markdown("</div>", unsafe_allow_html=True) 
    st.stop() 


# ✅ LÓGICA DO APP APÓS LOGIN
# Se o usuário está logado, mostra o conteúdo do aplicativo
if st.session_state.logged_in:
    st.sidebar.title(f"Bem-vindo, {st.session_state.username}!")
    st.sidebar.button("Sair", on_click=lambda: st.session_state.clear())

    menu = ["Diário de Obra"]
    if st.session_state.role == "admin":
        menu.append("Gerenciamento de Usuários")
    
    choice = st.sidebar.selectbox("Navegar", menu)

    # Função para a página do Diário de Obra
    def render_diario_obra_page():
        # ✅ CARREGAMENTO DE CSVs (Movido para dentro da função para recarregar se necessário)
        @st.cache_data
        def carregar_arquivo_csv(nome_arquivo):
            if not os.path.exists(nome_arquivo):
                st.error(f"Erro: Arquivo de dados '{nome_arquivo}' não encontrado. Por favor, verifique se os CSVs (colaboradores.csv, obras.csv, contratos.csv) estão na raiz do projeto.")
                st.stop()
            return pd.read_csv(nome_arquivo)

        try:
            colab_df = carregar_arquivo_csv("colaboradores.csv")
            obras_df = carregar_arquivo_csv("obras.csv")
            contratos_df = carregar_arquivo_csv("contratos.csv")
        except Exception as e:
            st.error(f"Erro ao carregar arquivos CSV: {e}")
            st.stop()

        colaboradores_lista = colab_df["Nome"].tolist()
        obras_lista = [""] + obras_df["Nome"].tolist()
        contratos_lista = [""] + contratos_df["Nome"].tolist()

        st.title("Relatório Diário de Obra - RDV Engenharia")

        with st.form("relatorio_form"):
            st.subheader("Dados Gerais da Obra")
            obra = st.selectbox("Obra", obras_lista)
            local = st.text_input("Local")
            data = st.date_input("Data", value=datetime.today())
            contrato = st.selectbox("Contrato", contratos_lista)
            clima = st.selectbox("Condições do dia", ["Bom", "Chuva", "Garoa", "Impraticável", "Feriado"])
            maquinas = st.text_area("Máquinas e equipamentos utilizados")
            servicos = st.text_area("Serviços executados no dia")

            st.subheader("Efetivo de Pessoal")
            max_colab_display = len(colaboradores_lista) if len(colaboradores_lista) > 0 else 10
            qtd_colaboradores = st.number_input("Quantos colaboradores hoje?", min_value=1, max_value=max_colab_display, step=1)
            
            efetivo_lista = []
            for i in range(qtd_colaboradores):
                with st.expander(f"Colaborador {i+1}"):
                    nome_selecionado = st.selectbox("Nome", colaboradores_lista if colaboradores_lista else ["Nenhum colaborador disponível"], key=f"nome_{i}")
                    
                    funcao_sugerida = ""
                    if nome_selecionado and nome_selecionado in colab_df["Nome"].values:
                        funcao_sugerida = colab_df.loc[colab_df["Nome"] == nome_selecionado, "Função"].values[0]

                    funcao_digitada = st.text_input("Função", value=funcao_sugerida, key=f"funcao_{i}")
                    ent = st.time_input("Entrada", key=f"ent_{i}")
                    sai = st.time_input("Saída", key=f"sai_{i}")
                    efetivo_lista.append({
                        "Nome": nome_selecionado,
                        "Função": funcao_digitada,
                        "Entrada": ent.strftime("%H:%M"),
                        "Saída": sai.strftime("%H:%M")
                    })

            st.subheader("Informações Adicionais")
            ocorrencias = st.text_area("Ocorrências")
            nome_empresa = st.text_input("Responsável pela empresa")
            nome_fiscal = st.text_input("Nome da fiscalização")
            fotos = st.file_uploader("Fotos do serviço", accept_multiple_files=True, type=["png", "jpg", "jpeg"])

            submitted = st.form_submit_button("Salvar e Gerar Relatório")

        # ✅ LÓGICA DE EXECUÇÃO DO RELATÓRIO
        temp_dir_obj_for_cleanup = None 
        fotos_processed_paths = [] 

        if submitted:
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

                with st.spinner("Processando fotos... Isso pode levar alguns segundos..."):
                    fotos_processed_paths = processar_fotos(fotos, obra, data) if fotos else []
                    
                    if fotos_processed_paths:
                        temp_dir_obj_for_cleanup = Path(fotos_processed_paths[0]).parent
                    elif fotos: 
                        st.warning("⚠️ Nenhuma foto foi processada corretamente. O PDF pode não conter imagens.")
                        
                with st.spinner("Gerando PDF..."):
                    nome_pdf = f"Diario_{obra.replace(' ', '_')}_{data.strftime('%Y-%m-%d')}.pdf"
                    pdf_buffer = gerar_pdf(registro, fotos_processed_paths)

                    if pdf_buffer is None:
                        st.error("Falha crítica ao gerar o PDF. Por favor, tente novamente ou verifique os logs para detalhes.")
                        st.stop()
                        
                st.download_button(
                    label="📥 Baixar Relatório PDF",
                    data=pdf_buffer,
                    file_name=nome_pdf,
                    mime="application/pdf",
                    type="primary"
                )

                drive_id = None
                with st.spinner("Enviando relatório para o Google Drive..."):
                    drive_id = upload_para_drive_seguro(pdf_buffer, nome_pdf)

                    if drive_id:
                        st.success(f"PDF salvo com sucesso no Google Drive! ID: {drive_id}")
                        st.markdown(f"**[Clique aqui para abrir no Google Drive](https://drive.google.com/file/d/{drive_id}/view)**")

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
                            """
                            
                            destinatarios_email = [
                                "comercial@rdvengenharia.com.br",
                                "administrativo@rdvengenharia.com.br"
                            ]
                            
                            if enviar_email(destinatarios_email, assunto_email, corpo_email_html, drive_id):
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
                        st.error("O upload para o Google Drive falhou. O e-mail de notificação não foi enviado.")

            except Exception as e:
                st.error(f"Ocorreu um erro inesperado durante o processamento do relatório: {str(e)}. Por favor, tente novamente.")

            finally:
                try:
                    if temp_dir_obj_for_cleanup and temp_dir_obj_for_cleanup.exists():
                        st.info(f"Limpando diretório temporário: {temp_dir_obj_for_cleanup}")
                        shutil.rmtree(temp_dir_obj_for_cleanup)
                except Exception as e:
                    st.warning(f"Erro ao tentar limpar arquivos temporários: {str(e)}. Por favor, verifique os logs.")

    # Função para a página de Gerenciamento de Usuários
    def render_user_management_page():
        st.title("Gerenciamento de Usuários")

        if st.session_state.role != "admin":
            st.warning("Você não tem permissão para acessar esta página.")
            return

        st.subheader("Adicionar Novo Usuário")
        with st.form("add_user_form"):
            new_username = st.text_input("Nome de Usuário")
            new_password = st.text_input("Senha", type="password")
            new_role = st.selectbox("Função", ["user", "admin"])
            add_user_submitted = st.form_submit_button("Adicionar Usuário")

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
        st.dataframe(df_users)

    # Lógica de roteamento do menu
    if choice == "Diário de Obra":
        render_diario_obra_page()
    elif choice == "Gerenciamento de Usuários":
        render_user_management_page()
