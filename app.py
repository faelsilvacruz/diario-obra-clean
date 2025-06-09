import streamlit as st
import pandas as pd
import os
import json
import io
import time
import traceback
import logging
from datetime import datetime
from pathlib import Path
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader
from reportlab.lib.colors import HexColor
from PIL import Image as PILImage
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
from googleapiclient.errors import HttpError
import yagmail

# CONFIGURAÇÃO DE LOG
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# INFORMAÇÕES DO APP
st.set_page_config(page_title="Diário de Obra - RDV", layout="centered")

# VERIFICAÇÃO DE AMBIENTE
st.sidebar.subheader("Info do Ambiente")
st.sidebar.json({
    "Arquivos CSV": [f for f in os.listdir('.') if f.endswith('.csv')],
})

# FUNÇÃO ROBUSTA PARA CARREGAR CSV
def carregar_arquivo_csv(nome_arquivo):
    try:
        if not os.path.exists(nome_arquivo):
            raise FileNotFoundError(f"Arquivo {nome_arquivo} não encontrado")
        return pd.read_csv(nome_arquivo)
    except Exception as e:
        logger.error(f"Erro ao carregar {nome_arquivo}: {str(e)}")
        st.error(f"Erro: não foi possível carregar {nome_arquivo}")
        st.stop()

# LEITURA DOS ARQUIVOS
colab_df = carregar_arquivo_csv("colaboradores.csv")
obras_df = carregar_arquivo_csv("obras.csv")
contratos_df = carregar_arquivo_csv("contratos.csv")

colaboradores_lista = colab_df["Nome"].tolist()
obras_lista = [""] + obras_df["Nome"].tolist()
contratos_lista = [""] + contratos_df["Nome"].tolist()

# DRIVE
DRIVE_FOLDER_ID = "1BUgZRcBrKksC3eUytoJ5mv_nhMRdAv1d"
creds = service_account.Credentials.from_service_account_info(
    st.secrets["google_service_account"],
    scopes=["https://www.googleapis.com/auth/drive"]
)

# UPLOAD PARA O GOOGLE DRIVE
def upload_para_drive_seguro(pdf_buffer, nome_arquivo):
    MAX_RETRIES = 3
    WAIT_SECONDS = 2
    for attempt in range(MAX_RETRIES):
        try:
            pdf_buffer.seek(0)
            service = build("drive", "v3", credentials=creds, static_discovery=False)
            media = MediaIoBaseUpload(pdf_buffer, mimetype='application/pdf', resumable=True)
            file_metadata = {
                'name': nome_arquivo,
                'parents': [DRIVE_FOLDER_ID],
                'supportsAllDrives': True
            }
            request = service.files().create(
                body=file_metadata,
                media_body=media,
                fields='id',
                supportsAllDrives=True
            )
            response = None
            while response is None:
                status, response = request.next_chunk()
                if status:
                    logger.info(f"Upload {int(status.progress() * 100)}% completo")
            return response.get('id')
        except HttpError as http_err:
            logger.error(f"Tentativa {attempt + 1} falhou: {http_err}")
            time.sleep(WAIT_SECONDS * (attempt + 1))
        except Exception as e:
            logger.error(f"Erro inesperado: {str(e)}")
            time.sleep(WAIT_SECONDS * (attempt + 1))
    return None

# GERAR PDF
def gerar_pdf(registro, fotos_paths):
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4
    margem = 30
    y = height - margem
    c.setFont("Helvetica-Bold", 16)
    c.setFillColor(HexColor("#0F2A4D"))
    c.drawCentredString(width / 2, y, "Diário de Obra - RDV Engenharia")
    y -= 40
    c.setFont("Helvetica", 12)
    c.setFillColor("black")
    for campo in ["Obra", "Local", "Data", "Contrato", "Clima", "Máquinas", "Serviços"]:
        texto = f"{campo}: {registro[campo]}"
        c.drawString(margem, y, texto)
        y -= 20
    c.drawString(margem, y, "Efetivo de Pessoal:")
    y -= 20
    for item in json.loads(registro["Efetivo"]):
        linha = f"- {item['Nome']} ({item['Função']}): {item['Entrada']} - {item['Saída']}"
        c.drawString(margem + 10, y, linha)
        y -= 15
    y -= 10
    c.drawString(margem, y, f"Ocorrências: {registro['Ocorrências']}")
    y -= 20
    c.drawString(margem, y, f"Responsável Empresa: {registro['Responsável Empresa']}")
    if registro['Fiscalização']:
        y -= 20
        c.drawString(margem, y, f"Fiscalização: {registro['Fiscalização']}")
    for foto_path in fotos_paths:
        try:
            c.showPage()
            y = height - margem
            c.drawString(margem, y, f"Foto: {Path(foto_path).name}")
            img = PILImage.open(foto_path)
            img.thumbnail((500, 500))
            c.drawImage(ImageReader(img), margem, y - 500, width=500, height=300)
        except:
            continue
    c.save()
    buffer.seek(0)
    return buffer

# UI
st.title("📋 Diário de Obra - RDV Engenharia")
obra = st.selectbox("Obra", obras_lista)
local = st.text_input("Local")
data = st.date_input("Data", value=datetime.today())
contrato = st.selectbox("Contrato", contratos_lista)
clima = st.selectbox("Condições do dia", ["Bom", "Chuva", "Garoa", "Impraticável", "Feriado"])
maquinas = st.text_area("Máquinas e equipamentos utilizados")
servicos = st.text_area("Serviços executados no dia")

st.header("Efetivo de Pessoal")
qtd_colaboradores = st.number_input("Quantos colaboradores hoje?", min_value=1, max_value=10, step=1)
efetivo_lista = []
for i in range(qtd_colaboradores):
    with st.expander(f"👷 Colaborador {i+1}"):
        nome = st.selectbox(f"Nome", colaboradores_lista, key=f"nome_{i}")
        funcao_sugerida = colab_df.loc[colab_df["Nome"] == nome, "Função"].values[0]
        funcao = st.text_input("Função", value=funcao_sugerida, key=f"funcao_{i}")
        ent = st.time_input("Entrada", key=f"ent_{i}")
        sai = st.time_input("Saída", key=f"sai_{i}")
        efetivo_lista.append({
            "Nome": nome,
            "Função": funcao,
            "Entrada": ent.strftime("%H:%M"),
            "Saída": sai.strftime("%H:%M")
        })

ocorrencias = st.text_area("Ocorrências")
nome_empresa = st.text_input("Responsável pela empresa")
nome_fiscal = st.text_input("Nome da fiscalização")
fotos = st.file_uploader("Fotos do serviço", accept_multiple_files=True, type=["png", "jpg", "jpeg"])

# GERAR RELATÓRIO
if st.button("💾 Salvar e Gerar Relatório"):
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

    fotos_dir = Path("fotos")
    fotos_dir.mkdir(exist_ok=True)
    fotos_paths = []
    for i, foto in enumerate(fotos):
        nome_foto = f"{obra}_{data.strftime('%Y-%m-%d')}_foto{i+1}.jpg".replace(" ", "_")
        caminho_foto = fotos_dir / nome_foto
        with open(caminho_foto, "wb") as f:
            f.write(foto.getbuffer())
        fotos_paths.append(str(caminho_foto))

    nome_pdf = f"Diario_{obra.replace(' ', '_')}_{data.strftime('%Y-%m-%d')}.pdf"
    pdf = gerar_pdf(registro, fotos_paths)
    st.download_button("📥 Baixar PDF", data=pdf, file_name=nome_pdf, mime="application/pdf")

    with st.spinner("Salvando no Google Drive..."):
        drive_id = upload_para_drive_seguro(io.BytesIO(pdf.getvalue()), nome_pdf)
        if drive_id:
            st.success("✅ PDF salvo com sucesso no Google Drive!")
            st.markdown(f"[📂 Abrir no Google Drive](https://drive.google.com/file/d/{drive_id}/view)")

            # ENVIO DO E-MAIL
            try:
                yag = yagmail.SMTP(
                    st.secrets["email"]["user"],
                    st.secrets["email"]["password"]
                )
                link_drive = f"https://drive.google.com/file/d/{drive_id}/view"
                assunto = f"📋 Novo Diário de Obra - {obra} ({data.strftime('%d/%m/%Y')})"
                corpo = f"""
                Olá, equipe RDV!

                O diário de obra foi preenchido com sucesso.

                📍 Obra: {obra}
                📅 Data: {data.strftime('%d/%m/%Y')}
                📝 Responsável: {nome_empresa}

                📎 Acesse o relatório em PDF:
                {link_drive}

                Atenciosamente,  
                Sistema Diário de Obra - RDV Engenharia
                """
                yag.send(to=["comercial@rdvengenharia.com.br", "administrativo@rdvengenharia.com.br"], subject=assunto, contents=corpo)
                st.success("📨 E-mail enviado com sucesso para a diretoria.")
            except Exception as e:
                st.warning(f"⚠️ Falha ao enviar e-mail: {str(e)}")
        else:
            st.error("❌ Falha ao salvar PDF no Drive")
