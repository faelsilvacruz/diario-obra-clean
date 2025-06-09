# ✅ IMPORTS
import streamlit as st
import pandas as pd
from datetime import datetime
from pathlib import Path
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.platypus import Paragraph
from reportlab.lib.units import mm
from reportlab.lib.colors import HexColor
from PIL import Image as PILImage
import json
import io
import os
import yagmail
import traceback

# 📁 Google Drive
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
from google.api_core import retry
from google.auth import transport

# ✅ CONFIGURAÇÃO
st.set_page_config(page_title="Diário de Obra - RDV", layout="centered")
DRIVE_FOLDER_ID = "1BUgZRcBrKksC3eUytoJ5mv_nhMRdAv1d"

# ✅ Google Drive - Criação do serviço robusto
def criar_servico_drive():
    try:
        creds_dict = dict(st.secrets["google_service_account"])
        creds = service_account.Credentials.from_service_account_info(
            creds_dict,
            scopes=["https://www.googleapis.com/auth/drive"]
        )
        http = transport.requests.AuthorizedSession(creds)
        return build("drive", "v3", credentials=creds, static_discovery=False, requestBuilder=http)
    except Exception as e:
        st.error(f"Erro ao criar serviço do Google Drive: {str(e)}")
        return None

# ✅ Upload robusto com retry
@retry.Retry(
    initial=1.0,
    maximum=10.0,
    multiplier=2.0,
    deadline=30.0,
    predicate=retry.if_exception_type(Exception)
)
def upload_para_drive_robusto(pdf_buffer, nome_arquivo):
    try:
        service = criar_servico_drive()
        if not service:
            return None

        # Verifica se a pasta existe
        try:
            service.files().get(fileId=DRIVE_FOLDER_ID, fields='id', supportsAllDrives=True).execute()
        except Exception as e:
            st.error(f"Pasta do Google Drive não acessível: {str(e)}")
            return None

        pdf_buffer.seek(0)
        media = MediaIoBaseUpload(pdf_buffer, mimetype='application/pdf', resumable=True)
        metadata = {"name": nome_arquivo, "parents": [DRIVE_FOLDER_ID], "supportsAllDrives": True}

        request = service.files().create(body=metadata, media_body=media, fields="id", supportsAllDrives=True)
        response = None
        while response is None:
            status, response = request.next_chunk()
            if status:
                st.info(f"Progresso: {int(status.progress() * 100)}%")

        return response.get("id")

    except Exception as e:
        st.error(f"Erro no upload: {str(e)}")
        raise

# ✅ PDF

def gerar_pdf(registro, fotos_paths):
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4
    y = height - 30

    c.setFont("Helvetica-Bold", 16)
    c.setFillColor(HexColor("#0F2A4D"))
    c.drawCentredString(width / 2, y, "Diário de Obra - RDV Engenharia")
    y -= 40

    c.setFont("Helvetica", 12)
    c.setFillColor("black")
    for campo in ["Obra", "Local", "Data", "Contrato", "Clima", "Máquinas", "Serviços"]:
        c.drawString(30, y, f"{campo}: {registro[campo]}")
        y -= 20

    c.drawString(30, y, "Efetivo:")
    y -= 20
    for item in json.loads(registro["Efetivo"]):
        c.drawString(40, y, f"- {item['Nome']} ({item['Função']}): {item['Entrada']} - {item['Saída']}")
        y -= 15

    y -= 10
    c.drawString(30, y, f"Ocorrências: {registro['Ocorrências']}")
    y -= 20
    c.drawString(30, y, f"Responsável: {registro['Responsável Empresa']}")
    if registro['Fiscalização']:
        y -= 20
        c.drawString(30, y, f"Fiscalização: {registro['Fiscalização']}")

    for foto_path in fotos_paths:
        try:
            c.showPage()
            y = height - 30
            c.drawString(30, y, f"Foto: {Path(foto_path).name}")
            img = PILImage.open(foto_path)
            img.thumbnail((500, 500))
            c.drawImage(ImageReader(img), 30, y - 500, width=500, height=300)
        except:
            continue

    c.save()
    buffer.seek(0)
    return buffer

# ✅ UI e dados
colab_df = pd.read_csv("colaboradores.csv")
colaboradores_lista = colab_df["Nome"].tolist()
obras_df = pd.read_csv("obras.csv")
obras_lista = [""] + obras_df["Nome"].tolist()
contratos_df = pd.read_csv("contratos.csv")
contratos_lista = [""] + contratos_df["Nome"].tolist()

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
        nome = st.selectbox("Nome", colaboradores_lista, key=f"nome_{i}")
        funcao = colab_df.loc[colab_df["Nome"] == nome, "Função"].values[0]
        ent = st.time_input("Entrada", key=f"ent_{i}")
        sai = st.time_input("Saída", key=f"sai_{i}")
        efetivo_lista.append({"Nome": nome, "Função": funcao, "Entrada": ent.strftime("%H:%M"), "Saída": sai.strftime("%H:%M")})

ocorrencias = st.text_area("Ocorrências")
nome_empresa = st.text_input("Responsável pela empresa")
nome_fiscal = st.text_input("Nome da fiscalização")
fotos = st.file_uploader("Fotos do serviço", accept_multiple_files=True, type=["png", "jpg", "jpeg"])

# ✅ PROCESSAR ENVIO
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
    pdf_download = gerar_pdf(registro, fotos_paths)
    st.download_button("📥 Baixar PDF", data=pdf_download, file_name=nome_pdf, mime="application/pdf")

    try:
        drive_id = upload_para_drive_robusto(gerar_pdf(registro, fotos_paths), nome_pdf)
        if drive_id:
            st.success("✅ PDF salvo com sucesso no Google Drive!")
            st.markdown(f"[📂 Abrir no Google Drive](https://drive.google.com/file/d/{drive_id}/view)")

            try:
                yag = yagmail.SMTP(st.secrets["email"]["user"], st.secrets["email"]["password"])
                assunto = f"📋 Novo Diário de Obra - {obra} ({data.strftime('%d/%m/%Y')})"
                corpo = f"""
Olá, equipe RDV!

O diário de obra foi preenchido com sucesso.

📍 Obra: {obra}
📅 Data: {data.strftime('%d/%m/%Y')}
📝 Responsável: {nome_empresa}

📎 Acesse o relatório em PDF:
https://drive.google.com/file/d/{drive_id}/view
                """
                yag.send(to=["comercial@rdvengenharia.com.br", "administrativo@rdvengenharia.com.br"], subject=assunto, contents=corpo)
                st.success("📨 E-mail enviado com sucesso!")
            except Exception as e:
                st.warning(f"⚠️ Erro ao enviar e-mail: {str(e)}")
        else:
            st.error("❌ Falha no upload para o Google Drive")
    except Exception as e:
        st.error(f"🚨 Erro inesperado: {str(e)}")
        st.text(traceback.format_exc())
