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
from reportlab.platypus.flowables import Spacer
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


# ✅ FUNÇÕES DE AUTENTICAÇÃO
conn = sqlite3.connect('users.db')
c = conn.cursor()

def create_usertable():
    c.execute('CREATE TABLE IF NOT EXISTS userstable(username TEXT,password TEXT,role TEXT)')

def add_userdata(username,password,role):
    c.execute('INSERT INTO userstable(username,password,role) VALUES (?,?,?)',(username,password,role))
    conn.commit()

def login_user(username,password):
    c.execute('SELECT * FROM userstable WHERE username =? AND password = ?',(username,password))
    data = c.fetchall()
    if data:
        return True, data[0][2] # Retorna True e a role
    return False, None

def view_all_users():
    c.execute('SELECT * FROM userstable')
    data = c.fetchall()
    return data

def make_hashes(password):
    return hashlib.sha256(str.encode(password)).hexdigest()

def check_hashes(password,hashed_text):
    if make_hashes(password) == hashed_text:
        return True
    return False

# ✅ FUNÇÕES DE GOOGLE DRIVE
@st.cache_resource
def get_drive_service():
    try:
        creds_dict = dict(st.secrets["google_service_account"])
        creds = service_account.Credentials.from_service_account_info(
            creds_dict, scopes=["https://www.googleapis.com/auth/drive"]
        )
        return build("drive", "v3", credentials=creds)
    except KeyError:
        st.error("Erro: Credenciais da Service Account do Google Drive não encontradas. Por favor, verifique se 'google_service_account' está configurado em seu arquivo .streamlit/secrets.toml (ou no painel de segredos do Streamlit Cloud).")
        st.stop()
    except Exception as e:
        st.error(f"Erro ao inicializar o serviço Google Drive: {e}")
        st.stop()


def create_drive_folder_if_not_exists(service, parent_folder_id, folder_name):
    query = f"'{parent_folder_id}' in parents and mimeType='application/vnd.google-apps.folder' and name='{folder_name}' and trashed=false"
    results = service.files().list(q=query, spaces="drive", fields="files(id, name)").execute()
    items = results.get("files", [])
    if items:
        return items[0]["id"]
    else:
        file_metadata = {
            "name": folder_name,
            "mimeType": "application/vnd.google-apps.folder",
            "parents": [parent_folder_id],
        }
        folder = service.files().create(body=file_metadata, fields="id").execute()
        return folder.get("id")

def upload_file_to_drive(service, parent_folder_id, file_name, file_content, mime_type):
    file_metadata = {"name": file_name, "parents": [parent_folder_id]}
    media = MediaIoBaseUpload(io.BytesIO(file_content), mimetype=mime_type, resumable=True)
    file = (
        service.files()
        .create(body=file_metadata, media_body=media, fields="id")
        .execute()
    )
    return file.get("id")

@st.cache_data(ttl=3600) # Cache para evitar recarregar toda vez
def load_data_from_drive(folder_id, file_name):
    service = get_drive_service()
    query = f"'{folder_id}' in parents and name='{file_name}' and trashed=false"
    results = service.files().list(q=query, spaces='drive', fields='files(id)').execute()
    items = results.get('files', [])

    if not items:
        st.warning(f"Arquivo '{file_name}' não encontrado na pasta do Google Drive. Criando um DataFrame vazio.")
        if "obras.csv" in file_name:
            return pd.DataFrame(columns=["Obra"]) # Coluna correta esperada
        elif "contratos.csv" in file_name:
            return pd.DataFrame(columns=["Contrato"]) # Coluna correta esperada
        elif "colaboradores.csv" in file_name:
            return pd.DataFrame(columns=["Nome", "Função"])
        else:
            return pd.DataFrame() # Retorna DataFrame vazio para outros casos

    file_id = items[0]['id']
    request = service.files().get_media(fileId=file_id)
    file_content = io.BytesIO(request.execute())
    return pd.read_csv(file_content)

# Função para enviar e-mail
def send_email(subject, body, to_email, attachments=None):
    try:
        yag = yagmail.SMTP(user=st.secrets["email"]["user"], password=st.secrets["email"]["password"])
        yag.send(to=to_email, subject=subject, contents=body, attachments=attachments)
        return True
    except KeyError:
        st.error("Erro de configuração de e-mail: Verifique se 'email.user' e 'email.password' estão configurados em seus segredos.")
        return False
    except Exception as e:
        # Captura erros de rede (gaierror) e outros erros de conexão/autenticação
        error_message = f"Erro ao enviar e-mail: {e}"
        if "gaierror" in str(e).lower():
            error_message += "\nCausa provável: Problema de conexão à internet ou configuração de DNS."
        elif "authentication failed" in str(e).lower() or "password" in str(e).lower() or "authorization" in str(e).lower():
             error_message += "\nCausa provável: Falha na autenticação. Se estiver usando Gmail, certifique-se de que a Verificação em Duas Etapas está ativada e você está usando uma Senha de Aplicativo (App Password)."
        st.error(error_message)
        return False

# Função para carregar imagem como base64 (para o CSS do login)
def get_img_as_base64(file_path):
    try:
        with open(file_path, "rb") as f:
            return base64.b64encode(f.read()).decode()
    except FileNotFoundError:
        st.error(f"Erro: Imagem '{file_path}' não encontrada. Verifique o caminho.")
        return ""
    except Exception as e:
        st.error(f"Erro ao carregar imagem '{file_path}': {e}")
        return ""

# Função para limpar arquivos temporários de ícones (chamada no main)
def clear_icon_temp_file(icon_path):
    if icon_path and os.path.exists(icon_path) and "streamlit_app_temp" in icon_path:
        try:
            os.remove(icon_path)
        except Exception:
            pass # Ignora erros na limpeza

# Função para gerar o PDF
def generate_pdf(data_form, efetivo_lista, output_pdf_path, temp_image_paths, service, folder_id):
    c = canvas.Canvas(output_pdf_path, pagesize=A4)
    width, height = A4

    # Carregar logo para o PDF e redimensionar
    try:
        logo_image = ImageReader(LOGO_PDF_PATH)
        logo_width, logo_height = logo_image.getSize()
        aspect_ratio = logo_height / logo_width
        new_logo_width = 100
        new_logo_height = new_logo_width * aspect_ratio
        c.drawImage(logo_image, 50, height - new_logo_height - 30, width=new_logo_width, height=new_logo_height)
    except Exception as e:
        st.warning(f"Erro ao carregar logo do PDF '{LOGO_PDF_PATH}': {e}. O PDF será gerado sem a logo.")

    # Título
    c.setFont("Helvetica-Bold", 18)
    c.drawCentredString(width / 2, height - 50, "Relatório Diário de Obra")

    # Linha separadora
    c.setStrokeColor(HexColor("#0F2A4D")) # Cor azul marinho
    c.line(50, height - 70, width - 50, height - 70)

    # Estilos de parágrafo
    styles = getSampleStyleSheet()
    normal_style = styles['Normal']
    bold_style = ParagraphStyle('BoldStyle', parent=normal_style, fontName='Helvetica-Bold')

    y_pos = height - 100 # Posição inicial para o conteúdo

    def draw_section_title(canvas_obj, text, y, font_size=12):
        canvas_obj.setFont("Helvetica-Bold", font_size)
        canvas_obj.drawString(50, y, text)
        canvas_obj.setFont("Helvetica", 10) # Reset para normal
        return y - 15

    # 1. DADOS GERAIS DA OBRA
    y_pos = draw_section_title(c, "1. Dados Gerais da Obra", y_pos)
    c.drawString(50, y_pos, f"Obra: {data_form['Obra']}")
    y_pos -= 12
    c.drawString(50, y_pos, f"Local: {data_form['Local']}")
    y_pos -= 12
    c.drawString(50, y_pos, f"Data: {data_form['Data']}")
    y_pos -= 12
    c.drawString(50, y_pos, f"Contrato: {data_form['Contrato']}")
    y_pos -= 12
    c.drawString(50, y_pos, f"Condições do dia: {data_form['Clima']}")
    y_pos -= 20

    # Máquinas e equipamentos
    y_pos = draw_section_title(c, "Máquinas e Equipamentos Utilizados:", y_pos)
    maquinas_paragraph = Paragraph(data_form['Maquinas'], normal_style)
    maquinas_paragraph.wrapOn(c, width - 100, height)
    maquinas_paragraph.drawOn(c, 50, y_pos - maquinas_paragraph.height)
    y_pos -= maquinas_paragraph.height + 10

    # Serviços executados
    y_pos = draw_section_title(c, "Serviços Executados no Dia:", y_pos)
    servicos_paragraph = Paragraph(data_form['Servicos'], normal_style)
    servicos_paragraph.wrapOn(c, width - 100, height)
    servicos_paragraph.drawOn(c, 50, y_pos - servicos_paragraph.height)
    y_pos -= servicos_paragraph.height + 20

    # 2. EFETIVO DE PESSOAL
    y_pos = draw_section_title(c, "2. Efetivo de Pessoal", y_pos)
    if efetivo_lista:
        # Preparar dados para a tabela
        table_data = [["Nome", "Função", "Entrada", "Saída"]]
        for colab in efetivo_lista:
            table_data.append([colab["Nome"], colab["Função"], colab["Entrada"], colab["Saída"]])

        table = Table(table_data, colWidths=[150, 150, 70, 70])
        table.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,0), HexColor("#0F2A4D")), # Cabeçalho azul
            ('TEXTCOLOR', (0,0), (-1,0), white), # Texto branco no cabeçalho
            ('ALIGN', (0,0), (-1,-1), 'LEFT'),
            ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
            ('BOTTOMPADDING', (0,0), (-1,0), 12),
            ('BACKGROUND', (0,1), (-1,-1), lightgrey), # Fundo cinza claro para as linhas
            ('GRID', (0,0), (-1,-1), 1, HexColor("#D3D3D3")), # Bordas da tabela
            ('LEFTPADDING', (0,0), (-1,-1), 6),
            ('RIGHTPADDING', (0,0), (-1,-1), 6),
            ('TOPPADDING', (0,0), (-1,-1), 6),
            ('BOTTOMPADDING', (0,0), (-1,-1), 6),
        ]))
        
        table_height = table.wrapOn(c, width - 100, height)[1]
        if y_pos - table_height < 50: # Se a tabela não couber, cria nova página
            c.showPage()
            y_pos = height - 50 # Reinicia y_pos na nova página
            # Título na nova página
            c.setFont("Helvetica-Bold", 18)
            c.drawCentredString(width / 2, height - 50, "Relatório Diário de Obra (continuação)")
            c.setFont("Helvetica", 10)
        
        table.drawOn(c, 50, y_pos - table_height)
        y_pos -= table_height + 20
    else:
        c.drawString(50, y_pos, "Nenhum colaborador registrado para o dia.")
        y_pos -= 20


    # 3. INFORMAÇÕES ADICIONAIS
    y_pos = draw_section_title(c, "3. Informações Adicionais", y_pos)
    ocorrencias_paragraph = Paragraph(data_form['Ocorrencias'], normal_style)
    ocorrencias_paragraph.wrapOn(c, width - 100, height)
    ocorrencias_paragraph.drawOn(c, 50, y_pos - ocorrencias_paragraph.height)
    y_pos -= ocorrencias_paragraph.height + 10

    c.drawString(50, y_pos, f"Responsável pela Empresa: {data_form['Nome da Empresa']}")
    y_pos -= 12
    c.drawString(50, y_pos, f"Nome da Fiscalização: {data_form['Nome da Fiscalizacao']}")
    y_pos -= 20

    # Fotos (se houver)
    if temp_image_paths:
        y_pos = draw_section_title(c, "Fotos do Serviço:", y_pos)
        current_x = 50
        max_img_width = (width - 100) / 2 - 10 # Duas colunas, com 10px de espaçamento
        
        for i, img_path in enumerate(temp_image_paths):
            try:
                img_reader = ImageReader(img_path)
                img_width, img_height = img_reader.getSize()
                aspect_ratio = img_height / img_width
                
                # Ajustar altura para manter proporção e caber na largura máxima
                new_img_width = max_img_width
                new_img_height = new_img_width * aspect_ratio

                if new_img_height > 150: # Limitar altura para não ocupar demais
                    new_img_height = 150
                    new_img_width = new_img_height / aspect_ratio
                
                # Verificar se a imagem cabe na página atual
                if y_pos - new_img_height - 30 < 50: # Se não couber, cria nova página (deixe espaço para texto e margem)
                    c.showPage()
                    y_pos = height - 50 # Reinicia y_pos na nova página
                    current_x = 50 # Reinicia X para a primeira coluna
                    y_pos = draw_section_title(c, "Fotos do Serviço (continuação):", y_pos)

                c.drawImage(img_reader, current_x, y_pos - new_img_height, width=new_img_width, height=new_img_height)
                c.drawString(current_x, y_pos - new_img_height - 15, f"Foto {i+1}")
                
                current_x += new_img_width + 20 # Mover para a próxima coluna ou para o início da linha
                if current_x + max_img_width > width - 50: # Se não houver espaço para outra imagem na linha
                    current_x = 50 # Voltar para a primeira coluna
                    y_pos -= new_img_height + 30 # Mover para a próxima linha de imagens
                else: # Se houver espaço para outra na mesma linha, apenas diminua o y_pos o suficiente
                    y_pos_after_img = y_pos - new_img_height - 30
                    if y_pos_after_img < 50: # Se a próxima imagem da mesma linha estourar a página, force nova linha
                        current_x = 50
                        y_pos -= new_img_height + 30
                    # Senão, y_pos não precisa descer para a próxima imagem da mesma linha
            except Exception as e:
                st.warning(f"Não foi possível incorporar a foto '{os.path.basename(img_path)}' ao PDF: {e}")
            
            # Garante que y_pos avance para a próxima linha de conteúdo após todas as imagens
            y_pos -= new_img_height + 30 # Ajuste o espaçamento conforme necessário

    c.save() # Salva o PDF
    
    # Limpa arquivos temporários de imagem após o uso
    for p in temp_image_paths:
        if os.path.exists(p):
            os.remove(p)


# ✅ PÁGINA PRINCIPAL DO RELATÓRIO DE OBRA
def render_diario_obra_page():
    # 1. INICIALIZAÇÃO OBRIGATÓRIA (no início da função)
    if 'num_colabs' not in st.session_state:
        st.session_state.num_colabs = 0 # Inicia com 0 ou outro valor desejado, 2 era um valor padrão anterior

    # [Mantenha todo o código de carregamento de dados...]
    # Carrega dados do Google Drive
    obras_df = load_data_from_drive(DRIVE_FOLDER_ID, "obras.csv")
    contratos_df = load_data_from_drive(DRIVE_FOLDER_ID, "contratos.csv")
    colab_df = load_data_from_drive(DRIVE_FOLDER_ID, "colaboradores.csv")

    # Garante que os DataFrames não estão vazios antes de tentar acessá-los e usa as colunas corretas
    if obras_df.empty:
        st.warning("Não foi possível carregar o arquivo 'obras.csv' do Google Drive. Verifique a pasta e o arquivo.")
        obras_lista = [""]
    else:
        obras_lista = [""] + obras_df["Obra"].drop_duplicates().sort_values().tolist()
    
    if contratos_df.empty:
        st.warning("Não foi possível carregar o arquivo 'contratos.csv' do Google Drive. Verifique a pasta e o arquivo.")
        contratos_lista = [""]
    else:
        contratos_lista = [""] + contratos_df["Contrato"].drop_duplicates().sort_values().tolist()

    if colab_df.empty:
        st.warning("Não foi possível carregar o arquivo 'colaboradores.csv' do Google Drive. Verifique a pasta e o arquivo.")
        colaboradores_lista = []
    else:
        colaboradores_lista = colab_df["Nome"].drop_duplicates().sort_values().tolist()


    st.title("Relatório Diário de Obra - RDV Engenharia")

    # 2. SLIDER FORA DO FORMULÁRIO (para controle dinâmico)
    st.subheader("Efetivo de Pessoal")
    max_colabs_slider = len(colaboradores_lista) if colaboradores_lista else 20
    
    # O slider controla o número de colaboradores e usa session_state para persistência
    # O valor retornado pelo slider é imediatamente salvo no session_state
    qtd_colaboradores = st.slider(
        "Quantos colaboradores hoje?",
        min_value=0,
        max_value=max_colabs_slider,
        value=st.session_state.num_colabs, # Usa o valor do session_state
        key="slider_colabs" # Key do widget
    )
    st.session_state.num_colabs = qtd_colaboradores # Atualiza o session_state com o valor do slider

    st.markdown("---") # Separador antes do formulário principal

    # 3. FORMULÁRIO PRINCIPAL
    with st.form(key="relatorio_form", clear_on_submit=False):
        # 1. DADOS GERAIS DA OBRA (Mantido dentro do formulário)
        st.subheader("Dados Gerais da Obra")
        # Garanta que as chaves de cada widget sejam únicas
        obra = st.selectbox("Obra", obras_lista, key="form_obra_select")
        local = st.text_input("Local", key="form_local_input")
        data = st.date_input("Data", value=datetime.today(), key="form_data_input")
        contrato = st.selectbox("Contrato", contratos_lista, key="form_contrato_select")
        clima = st.selectbox("Condições do dia", ["Bom", "Chuva", "Garoa", "Impraticável", "Feriado", "Guarda"], key="form_clima_select")
        maquinas = st.text_area("Máquinas e equipamentos utilizados", key="form_maquinas_text")
        servicos = st.text_area("Serviços executados no dia", key="form_servicos_text")

        st.markdown("---") # Linha separadora para visual
        
        # 4. CAMPOS DINÂMICOS DOS COLABORADORES (DENTRO DO FORM)
        efetivo_lista = []
        for i in range(st.session_state.num_colabs): # Usa o valor do session_state
            with st.expander(f"Colaborador {i+1}", expanded=True):
                nome = st.selectbox("Nome", [""] + colaboradores_lista, key=f"form_colab_nome_{i}")
                funcao = ""
                # Garante que colab_df não está vazio antes de tentar acessar valores
                if nome and not colab_df.empty and nome in colab_df["Nome"].values:
                    funcao = colab_df.loc[colab_df["Nome"] == nome, "Função"].values[0]
                funcao = st.text_input("Função", value=funcao, key=f"form_colab_funcao_{i}")
                col1, col2 = st.columns(2)
                with col1:
                    entrada = st.time_input("Entrada", value=datetime.strptime("08:00", "%H:%M").time(), key=f"form_colab_entrada_{i}")
                with col2:
                    saida = st.time_input("Saída", value=datetime.strptime("17:00", "%H:%M").time(), key=f"form_colab_saida_{i}")
                efetivo_lista.append({"Nome": nome, "Função": funcao, "Entrada": entrada.strftime("%H:%M"), "Saída": saida.strftime("%H:%M")})

        st.markdown("---") # Linha separadora

        # INFORMAÇÕES ADICIONAIS (Mantido dentro do formulário)
        st.subheader("Informações Adicionais")
        ocorrencias = st.text_area("Ocorrências", key="form_ocorrencias_text")
        nome_empresa = st.text_input("Responsável pela empresa", key="form_responsavel_empresa_input")
        nome_fiscal = st.text_input("Nome da fiscalização", key="form_fiscalizacao_input")
        fotos = st.file_uploader("Fotos do serviço", accept_multiple_files=True, type=["png", "jpg", "jpeg"], key="form_fotos_uploader")

        # 5. BOTÃO DE SUBMIT (ÚLTIMO ELEMENTO DO FORM)
        submitted = st.form_submit_button("✅ Salvar e Gerar Relatório", key="form_submit_button_main") # Renomeei a key para ser mais específica

    # Adicione este debug temporário para verificar:
    # st.write("Estado atual do session_state:", st.session_state) # Descomente para debug

    # 6. LÓGICA DE PROCESSAMENTO (FORA DO FORM)
    if submitted:
        # Coleta de dados do formulário
        report_data = {
            "Obra": obra,
            "Local": local,
            "Data": data.strftime("%d/%m/%Y"),
            "Contrato": contrato,
            "Clima": clima,
            "Maquinas": maquinas,
            "Servicos": servicos,
            "Ocorrencias": ocorrencias,
            "Nome da Empresa": nome_empresa,
            "Nome da Fiscalizacao": nome_fiscal,
        }

        # Cria pasta diária no Drive
        service = get_drive_service()
        today_folder_name = datetime.now().strftime("%Y-%m-%d")
        daily_folder_id = create_drive_folder_if_not_exists(service, DRIVE_FOLDER_ID, today_folder_name)

        # Geração do PDF
        pdf_file_name = f"RDV_{obra.replace(' ', '_')}_{data.strftime('%Y%m%d')}.pdf"
        output_pdf_path = os.path.join(tempfile.gettempdir(), pdf_file_name) # Salva PDF em temp dir

        temp_image_paths = []
        if fotos:
            for uploaded_file in fotos:
                # Salva cada imagem temporariamente para o PDF
                image_bytes = uploaded_file.read()
                temp_img_path = os.path.join(tempfile.gettempdir(), uploaded_file.name)
                with open(temp_img_path, "wb") as f:
                    f.write(image_bytes)
                temp_image_paths.append(temp_img_path)

        generate_pdf(report_data, efetivo_lista, output_pdf_path, temp_image_paths, service, daily_folder_id)

        # Upload do PDF para o Google Drive
        with open(output_pdf_path, "rb") as f:
            pdf_content = f.read()
        
        try:
            uploaded_file_id = upload_file_to_drive(service, daily_folder_id, pdf_file_name, pdf_content, "application/pdf")
            st.success(f"Relatório '{pdf_file_name}' salvo com sucesso no Google Drive! ID: {uploaded_file_id}")
            # Limpa o arquivo PDF temporário
            if os.path.exists(output_pdf_path):
                os.remove(output_pdf_path)
        except HttpError as e:
            st.error(f"Erro ao fazer upload do PDF para o Google Drive: {e}")
        except Exception as e:
            st.error(f"Erro inesperado no upload do PDF: {e}")

        # Opcional: Adicionar um campo para o email de destino no formulário se for enviar email
        # email_destino = "seu_email@example.com" # Substitua pelo email de destino
        # if send_email(f"Relatório Diário de Obra - {obra} ({data.strftime('%d/%m/%Y')})", "Segue em anexo o relatório diário de obra.", email_destino, attachments=[output_pdf_path]):
        #     st.success("E-mail enviado com sucesso!")
        # else:
        #     st.error("Falha ao enviar e-mail.")

        # Opcional: st.rerun() para limpar o formulário e resetar o estado
        # st.rerun()

# ✅ ESTRUTURA PRINCIPAL DO APLICATIVO
def main():
    # Inicialização do session_state
    if "logged_in" not in st.session_state:
        st.session_state["logged_in"] = False
        st.session_state["username"] = None
        st.session_state["role"] = None
        st.session_state["page"] = "home" # Página inicial padrão

    # Configuração da página Streamlit (apenas uma vez)
    icon_path_for_set_page_config = LOGO_ICON_PATH
    if not os.path.exists(icon_path_for_set_page_config):
        icon_path_for_set_page_config = None # Fallback se o ícone não for encontrado

    st.set_page_config(
        page_title="RDV Engenharia",
        page_icon=icon_path_for_set_page_config,
        layout="centered",
        initial_sidebar_state="auto"
    )
    
    # Adiciona CSS global
    st.markdown("""
        <style>
        /* Esconde o menu 'hamburger' e o 'Made with Streamlit' */
        #MainMenu {visibility: hidden;}
        footer {visibility: hidden;}
        .stDeployButton {display: none;} /* Esconde o botão de deploy no Streamlit Cloud */

        /* Adiciona espaçamento superior ao conteúdo principal para a logo e título */
        .block-container {
            padding-top: 1rem;
            padding-bottom: 1rem;
            padding-left: 1rem;
            padding-right: 1rem;
        }
        </style>
        """, unsafe_allow_html=True)

    # Cria a tabela de usuários se não existir
    create_usertable()

    # Tenta adicionar um usuário admin padrão se a tabela estiver vazia
    # Descomente e rode uma vez se precisar criar o usuário inicial
    # if not view_all_users():
    #     add_userdata("admin", make_hashes("admin123"), "admin")
    #     st.success("Usuário 'admin' padrão criado com senha 'admin123'. Por favor, altere!")

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

        with st.form(key="login_form"):
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

    else: # Usuário está logado
        # Sidebar de navegação
        st.sidebar.title(f"Bem-vindo, {st.session_state.username}!")
        if st.session_state.role == "admin":
            st.sidebar.button("Gerenciamento de Usuários", on_click=lambda: st.session_state.update(page="user_management"))
        st.sidebar.button("Diário de Obra", on_click=lambda: st.session_state.update(page="diario_obra"))
        st.sidebar.button("Sair", on_click=lambda: st.session_state.update(logged_in=False, username=None, role=None, page="home"))
        
        # Renderiza a página selecionada
        if st.session_state.page == "diario_obra":
            render_diario_obra_page()
        elif st.session_state.page == "user_management" and st.session_state.role == "admin":
            render_user_management_page()
        else: # Página padrão após login ou se a página selecionada não existe/não tem permissão
            st.info("Selecione uma opção no menu lateral.")

    # Tenta limpar o arquivo temporário do ícone da página
    if "icon_temp_file_path" in st.session_state:
        clear_icon_temp_file(st.session_state.icon_temp_file_path)
        del st.session_state.icon_temp_file_path

# Função de gerenciamento de usuários (deve ser definida no escopo global ou antes de main())
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


if __name__ == "__main__":
    main()
