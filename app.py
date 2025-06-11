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
DRIVE_FOLDER_ID = "1BUgZRcBrKksC3eUytoJ5mv_nhMRcAv1d" # ID da pasta no Google Drive
LOGO_LOGIN_PATH = "LOGO RDV AZUL.jpeg" # Para a tela de login
LOGO_PDF_PATH = "LOGO_RDV_AZUL-sem fundo.png" # Para o cabeçalho do PDF
LOGO_ICON_PATH = "LOGO_RDV_AZUL-sem fundo.png" # Usando a mesma logo do PDF para o ícone da página


# ✅ FUNÇÃO PARA CARREGAR IMAGEM COMO BASE64 (PARA LOGIN)
def get_img_as_base64(file_path):
    """Carrega uma imagem e retorna sua representação em Base64."""
    if not os.path.exists(file_path):
        st.error(f"Erro: Arquivo da logo '{file_path}' não encontrado. Por favor, verifique o caminho e se está na mesma pasta do 'app.py'.")
        return ""
    try:
        with open(file_path, "rb") as f:
            img_bytes = f.read()
        return base64.b64encode(img_bytes).decode()
    except Exception as e:
        st.error(f"Erro ao carregar a logo para Base64: {e}")
        return ""

# ✅ FUNÇÃO PARA CARREGAR ÍCONE DA PÁGINA (MAIS ROBUSTA)
def load_page_icon():
    """
    Carrega o ícone para st.set_page_config.
    Retorna o caminho do arquivo de imagem temporário ou None se houver erro.
    """
    if LOGO_ICON_PATH and os.path.exists(LOGO_ICON_PATH):
        try:
            img = PILImage.open(LOGO_ICON_PATH)
            img.thumbnail((32, 32), PILImage.Resampling.LANCZOS)
            
            temp_icon_file = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
            img.save(temp_icon_file.name, format="PNG")
            temp_icon_file.close()
            return temp_icon_file.name
        except Exception as e:
            st.warning(f"Erro ao tentar carregar ou redimensionar LOGO_ICON_PATH para o ícone: {e}")
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
            except Exception as e:
                st.warning(f"Erro ao tentar carregar ou redimensionar LOGO_PDF_PATH para o ícone: {e}")
                return None
        
        st.warning(f"Nenhum arquivo de imagem válido encontrado para o ícone ({LOGO_ICON_PATH} ou {LOGO_PDF_PATH}).")
        return None

# ✅ CONFIGURAÇÃO DA PÁGINA STREAMLIT (COM TRATAMENTO DE ERRO)
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
except Exception as e:
    st.warning(f"Erro durante a configuração da página (provavelmente com o ícone): {e}")
    st.set_page_config(
        page_title="Diário de Obra - RDV",
        layout="centered"
    )

for path in [LOGO_LOGIN_PATH, LOGO_PDF_PATH, LOGO_ICON_PATH]:
    if not os.path.exists(path):
        st.warning(f"Arquivo não encontrado: {path}. Verifique se os nomes e caminhos estão corretos.")

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

# ✅ FUNÇÕES DE AUTENTICAÇÃO DE USUÁRIO (SQLite)
conn = sqlite3.connect('users.db')
c = conn.cursor()

def make_hashes(password):
    return hashlib.sha256(str.encode(password)).hexdigest()

def check_hashes(password, hashed_text):
    return make_hashes(password) == hashed_text

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
    """Inicializa o banco de dados e cria um usuário admin padrão se não houver usuários."""
    create_usertable()
    if not view_all_users():
        add_userdata("admin", make_hashes("admin123"), "admin")
        st.success("Usuário 'admin' criado com senha 'admin123'. Por favor, altere sua senha após o primeiro login.")


# ✅ FUNÇÕES AUXILIARES PARA GERAÇÃO DE PDF

def draw_text_area_with_wrap(canvas_obj, text, x, y_start, max_width, line_height=14, font_size=10):
    """Desenha texto em um canvas ReportLab com quebra de linha."""
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
    """Desenha o cabeçalho principal do PDF com logo e título."""
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
        except Exception as e:
            st.warning(f"Erro ao carregar a logo '{logo_path}' para o PDF: {e}")

def draw_info_table(c, registro, width, height, y_start, margem):
    """Desenha a tabela de informações gerais da obra."""
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
    """Desenha a tabela de efetivo de pessoal."""
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
    """Desenha o rodapé com as áreas de assinatura."""
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


# ✅ FUNÇÃO DE GERAÇÃO DE PDF PRINCIPAL
def gerar_pdf(registro, fotos_paths):
    """
    Generates the daily work report in PDF format, including form data
    and processed photos, using the new layout.
    """
    buffer = io.BytesIO()

    try:
        c = canvas.Canvas(buffer, pagesize=A4)
        width, height = A4
        margem = 30

        draw_header(c, width, height, LOGO_PDF_PATH)
        y = height - 100

        y = draw_info_table(c, registro, width, height, y, margem)
        
        c.setFont("Helvetica-Bold", 10)
        c.drawCentredString(width / 2, y - 10, "Serviços Executados / Anotações da Empresa")
        c.setFont("Helvetica", 10)
        y -= 25

        box_clima_h = 20
        c.rect(margem, y - box_clima_h, width - 2*margem, box_clima_h)
        c.drawString(margem + 5, y - 15, f"(1)- CLIMA: {registro.get('Clima', 'N/A')}")
        y -= (box_clima_h + 5)

        box_maquinas_h = 60
        c.rect(margem, y - box_maquinas_h, width - 2*margem, box_maquinas_h)
        c.drawString(margem + 5, y - 15, "(2)- MÁQUINAS E EQUIPAMENTOS:")
        y_text_maquinas = y - 30
        draw_text_area_with_wrap(c, registro.get('Máquinas', 'Nenhuma máquina/equipamento informado.'), margem + 15, y_text_maquinas, (width - 2*margem) - 20, line_height=12)
        y -= (box_maquinas_h + 5)

        box_servicos_h = 100
        c.rect(margem, y - box_servicos_h, width - 2*margem, box_servicos_h)
        c.drawString(margem + 5, y - 15, "(3)- SERVIÇOS EXECUTADOS:")
        y_text_servicos = y - 30
        draw_text_area_with_wrap(c, registro.get('Serviços', 'Nenhum serviço executado informado.'), margem + 15, y_text_servicos, (width - 2*margem) - 20, line_height=12)
        y -= (box_servicos_h + 5)

        c.setFont("Helvetica-Bold", 10)
        c.drawString(margem, y - 10, "(4)- EFETIVO DE PESSOAL")
        y -= 25
        y = draw_efetivo_table(c, registro.get("Efetivo", "[]"), width, height, y, margem) 

        c.setFont("Helvetica-Bold", 10)
        c.drawString(margem, y - 10, "(5)- OUTRAS OCORRÊNCIAS:")
        c.setFont("Helvetica", 10)
        y -= 25
        
        box_ocorrencias_h = 60
        c.rect(margem, y - box_ocorrencias_h, width - 2*margem, box_ocorrencias_h)
        y_text_ocorrencias = y - 15
        draw_text_area_with_wrap(c, registro.get('Ocorrências', 'Nenhuma ocorrência informada.'), margem + 5, y_text_ocorrencias, (width - 2*margem) - 10, line_height=12)
        y -= (box_ocorrencias_h + 10)

        c.setFont("Helvetica-Bold", 10)
        c.drawCentredString(width / 2, y - 10, "ANOTAÇÕES DA FISCALIZAÇÃO")
        c.setFont("Helvetica", 10)
        y -= 25
        
        box_fiscalizacao_h = 80
        c.rect(margem, y - box_fiscalizacao_h, width - 2*margem, box_fiscalizacao_h)
        c.drawString(margem + 5, y - box_fiscalizacao_h + 10, f"Nome da Fiscalização: {registro.get('Fiscalização', 'N/A')}")
        y -= (box_fiscalizacao_h + 10)

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
        
        clima_legend = [
            ["BOM", HexColor("#ADD8E6")],
            ["CHUVA", HexColor("#87CEEB")],
            ["GAROA", HexColor("#6495ED")],
            ["IMPRATICÁVEL", HexColor("#FF0000")],
            ["FERIADO", HexColor("#008000")],
            ["GUARDA", HexColor("#FFA500")]
        ]
        
        legend_x_offset = width / 2 + 30 
        legend_y_start = (y + table_pluv_height) - (table_pluv_height / 2) + (len(clima_legend) * 15 / 2) - 10
        
        c.setFont("Helvetica", 8)
        for i, (text, color) in enumerate(clima_legend):
            c.setFillColor(color)
            c.rect(legend_x_offset, legend_y_start - (i * 15), 10, 10, fill=1)
            c.setFillColor(black)
            c.drawString(legend_x_offset + 15, legend_y_start - (i * 15) + 2, text)

        draw_footer(c, width, margem, y, registro) 

        for i, foto_path in enumerate(fotos_paths):
            try:
                if not Path(foto_path).exists():
                    st.warning(f"The photo '{Path(foto_path).name}' was not found in the temporary path and will be ignored in the PDF.")
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

            except Exception as img_error:
                st.warning(f"Error adding photo '{Path(foto_path).name}' to PDF: {str(img_error)}. The photo will be ignored.")
                continue

        c.save()
        buffer.seek(0)
        return buffer

    except Exception as e:
        st.error(f"Critical error generating the PDF document: {str(e)}")
        return None


# ✅ FUNÇÃO DE PROCESSAMENTO DE FOTOS
def processar_fotos(fotos_upload, obra_nome, data_relatorio):
    """
    Processes photos, resizes, temporarily saves them to disk,
    and returns the paths of the processed files.
    """
    fotos_processadas_paths = []
    temp_dir_path_obj = None

    try:
        temp_dir_path_obj = Path(tempfile.mkdtemp(prefix="diario_obra_"))
        st.info(f"Temporary directory created for photos: {temp_dir_path_obj}")

        for i, foto_file in enumerate(fotos_upload):
            if foto_file is None:
                st.warning(f"Uploaded photo {i+1} is empty and will be ignored.")
                continue

            try:
                nome_foto_base = f"{obra_nome.replace(' ', '_')}_{data_relatorio.strftime('%Y-%m-%d')}_foto{i+1}"
                nome_foto_final = f"{nome_foto_base}{Path(foto_file.name).suffix}"
                caminho_foto_temp = temp_dir_path_obj / nome_foto_final
                
                st.info(f"Attempting to save photo {i+1} ({foto_file.name}) to: {caminho_foto_temp}")

                with open(caminho_foto_temp, "wb") as f:
                    f.write(foto_file.getbuffer())

                if not caminho_foto_temp.exists():
                    raise FileNotFoundError(f"Temporary file for photo {i+1} was not created at {caminho_foto_temp}")
                
                st.info(f"Photo {i+1} temporarily saved. Size: {caminho_foto_temp.stat().st_size} bytes.")

                img = PILImage.open(caminho_foto_temp)
                img.thumbnail((1200, 1200), PILImage.Resampling.LANCZOS)
                img.save(caminho_foto_temp, "JPEG", quality=85)

                fotos_processadas_paths.append(str(caminho_foto_temp))
                st.info(f"Photo {i+1} processed and ready: {caminho_foto_temp}")

            except Exception as img_error:
                st.warning(f"Failed to process photo {i+1} ({foto_file.name}): {str(img_error)}. This photo will be ignored in the PDF.")
                continue

        return fotos_processadas_paths
        
    except Exception as e:
        st.error(f"Critical error in initial photo processing: {str(e)}")
        if temp_dir_path_obj and temp_dir_path_obj.exists():
            shutil.rmtree(temp_dir_path_obj)
            st.warning(f"Temporary directory {temp_dir_path_obj} cleaned due to critical error in initial photo processing.")
        return []


# ✅ FUNÇÃO DE UPLOAD PARA GOOGLE DRIVE
def upload_para_drive_seguro(pdf_buffer, nome_arquivo):
    """
    Faz o upload de um buffer de PDF para uma pasta específica no Google Drive.
    Inclui tratamento de erros da API.
    """
    try:
        pdf_buffer.seek(0)
        service = build("drive", "v3", credentials=creds, static_discovery_docs=False)
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
    """
    Envia e-mail com tratamento robusto de erros usando Yagmail.
    Espera um corpo de e-mail já em formato HTML.
    """
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
        st.error(f"""
        Falha no envio do e-mail: {str(e)}
        
        **Causa Comum para 'gaierror: [Errno 11001] getaddrinfo failed':**
        Este erro geralmente indica um problema de rede ou DNS, onde o aplicativo não conseguiu resolver o endereço do servidor de e-mail (`smtp.gmail.com`) ou se conectar a ele.
        
        **Possíveis Soluções:**
        1.  **Verifique sua conexão com a internet.**
        2.  **Firewall/Proxy:** Certifique-se de que não há um firewall ou servidor proxy bloqueando o acesso à porta 587 (para STARTTLS) ou 465 (para SSL) para `smtp.gmail.com`.
        3.  **DNS:** Verifique as configurações de DNS do ambiente onde a aplicação está rodando.
        4.  **Permissões da Conta Gmail:** Confirme que a "Verificação em Duas Etapas" está ativada e que você gerou uma "Senha de Aplicativo" para usar no `secrets.toml` (em vez da senha normal da conta Google).
        5.  **Permitir aplicativos menos seguros (legado):** Se a verificação em duas etapas não for uma opção, certifique-se de que "Acesso a apps menos seguros" esteja ativado para a conta de e-mail (embora esta opção esteja sendo descontinuada pelo Google).
        """)
        return False


# --- LÓGICA PRINCIPAL DO APP (COM LOGIN) ---

# Inicializa o estado da sessão e o banco de dados de usuários
if 'logged_in' not in st.session_state:
    st.session_state.logged_in = False
    st.session_state.username = None
    st.session_state.role = None
# Inicializa o session_state para o número de colaboradores
if 'num_colabs_slider' not in st.session_state:
    # ALTERADO: Valor inicial padrão do slider para 0
    st.session_state.num_colabs_slider = 0 
init_db()

# --- Tela de Login ---
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

# ✅ LÓGICA DO APP APÓS LOGIN
if st.session_state.logged_in:
    st.sidebar.title(f"Bem-vindo, {st.session_state.username}!")
    st.sidebar.button("Sair", on_click=lambda: st.session_state.clear(), key="logout_button")

    menu = ["Diário de Obra"]
    if st.session_state.role == "admin":
        menu.append("Gerenciamento de Usuários")
    
    choice = st.sidebar.selectbox("Navegar", menu, key="sidebar_menu")

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
    
    # --- Validação e carregamento de colaboradores.csv ---
    colab_df = pd.DataFrame()
    colaboradores_lista = []
    try:
        colab_df = pd.read_csv("colaboradores.csv")
        if not {"Nome", "Função"}.issubset(colab_df.columns):
            st.error("O arquivo 'colaboradores.csv' deve conter as colunas 'Nome' e 'Função'.")
            colab_df = pd.DataFrame() # Reseta para DataFrame vazio se colunas faltarem
        else:
            colaboradores_lista = colab_df["Nome"].tolist()
    except FileNotFoundError:
        st.error("Arquivo 'colaboradores.csv' não encontrado. Por favor, crie-o na mesma pasta da aplicação.")
    except Exception as e:
        st.error(f"Erro ao carregar ou processar 'colaboradores.csv': {e}")
        colab_df = pd.DataFrame()

    if obras_df.empty or contratos_df.empty:
        st.stop()

    obras_lista = [""] + obras_df["Nome"].tolist()
    contratos_lista = [""] + contratos_df["Nome"].tolist()
    
    st.title("Relatório Diário de Obra - RDV Engenharia")

    # --- 1. DADOS GERAIS DA OBRA (PRIMEIRA SEÇÃO) ---
    st.subheader("Dados Gerais da Obra")
    obra = st.selectbox("Obra", obras_lista, key="obra_select")
    local = st.text_input("Local", key="local_input")
    data = st.date_input("Data", value=datetime.today(), key="data_input")
    contrato = st.selectbox("Contrato", contratos_lista, key="contrato_select")
    clima = st.selectbox("Condições do dia", ["Bom", "Chuva", "Garoa", "Impraticável", "Feriado", "Guarda"], key="clima_select")
    maquinas = st.text_area("Máquinas e equipamentos utilizados", key="maquinas_text")
    servicos = st.text_area("Serviços executados no dia", key="servicos_text")

    st.markdown("---") # Linha separadora para visual

    # --- 2. EFETIVO DE PESSOAL (SLIDER e CONTROLES - FORA DO FORMULÁRIO) ---
    # Esta seção fica aqui para que o slider possa disparar re-execuções e atualizar os campos dinamicamente.
    st.subheader("Efetivo de Pessoal")
# Adiciona slider de colaboradores ANTES do uso de qtd_colaboradores
max_colabs_slider = len(colaboradores_lista) if colaboradores_lista else 20
qtd_colaboradores = st.slider(
    "Quantos colaboradores hoje?",
    min_value=0,
    max_value=max_colabs_slider,
    value=st.session_state.get("num_colabs_slider", 0),
    step=1,
    key="num_colabs_slider_widget",
    on_change=lambda: st.session_state.update(num_colabs_slider=st.session_state.num_colabs_slider_widget)
)

# Atualiza o valor no session_state para uso consistente
st.session_state.num_colabs_slider = qtd_colaboradores

    
    # REMOVIDOS: Prints de debug e Botão de reset
    # st.write(f"Quantidade atual de colaboradores: {qtd_colaboradores}")
    # st.write(f"Lista de colaboradores disponíveis: {colaboradores_lista}")
    # if st.button("Resetar número de colaboradores", key="reset_colabs_btn"):
    #     st.session_state.num_colabs_slider = 2
    #     st.rerun() # Necessário para re-renderizar o slider com o novo valor do session_state

    st.markdown("---") # Separador antes do formulário principal

    # --- O FORMULÁRIO PRINCIPAL (contém os detalhes dos colaboradores e informações adicionais) ---
with st.form(key="relatorio_form", clear_on_submit=False):
    efetivo_lista = []
    for i in range(qtd_colaboradores): 
        with st.expander(f"Colaborador {i+1}", expanded=True):
            nome = st.selectbox("Nome", [""] + colaboradores_lista, key=f"colab_nome_{i}")
            funcao = ""
            if nome and not colab_df.empty and nome in colab_df["Nome"].values:
                funcao = colab_df.loc[colab_df["Nome"] == nome, "Função"].values[0]
            funcao = st.text_input("Função", value=funcao, key=f"colab_funcao_{i}")
            col1, col2 = st.columns(2)
            with col1:
                entrada = st.time_input("Entrada", value=datetime.strptime("08:00", "%H:%M").time(), key=f"colab_entrada_{i}")
            with col2:
                saida = st.time_input("Saída", value=datetime.strptime("17:00", "%H:%M").time(), key=f"colab_saida_{i}")
            efetivo_lista.append({"Nome": nome, "Função": funcao, "Entrada": entrada.strftime("%H:%M"), "Saída": saida.strftime("%H:%M")})

    st.markdown("---")
    st.subheader("Informações Adicionais")
    ocorrencias = st.text_area("Ocorrências", key="ocorrencias_text")
    nome_empresa = st.text_input("Responsável pela empresa", key="responsavel_empresa_input")
    nome_fiscal = st.text_input("Nome da fiscalização", key="fiscalizacao_input")
    fotos = st.file_uploader("Fotos do serviço", accept_multiple_files=True, type=["png", "jpg", "jpeg"], key="fotos_uploader")

    # ✅ Botão agora está DENTRO do form
    submitted = st.form_submit_button("Salvar e Gerar Relatório", key="submit_button")

    if submitted:
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
                pdf_buffer.seek(0)
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
                    st.info(f"Limpando diretório temporário de fotos: {temp_dir_obj_for_cleanup}")
                    shutil.rmtree(temp_dir_obj_for_cleanup)
            except Exception as e:
                st.warning(f"Erro ao tentar limpar diretório temporário de fotos: {str(e)}. Por favor, verifique os logs.")
            
            try:
                if temp_icon_path_for_cleanup and os.path.exists(temp_icon_path_for_cleanup):
                    st.info(f"Limpando arquivo temporário do ícone: {temp_icon_path_for_cleanup}")
                    os.remove(temp_icon_path_for_cleanup)
            except Exception as e:
                st.warning(f"Erro ao tentar limpar arquivo temporário do ícone: {str(e)}. Por favor, verifique os logs.")


def render_user_management_page():
    st.title("Gerenciamento de Usuários")

    if st.session_state.role != "admin":
        st.warning("Você não tem permissão para acessar esta página.")
        return

    st.subheader("Adicionar Novo Usuário")
    with st.form("add_user_form", key="add_user_form_key"): # Adicionei key
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
    st.dataframe(df_users, use_container_width=True) # use_container_width para melhor visualização

if choice == "Diário de Obra":
    render_diario_obra_page()
elif choice == "Gerenciamento de Usuários":
    render_user_management_page()
