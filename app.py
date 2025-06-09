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

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

# ✅ CONFIGURAÇÃO STREAMLIT
st.set_page_config(page_title="Diário de Obra - RDV", layout="centered")

# ✅ CONSTANTE - ID DA PASTA NO DRIVE
DRIVE_FOLDER_ID = "1BUgZRcBrKksC3eUytoJ5mv_nhMRdAv1d"

# ✅ SERVIÇO DO GOOGLE DRIVE
@st.cache_resource(show_spinner=False)
def get_drive_service():
    creds_dict = dict(st.secrets["google_service_account"])
    creds = service_account.Credentials.from_service_account_info(
        creds_dict, scopes=["https://www.googleapis.com/auth/drive"]
    )
    return build("drive", "v3", credentials=creds, static_discovery=False)

# ✅ FUNÇÃO DE UPLOAD REFORÇADA

def upload_para_drive(pdf_buffer, nome_arquivo):
    try:
        service = get_drive_service()
        pdf_buffer.seek(0)

        file_metadata = {
            'name': nome_arquivo,
            'parents': [DRIVE_FOLDER_ID]
        }

        media = MediaIoBaseUpload(pdf_buffer, mimetype='application/pdf', resumable=True)

        arquivo = service.files().create(
            body=file_metadata,
            media_body=media,
            fields='id',
            supportsAllDrives=True
        ).execute(timeout=30)

        return arquivo.get("id")
    except Exception as e:
        st.error(f"Erro detalhado no upload: {str(e)}")
        return None

# ✅ GERAÇÃO DE PDF

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
        c.drawString(margem, y, f"{campo}: {registro[campo]}")
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
            c.drawString(margem, y, f"📷 Foto: {Path(foto_path).name}")
            img = PILImage.open(foto_path)
            img.thumbnail((500, 500))
            c.drawImage(ImageReader(img), margem, y - 500, width=500, height=300)
        except:
            continue

    c.save()
    buffer.seek(0)
    return buffer

# ✅ LEITURA DE DADOS CSV
colab_df = pd.read_csv("colaboradores.csv")
colaboradores_lista = colab_df["Nome"].tolist()
obras_df = pd.read_csv("obras.csv")
obras_lista = [""] + obras_df["Nome"].tolist()
contratos_df = pd.read_csv("contratos.csv")
contratos_lista = [""] + contratos_df["Nome"].tolist()

# ✅ INTERFACE
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
        funcao_sugerida = colab_df.loc[colab_df["Nome"] == nome, "Função"].values[0]
        funcao = st.text_input("Função", value=funcao_sugerida, key=f"funcao_{i}")
        ent = st.time_input("Entrada", key=f"ent_{i}")
        sai = st.time_input("Saída", key=f"sai_{i}")
        efetivo_lista.append({"Nome": nome, "Função": funcao, "Entrada": ent.strftime("%H:%M"), "Saída": sai.strftime("%H:%M")})

ocorrencias = st.text_area("Ocorrências")
nome_empresa = st.text_input("Responsável pela empresa")
nome_fiscal = st.text_input("Nome da fiscalização")
fotos = st.file_uploader("Fotos do serviço", accept_multiple_files=True, type=["png", "jpg", "jpeg"])

# ✅ AÇÃO PRINCIPAL
if st.button("💾 Salvar e Gerar Relatório"):
    with st.spinner("Preparando relatório..."):
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

        fotos_dir = Path("temp_fotos")
        fotos_dir.mkdir(exist_ok=True)
        fotos_paths = []

        try:
            for i, foto in enumerate(fotos):
                if foto is None:
                    continue
                nome_foto = f"{obra}_{data.strftime('%Y-%m-%d')}_foto{i+1}.jpg".replace(" ", "_")
                caminho_foto = fotos_dir / nome_foto
                with open(caminho_foto, "wb") as f:
                    f.write(foto.getbuffer())
                fotos_paths.append(str(caminho_foto))

            pdf_download = gerar_pdf(registro, fotos_paths)
            pdf_upload = gerar_pdf(registro, fotos_paths)
            nome_pdf = f"Diario_{obra.replace(' ', '_')}_{data.strftime('%Y-%m-%d')}.pdf"

            st.download_button("📥 Baixar PDF", data=pdf_download, file_name=nome_pdf, mime="application/pdf")

            with st.spinner("Salvando no Google Drive..."):
                drive_id = upload_para_drive(pdf_upload, nome_pdf)
                if not drive_id:
                    st.error("Falha ao salvar no Google Drive")
                    st.stop()

                st.success(f"✅ PDF salvo no Drive! ID: {drive_id}")
                st.markdown(f"[📂 Abrir no Google Drive](https://drive.google.com/file/d/{drive_id}/view)")

            with st.spinner("Enviando e-mail..."):
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

Atenciosamente,  
Sistema Diário de Obra - RDV Engenharia
"""
                    yag.send(
                        to=["comercial@rdvengenharia.com.br", "administrativo@rdvengenharia.com.br"],
                        subject=assunto,
                        contents=corpo
                    )
                    st.success("📨 E-mail enviado com sucesso!")
                except Exception as e:
                    st.error(f"Erro ao enviar e-mail: {str(e)}")

        finally:
            for foto_path in fotos_paths:
                try:
                    os.remove(foto_path)
                except:
                    pass
