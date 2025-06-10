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
import shutil  # Adicionado para a limpeza do diretório temporário
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
from googleapiclient.errors import HttpError # Importar HttpError para tratamento específico

# ✅ CONSTANTES
DRIVE_FOLDER_ID = "1BUgZRcBrKksC3eUytoJ5mv_nhMRdAv1d" # Verifique se essa pasta está compartilhada com sua Service Account

st.set_page_config(page_title="Diário de Obra - RDV", layout="centered")

# ✅ CREDENCIAIS GOOGLE DRIVE
# Acessa as credenciais da Service Account a partir dos segredos do Streamlit
# Certifique-se de que seu arquivo .streamlit/secrets.toml está configurado corretamente
# com a chave privada da sua Service Account.
try:
    creds_dict = dict(st.secrets["google_service_account"])
    creds = service_account.Credentials.from_service_account_info(
        creds_dict, scopes=["https://www.googleapis.com/auth/drive"]
    )
except KeyError:
    st.error("Erro: Credenciais da Service Account do Google Drive não encontradas. Verifique seu arquivo .streamlit/secrets.toml.")
    st.stop() # Interrompe a execução se as credenciais não forem encontradas
except Exception as e:
    st.error(f"Erro ao carregar credenciais do Google Drive: {e}")
    st.stop()


# ✅ CSVs
@st.cache_data # Usar st.cache_data para melhor performance, já que os CSVs não mudam durante a sessão
def carregar_arquivo_csv(nome_arquivo):
    if not os.path.exists(nome_arquivo):
        st.error(f"Erro: Arquivo de dados '{nome_arquivo}' não encontrado. Por favor, verifique se os CSVs estão na raiz do projeto.")
        st.stop() # Interrompe a execução se os arquivos essenciais não forem encontrados
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
# Ajuste no max_value para evitar erro se houver mais colaboradores no CSV que o limite
qtd_colaboradores = st.number_input("Quantos colaboradores hoje?", min_value=1, max_value=len(colaboradores_lista) if len(colaboradores_lista) > 0 else 10, step=1)
efetivo_lista = []
for i in range(qtd_colaboradores):
    with st.expander(f"Colaborador {i+1}"):
        # Garante que o selectbox não falha se colaboradores_lista estiver vazia
        nome = st.selectbox("Nome", colaboradores_lista if colaboradores_lista else ["Nenhum colaborador disponível"], key=f"nome_{i}")
        # Apenas tenta buscar a função se o nome selecionado for válido (não vazio ou placeholder)
        funcao = ""
        if nome and nome in colab_df["Nome"].values:
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


# ✅ FUNÇÃO REVISADA PARA PROCESSAR FOTOS (do seu amigo)
def processar_fotos(fotos_upload, obra_nome, data_relatorio):
    """
    Processa fotos de forma segura, salvando-as temporariamente no disco
    e retornando seus caminhos.
    """
    fotos_processadas = []
    # Inicializa temp_dir como None para garantir que sempre esteja definido no finally
    temp_dir_path = None

    try:
        # Cria diretório temporário
        temp_dir_path = Path(tempfile.mkdtemp(prefix="diario_obra_"))

        for i, foto_file in enumerate(fotos_upload):
            if foto_file is None:
                continue

            try:
                # Define nome do arquivo de forma única e limpa
                nome_foto_base = f"{obra_nome.replace(' ', '_')}_{data_relatorio.strftime('%Y-%m-%d')}_foto{i+1}"
                # Path(foto_file.name).suffix garante a extensão original (.png, .jpg)
                nome_foto_final = f"{nome_foto_base}{Path(foto_file.name).suffix}"
                caminho_foto = temp_dir_path / nome_foto_final

                # Salva o arquivo temporário do buffer de upload para o disco
                with open(caminho_foto, "wb") as f:
                    f.write(foto_file.getbuffer())

                # Verifica se o arquivo foi criado (boa prática)
                if not caminho_foto.exists():
                    raise FileNotFoundError(f"Arquivo {caminho_foto} não foi criado após a escrita.")

                # Redimensiona a imagem e sobrescreve o arquivo temporário
                img = PILImage.open(caminho_foto)
                img.thumbnail((1200, 1200))  # Redimensiona mantendo aspect ratio
                img.save(caminho_foto, "JPEG", quality=85) # Salva com qualidade para JPG

                fotos_processadas.append(str(caminho_foto)) # Retorna o caminho como string
            except Exception as img_error:
                st.warning(f"Falha ao processar foto {i+1} ({foto_file.name}): {str(img_error)}")
                continue # Continua para a próxima foto mesmo se uma falhar

        return fotos_processadas

    except Exception as e:
        st.error(f"Erro crítico no processamento inicial das fotos: {str(e)}")
        # Em caso de erro crítico, tenta limpar o diretório temporário se ele foi criado
        if temp_dir_path and temp_dir_path.exists():
            shutil.rmtree(temp_dir_path)
        return []


# ✅ FUNÇÃO GERAR_PDF REVISADA (do seu amigo)
def gerar_pdf(registro, fotos_paths):
    """
    Gera PDF, incluindo campos do registro e fotos, com tratamento robusto de erros.
    """
    buffer = io.BytesIO()

    try:
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

        # Dados do Registro
        # Ajuste para campos de texto longos como Máquinas, Serviços e Ocorrências
        def draw_text_area(canvas_obj, text, x, y_start, max_width, line_height=14):
            from reportlab.platypus import Paragraph
            from reportlab.lib.styles import getSampleStyleSheet
            styles = getSampleStyleSheet()
            style = styles['Normal']
            style.leading = line_height # Espaçamento entre linhas

            p = Paragraph(text, style)
            # Calcula altura necessária para o texto
            text_width, text_height = p.wrapOn(canvas_obj, max_width, height)
            
            # Se o texto exceder a largura, ele será quebrado em múltiplas linhas
            # Retorna a nova posição Y após desenhar o texto
            p.drawOn(canvas_obj, x, y_start - text_height)
            return y_start - text_height - line_height # Retorna nova Y para o próximo item

        y = height - margem - 40 # Começa abaixo do título principal

        c.drawString(margem, y, f"Obra: {registro['Obra']}")
        y -= 20
        c.drawString(margem, y, f"Local: {registro['Local']}")
        y -= 20
        c.drawString(margem, y, f"Data: {registro['Data']}")
        y -= 20
        c.drawString(margem, y, f"Contrato: {registro['Contrato']}")
        y -= 20
        c.drawString(margem, y, f"Condições do dia: {registro['Clima']}")
        y -= 20
        
        # Máquinas
        c.drawString(margem, y, "Máquinas e equipamentos utilizados:")
        y = draw_text_area(c, registro['Máquinas'], margem + 10, y - 5, width - 2*margem)
        y -= 10

        # Serviços
        c.drawString(margem, y, "Serviços executados no dia:")
        y = draw_text_area(c, registro['Serviços'], margem + 10, y - 5, width - 2*margem)
        y -= 10

        c.drawString(margem, y, "Efetivo de Pessoal:")
        y -= 20
        for item in json.loads(registro["Efetivo"]):
            linha = f"- {item['Nome']} ({item['Função']}): {item['Entrada']} - {item['Saída']}"
            c.drawString(margem + 10, y, linha)
            y -= 15

        y -= 10
        # Ocorrências
        c.drawString(margem, y, "Ocorrências:")
        y = draw_text_area(c, registro['Ocorrências'], margem + 10, y - 5, width - 2*margem)
        y -= 10

        c.drawString(margem, y, f"Responsável Empresa: {registro['Responsável Empresa']}")
        y -= 20
        c.drawString(margem, y, f"Fiscalização: {registro['Fiscalização']}")

        # Seção de fotos com tratamento de erros
        for foto_path in fotos_paths:
            try:
                # Verifica se o arquivo existe antes de tentar abrir
                if not Path(foto_path).exists():
                    st.warning(f"Foto não encontrada no caminho temporário e será ignorada: {foto_path}")
                    continue

                c.showPage() # Inicia uma nova página para cada foto
                y = height - margem
                c.drawString(margem, y, f"📷 Foto: {Path(foto_path).name}")
                y -= 20 # Espaçamento para o nome da foto

                # Tenta carregar a imagem e desenhar
                img = PILImage.open(foto_path)
                
                # Redimensiona para caber na página de forma inteligente
                img_width, img_height = img.size
                max_img_width = width - 2 * margem
                max_img_height = height - 2 * margem - y # Espaço restante na página

                # Calcula a proporção para redimensionar sem distorcer
                aspect_ratio = img_width / img_height

                if img_width > max_img_width or img_height > max_img_height:
                    if (max_img_width / aspect_ratio) <= max_img_height:
                        new_width = max_img_width
                        new_height = max_img_width / aspect_ratio
                    else:
                        new_height = max_img_height
                        new_width = max_img_height * aspect_ratio
                    img = img.resize((int(new_width), int(new_height)), PILImage.LANCZOS) # PILImage.LANCZOS para melhor qualidade
                
                # Centraliza a imagem horizontalmente se for menor que a largura máxima
                x_pos = margem + (max_img_width - img.width) / 2 if img.width < max_img_width else margem
                
                # Ajusta a posição Y para que a imagem caiba a partir da posição atual
                # e haja espaço para o próximo elemento
                img_y_pos = y - img.height - 10 # 10 pixels de margem após o nome da foto
                
                c.drawImage(ImageReader(img), x_pos, img_y_pos, width=img.width, height=img.height)

            except Exception as e:
                st.warning(f"Erro ao adicionar foto '{Path(foto_path).name}' ao PDF: {str(e)}. A foto será ignorada.")
                continue # Continua para a próxima foto mesmo se uma falhar

        c.save()
        buffer.seek(0)
        return buffer

    except Exception as e:
        st.error(f"Erro crítico ao gerar PDF: {str(e)}")
        return None # Retorna None em caso de falha crítica


# ✅ UPLOAD PARA GOOGLE DRIVE
def upload_para_drive_seguro(pdf_buffer, nome_arquivo):
    """
    Faz o upload de um buffer de PDF para o Google Drive.
    """
    try:
        pdf_buffer.seek(0) # Garante que o ponteiro está no início do buffer
        service = build("drive", "v3", credentials=creds, static_discovery=False)
        media = MediaIoBaseUpload(pdf_buffer, mimetype='application/pdf', resumable=True)
        file_metadata = {'name': nome_arquivo, 'parents': [DRIVE_FOLDER_ID]}
        file = service.files().create(
            body=file_metadata,
            media_body=media,
            fields='id',
            supportsAllDrives=True # Necessário para pastas em "Drives Compartilhados"
        ).execute()
        return file.get("id")
    except HttpError as error: # Tratamento específico para erros da API Google
        st.error(f"Erro HTTP ao enviar para o Google Drive: {error.resp.status} - {error.content.decode('utf-8')}")
        st.error("Verifique as permissões da Service Account e o compartilhamento da pasta no Google Drive.")
        return None
    except Exception as e:
        st.error(f"Erro inesperado ao enviar para o Google Drive: {e}")
        return None


# ✅ EXECUÇÃO FINAL
# Use st.form e st.form_submit_button para melhor controle de estado do formulário
with st.form("relatorio_form"):
    # Mova todos os seus st.selectbox, st.text_input, etc. para DENTRO deste bloco `with`
    # ... (todo o seu código de formulário vai aqui)
    # Exemplo:
    # obra = st.selectbox("Obra", obras_lista)
    # ...
    
    # Coloque o botão de submit no final do formulário
    submitted = st.form_submit_button("Salvar e Gerar Relatório")

# Garante que as variáveis temp_dir_obj e fotos_paths_to_clean estejam definidas
# antes do bloco finally principal.
temp_dir_obj = None 
fotos_paths_to_clean = []


if submitted:
    # Inicializa temp_dir_obj para que possa ser limpo no finally
    temp_dir_obj = Path(tempfile.mkdtemp(prefix="diario_obra_"))
    fotos_paths_to_clean = [] # Lista para armazenar os caminhos a serem limpos

    with st.spinner("Preparando relatório..."):
        try:
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
            # Passa obra e data para a função processar_fotos
            fotos_paths_to_clean = processar_fotos(fotos, obra, data) if fotos else []

            if fotos and not fotos_paths_to_clean:
                st.warning("⚠️ Nenhuma foto foi processada corretamente. O PDF pode não conter imagens.")
            
            st.info("Gerando PDF...")
            nome_pdf = f"Diario_{obra.replace(' ', '_')}_{data.strftime('%Y-%m-%d')}.pdf"
            
            # Passa fotos_paths_to_clean, que são os caminhos temporários
            pdf_buffer = gerar_pdf(registro, fotos_paths_to_clean)

            if pdf_buffer is None:
                st.error("Falha crítica ao gerar PDF. O processo será interrompido.")
                st.stop() # Para a execução se o PDF não puder ser gerado
            
            st.download_button("📥 Baixar PDF", data=pdf_buffer, file_name=nome_pdf, mime="application/pdf")

            st.info("Enviando para o Google Drive...")
            # A correção do .getvalue() já foi feita na explicação anterior, aqui está otimizado
            drive_id = upload_para_drive_seguro(pdf_buffer, nome_pdf)

            if drive_id:
                st.success(f"PDF salvo no Drive! ID: {drive_id}")
                st.markdown(f"[Abrir no Google Drive](https://drive.google.com/file/d/{drive_id}/view)")

                st.info("Enviando e-mail...")
                try:
                    # Credenciais do Yagmail via st.secrets
                    yag_user = st.secrets["email"]["user"]
                    yag_password = st.secrets["email"]["password"]

                    yag = yagmail.SMTP(user=yag_user, password=yag_password)
                    
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
                except KeyError:
                    st.warning("Credenciais de e-mail não encontradas nos segredos do Streamlit. E-mail não enviado.")
                except Exception as e:
                    st.warning(f"Falha ao enviar e-mail: {str(e)}")
                    st.info("Verifique se as credenciais do Yagmail estão corretas (especialmente a senha de aplicativo para Gmail).")
            else:
                st.error("Falha ao salvar PDF no Google Drive. E-mail não enviado.")

        except Exception as e:
            st.error(f"Ocorreu um erro inesperado durante o processamento do relatório: {str(e)}")

        finally:
            # Limpeza dos arquivos temporários e do diretório
            try:
                # O temp_dir_obj é o objeto Path do diretório temporário
                if temp_dir_obj and temp_dir_obj.exists():
                    shutil.rmtree(temp_dir_obj)
                    # st.info(f"Diretório temporário {temp_dir_obj} limpo.") # Para depuração
            except Exception as e:
                st.warning(f"Erro ao limpar arquivos temporários: {str(e)}")
