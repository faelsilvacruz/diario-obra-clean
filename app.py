
# ✅ IMPORTS
import streamlit as st
import pandas as pd
from datetime import datetime
from pathlib import Path
from PIL import Image as PILImage
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader
from reportlab.lib.colors import HexColor
import os
import io
import json
import yagmail
import tempfile
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

# ✅ CONSTANTES
DRIVE_FOLDER_ID = "1BUgZRcBrKksC3eUytoJ5mv_nhMRdAv1d"

st.set_page_config(page_title="Diário de Obra - RDV", layout="centered")

# ✅ CREDENCIAIS
creds_dict = dict(st.secrets["google_service_account"])
creds = service_account.Credentials.from_service_account_info(
    creds_dict, scopes=["https://www.googleapis.com/auth/drive"]
)

# ✅ CSVs
def carregar_arquivo_csv(nome_arquivo):
    if not os.path.exists(nome_arquivo):
        raise FileNotFoundError(f"Arquivo {nome_arquivo} não encontrado")
    return pd.read_csv(nome_arquivo)

colab_df = carregar_arquivo_csv("colaboradores.csv")
obras_df = carregar_arquivo_csv("obras.csv")
contratos_df = carregar_arquivo_csv("contratos.csv")

colaboradores_lista = colab_df["Nome"].tolist()
obras_lista = [""] + obras_df["Nome"].tolist()
contratos_lista = [""] + contratos_df["Nome"].tolist()

# ✅ FORMULÁRIO
st.title("Relatório Diário de Obra - RDV Engenharia")
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
    with st.expander(f"Colaborador {i+1}"):
        nome = st.selectbox("Nome", colaboradores_lista, key=f"nome_{i}")
        funcao = colab_df.loc[colab_df["Nome"] == nome, "Função"].values[0]
        funcao_input = st.text_input("Função", value=funcao, key=f"funcao_{i}")
        ent = st.time_input("Entrada", key=f"ent_{i}")
        sai = st.time_input("Saída", key=f"sai_{i}")
        efetivo_lista.append({
            "Nome": nome,
            "Função": funcao_input,
            "Entrada": ent.strftime("%H:%M"),
            "Saída": sai.strftime("%H:%M")
        })

ocorrencias = st.text_area("Ocorrências")
nome_empresa = st.text_input("Responsável pela empresa")
nome_fiscal = st.text_input("Nome da fiscalização")
fotos = st.file_uploader("Fotos do serviço", accept_multiple_files=True, type=["png", "jpg", "jpeg"])

# ✅ PROCESSAMENTO DE FOTOS
def processar_fotos(fotos_upload):
    fotos_processadas = []
    with tempfile.TemporaryDirectory() as temp_dir:
        for i, foto in enumerate(fotos_upload):
            try:
                img = PILImage.open(foto)
                img.thumbnail((1200, 1200))
                temp_path = os.path.join(temp_dir, f"temp_foto_{i}.jpg")
                img.save(temp_path, "JPEG", quality=85)
                fotos_processadas.append(temp_path)
            except Exception as e:
                st.warning(f"Erro ao processar foto {i}: {e}")
    return fotos_processadas

# ✅ PDF
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
    y -= 20
    c.drawString(margem, y, f"Fiscalização: {registro['Fiscalização']}")

    for foto_path in fotos_paths:
        c.showPage()
        y = height - margem
        img = PILImage.open(foto_path)
        img.thumbnail((500, 500))
        c.drawString(margem, y, f"Foto: {Path(foto_path).name}")
        c.drawImage(ImageReader(img), margem, y - 300, width=300, height=200)

    c.save()
    buffer.seek(0)
    return buffer

# ✅ UPLOAD
def upload_para_drive_seguro(pdf_buffer, nome_arquivo):
    try:
        pdf_buffer.seek(0)
        service = build("drive", "v3", credentials=creds, static_discovery=False)
        media = MediaIoBaseUpload(pdf_buffer, mimetype='application/pdf')
        file_metadata = {'name': nome_arquivo, 'parents': [DRIVE_FOLDER_ID]}
        file = service.files().create(
            body=file_metadata,
            media_body=media,
            fields='id',
            supportsAllDrives=True
        ).execute()
        return file.get("id")
    except Exception as e:
        st.error(f"Erro ao enviar para o Google Drive: {e}")
        return None

# ✅ EXECUÇÃO FINAL
if st.button("Salvar e Gerar Relatório"):
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

    st.info("Processando imagens...")
    fotos_paths = processar_fotos(fotos) if fotos else []

    st.info("Gerando PDF...")
    nome_pdf = f"Diario_{obra.replace(' ', '_')}_{data.strftime('%Y-%m-%d')}.pdf"
    pdf_buffer = gerar_pdf(registro, fotos_paths)

    st.download_button("Baixar PDF", data=pdf_buffer, file_name=nome_pdf, mime="application/pdf")

    st.info("Enviando para o Google Drive...")
    drive_id = upload_para_drive_seguro(io.BytesIO(pdf_buffer.getvalue()), nome_pdf)
    if drive_id:
        st.success(f"PDF salvo no Drive! ID: {drive_id}")
        st.markdown(f"[Abrir no Google Drive](https://drive.google.com/file/d/{drive_id}/view)")

        try:
            yag = yagmail.SMTP(st.secrets["email"]["user"], st.secrets["email"]["password"])
            corpo = f"""
Olá, equipe RDV!

O diário de obra foi preenchido com sucesso.

Obra: {obra}
Data: {data.strftime('%d/%m/%Y')}
Responsável: {nome_empresa}

Link:
https://drive.google.com/file/d/{drive_id}/view

Atenciosamente,
Sistema Diário de Obra - RDV Engenharia
"""
            yag.send(
                to=["comercial@rdvengenharia.com.br", "administrativo@rdvengenharia.com.br"],
                subject=f"Novo Diário de Obra - {obra} ({data.strftime('%d/%m/%Y')})",
                contents=corpo
            )
            st.success("E-mail enviado com sucesso para a diretoria.")
        except Exception as e:
            st.warning(f"Falha ao enviar e-mail: {str(e)}")
    else:
        st.error("Falha ao salvar PDF no Google Drive.")
