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
from googleapiclient.errors import HttpError # Importado para tratamento específico de erros da API Google

# ✅ CONSTANTES
DRIVE_FOLDER_ID = "1BUgZRcBrKksC3eUytoJ5mv_nhMRdAv1d" # ID da pasta no Google Drive

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
    st.error("Erro: Credenciais da Service Account do Google Drive não encontradas. Por favor, verifique se 'google_service_account' está configurado em seu arquivo .streamlit/secrets.toml.")
    st.stop() # Interrompe a execução se as credenciais não forem encontradas
except Exception as e:
    st.error(f"Erro ao carregar credenciais do Google Drive: {e}")
    st.stop()


# ✅ CARREGAMENTO DE CSVs
@st.cache_data # Usar st.cache_data para melhor performance, já que os CSVs não mudam durante a sessão
def carregar_arquivo_csv(nome_arquivo):
    """Carrega um arquivo CSV e verifica sua existência."""
    if not os.path.exists(nome_arquivo):
        st.error(f"Erro: Arquivo de dados '{nome_arquivo}' não encontrado. Por favor, verifique se os CSVs (colaboradores.csv, obras.csv, contratos.csv) estão na raiz do projeto.")
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
obras_lista = [""] + obras_df["Nome"].tolist() # Adiciona opção vazia
contratos_lista = [""] + contratos_df["Nome"].tolist() # Adiciona opção vazia

# ✅ FORMULÁRIO PRINCIPAL
st.title("Relatório Diário de Obra - RDV Engenharia")

# Usamos st.form para agrupar os inputs e ter um controle mais explícito do submit
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
    # Ajusta o max_value para evitar erros se houver poucos colaboradores no CSV
    max_colab_display = len(colaboradores_lista) if len(colaboradores_lista) > 0 else 10
    qtd_colaboradores = st.number_input("Quantos colaboradores hoje?", min_value=1, max_value=max_colab_display, step=1)
    
    efetivo_lista = []
    for i in range(qtd_colaboradores):
        with st.expander(f"Colaborador {i+1}"):
            # Garante que o selectbox não falha se colaboradores_lista estiver vazia
            nome_selecionado = st.selectbox("Nome", colaboradores_lista if colaboradores_lista else ["Nenhum colaborador disponível"], key=f"nome_{i}")
            
            funcao_sugerida = ""
            # Apenas tenta buscar a função se um nome válido for selecionado
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

    # Botão de submissão do formulário
    submitted = st.form_submit_button("Salvar e Gerar Relatório")


# ✅ FUNÇÃO DE PROCESSAMENTO DE FOTOS
def processar_fotos(fotos_upload, obra_nome, data_relatorio):
    """
    Processa fotos, redimensiona, salva temporariamente no disco
    e retorna os caminhos dos arquivos processados.
    """
    fotos_processadas_paths = []
    # Inicializa temp_dir_path como None; ele será definido na primeira vez que for criado
    # e usado no bloco finally principal para limpeza.
    # O temp_dir_path será o objeto Path do diretório temporário.
    temp_dir_path_obj = None

    try:
        # Cria um diretório temporário único para esta execução
        temp_dir_path_obj = Path(tempfile.mkdtemp(prefix="diario_obra_"))
        st.info(f"Diretório temporário criado para fotos: {temp_dir_path_obj}")

        for i, foto_file in enumerate(fotos_upload):
            # Garante que o arquivo de upload não é nulo
            if foto_file is None:
                st.warning(f"Foto {i+1} enviada está vazia e será ignorada.")
                continue

            try:
                # Cria um nome de arquivo único e legível para a foto temporária
                nome_foto_base = f"{obra_nome.replace(' ', '_')}_{data_relatorio.strftime('%Y-%m-%d')}_foto{i+1}"
                nome_foto_final = f"{nome_foto_base}{Path(foto_file.name).suffix}"
                caminho_foto_temp = temp_dir_path_obj / nome_foto_final
                
                st.info(f"Tentando salvar foto {i+1} ({foto_file.name}) em: {caminho_foto_temp}")

                # Salva o conteúdo do arquivo enviado pelo Streamlit para o disco
                with open(caminho_foto_temp, "wb") as f:
                    f.write(foto_file.getbuffer())

                # Verificação de segurança: Confirma que o arquivo foi realmente criado
                if not caminho_foto_temp.exists():
                    raise FileNotFoundError(f"Arquivo temporário da foto {i+1} não foi criado em {caminho_foto_temp}")
                
                st.info(f"Foto {i+1} salva temporariamente. Tamanho: {caminho_foto_temp.stat().st_size} bytes.")

                # Abre a imagem salva, redimensiona e a sobrescreve no mesmo local temporário
                img = PILImage.open(caminho_foto_temp)
                img.thumbnail((1200, 1200))  # Redimensiona mantendo a proporção
                img.save(caminho_foto_temp, "JPEG", quality=85) # Salva como JPEG com compressão

                fotos_processadas_paths.append(str(caminho_foto_temp)) # Adiciona o caminho final à lista
                st.info(f"Foto {i+1} processada e pronta: {caminho_foto_temp}")

            except Exception as img_error:
                st.warning(f"Falha ao processar foto {i+1} ({foto_file.name}): {str(img_error)}. Esta foto será ignorada no PDF.")
                continue # Continua para a próxima foto, mesmo se uma falhar

        return fotos_processadas_paths # Retorna a lista de caminhos dos arquivos temporários
    
    except Exception as e:
        st.error(f"Erro crítico no processamento inicial das fotos: {str(e)}")
        # Se um erro crítico ocorrer na criação do diretório, garante a limpeza
        if temp_dir_path_obj and temp_dir_path_obj.exists():
            shutil.rmtree(temp_dir_path_obj)
            st.warning(f"Diretório temporário {temp_dir_path_obj} limpo devido a erro crítico no processamento inicial das fotos.")
        return []


# ✅ FUNÇÃO DE GERAÇÃO DE PDF
def gerar_pdf(registro, fotos_paths):
    """
    Gera o relatório diário de obra em formato PDF, incluindo os dados
    do formulário e as fotos processadas.
    """
    buffer = io.BytesIO() # Buffer em memória para o PDF

    try:
        c = canvas.Canvas(buffer, pagesize=A4)
        width, height = A4
        margem = 30
        y = height - margem

        # Estilo para o título principal
        c.setFont("Helvetica-Bold", 16)
        c.setFillColor(HexColor("#0F2A4D")) # Cor azul escuro para o título
        c.drawCentredString(width / 2, y, "Diário de Obra - RDV Engenharia")
        y -= 40 # Espaço após o título

        c.setFont("Helvetica", 12) # Fonte padrão para o corpo do texto
        c.setFillColor("black")

        # Função auxiliar para desenhar textos longos com quebra de linha
        def draw_text_area_with_wrap(canvas_obj, text, x, y_start, max_width, line_height=14):
            from reportlab.platypus import Paragraph
            from reportlab.lib.styles import getSampleStyleSheet
            styles = getSampleStyleSheet()
            style = styles['Normal']
            style.leading = line_height # Define o espaçamento entre linhas

            p = Paragraph(text, style)
            text_width, text_height = p.wrapOn(canvas_obj, max_width, height) # Calcula o espaço que o texto ocupará
            
            p.drawOn(canvas_obj, x, y_start - text_height) # Desenha o parágrafo
            return y_start - text_height - line_height # Retorna a nova posição Y para o próximo elemento

        # Dados Gerais do Registro
        y = height - margem - 40 # Começa o conteúdo abaixo do título principal

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
        
        # Máquinas e equipamentos (com quebra de linha)
        c.drawString(margem, y, "Máquinas e equipamentos utilizados:")
        y = draw_text_area_with_wrap(c, registro['Máquinas'], margem + 10, y - 5, width - 2*margem)
        y -= 10 # Espaço extra após o bloco de texto

        # Serviços executados (com quebra de linha)
        c.drawString(margem, y, "Serviços executados no dia:")
        y = draw_text_area_with_wrap(c, registro['Serviços'], margem + 10, y - 5, width - 2*margem)
        y -= 10

        # Efetivo de Pessoal
        c.drawString(margem, y, "Efetivo de Pessoal:")
        y -= 20
        for item in json.loads(registro["Efetivo"]):
            linha = f"- {item['Nome']} ({item['Função']}): {item['Entrada']} - {item['Saída']}"
            c.drawString(margem + 10, y, linha)
            y -= 15 # Espaçamento para cada colaborador

        y -= 10
        # Ocorrências (com quebra de linha)
        c.drawString(margem, y, "Ocorrências:")
        y = draw_text_area_with_wrap(c, registro['Ocorrências'], margem + 10, y - 5, width - 2*margem)
        y -= 10

        c.drawString(margem, y, f"Responsável Empresa: {registro['Responsável Empresa']}")
        y -= 20
        c.drawString(margem, y, f"Fiscalização: {registro['Fiscalização']}")

        # Seção de fotos
        for foto_path in fotos_paths:
            try:
                # Verifica se o arquivo da foto existe antes de tentar carregar
                if not Path(foto_path).exists():
                    st.warning(f"A foto '{Path(foto_path).name}' não foi encontrada no caminho temporário e será ignorada no PDF.")
                    continue

                c.showPage() # Começa uma nova página para cada foto
                y = height - margem
                c.drawString(margem, y, f"📷 Foto: {Path(foto_path).name}")
                y -= 20 # Espaço para o nome da foto

                img = PILImage.open(foto_path) # Abre a imagem do caminho temporário
                
                # Lógica para redimensionar a imagem para caber na página sem distorção
                img_width, img_height = img.size
                max_img_width = width - 2 * margem
                max_img_height = height - 2 * margem - (height - y) # Altura disponível abaixo do título da foto

                # Calcula as novas dimensões mantendo a proporção
                aspect_ratio = img_width / img_height
                if img_width > max_img_width or img_height > max_img_height:
                    if (max_img_width / aspect_ratio) <= max_img_height: # Limite pela largura
                        new_width = max_img_width
                        new_height = max_img_width / aspect_ratio
                    else: # Limite pela altura
                        new_height = max_img_height
                        new_width = max_img_height * aspect_ratio
                    img = img.resize((int(new_width), int(new_height)), PILImage.LANCZOS) # Redimensiona com alta qualidade
                
                # Calcula a posição X para centralizar a imagem horizontalmente
                x_pos = margem + (max_img_width - img.width) / 2 if img.width < max_img_width else margem
                
                # Calcula a posição Y para desenhar a imagem abaixo do nome da foto e com margem
                img_y_pos = y - img.height - 10 
                
                # Desenha a imagem no PDF
                c.drawImage(ImageReader(img), x_pos, img_y_pos, width=img.width, height=img.height)

            except Exception as e:
                st.warning(f"Erro ao adicionar a foto '{Path(foto_path).name}' ao PDF: {str(e)}. A foto será ignorada.")
                continue # Continua para a próxima foto

        c.save() # Salva todas as operações no PDF
        buffer.seek(0) # Retorna o ponteiro para o início do buffer para que possa ser lido
        return buffer

    except Exception as e:
        st.error(f"Erro crítico ao gerar o documento PDF: {str(e)}")
        return None # Retorna None em caso de falha crítica na geração do PDF


# ✅ FUNÇÃO DE UPLOAD PARA GOOGLE DRIVE
def upload_para_drive_seguro(pdf_buffer, nome_arquivo):
    """
    Faz o upload de um buffer de PDF para uma pasta específica no Google Drive.
    Inclui tratamento de erros da API.
    """
    try:
        pdf_buffer.seek(0) # Garante que o ponteiro está no início do buffer para leitura
        service = build("drive", "v3", credentials=creds, static_discovery=False)
        media = MediaIoBaseUpload(pdf_buffer, mimetype='application/pdf', resumable=True)
        file_metadata = {'name': nome_arquivo, 'parents': [DRIVE_FOLDER_ID]}
        
        file = service.files().create(
            body=file_metadata,
            media_body=media,
            fields='id',
            supportsAllDrives=True # Importante para pastas em "Drives Compartilhados"
        ).execute()
        return file.get("id")
    except HttpError as error: # Tratamento específico para erros da API do Google Drive
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
        # Configuração do Yagmail com parâmetros explícitos para maior compatibilidade
        yag = yagmail.SMTP(
            user=st.secrets["email"]["user"],
            password=st.secrets["email"]["password"],
            host='smtp.gmail.com', # Host SMTP do Gmail
            port=587,              # Porta padrão para STARTTLS
            smtp_starttls=True,    # Habilita STARTTLS
            smtp_ssl=False,        # Desabilita SSL direto (pois usamos STARTTLS)
            timeout=30             # Timeout de 30 segundos para conexão
        )
        
        # Monta o corpo completo do e-mail em HTML
        corpo_completo_final = f"""
        <html>
            <body>
                {corpo_html} # Insere o HTML fornecido
                {f'<p><a href="https://drive.google.com/file/d/{drive_id}/view">Acessar o Diário de Obra no Google Drive</a></p>' if drive_id else ''}
                <p style="color: #888; font-size: 0.8em; margin-top: 20px;">
                    Mensagem enviada automaticamente pelo Sistema Diário de Obra - RDV Engenharia
                </p>
            </body>
        </html>
        """
        
        # Envia o e-mail
        yag.send(
            to=destinatarios,
            subject=assunto,
            contents=corpo_completo_final,
            # Adiciona um cabeçalho personalizado, útil para filtros ou auditoria
            headers={'X-Application': 'DiarioObraRDV'} 
        )
        return True
        
    except KeyError:
        st.error("Erro: Credenciais de e-mail não encontradas em '.streamlit/secrets.toml'. Por favor, verifique.")
        return False
    except Exception as e:
        # Erros específicos do SMTP (como autenticação falha) são úteis para depuração
        st.error(f"Falha no envio do e-mail: {str(e)}")
        return False


# ✅ LÓGICA DE EXECUÇÃO DO RELATÓRIO
# As variáveis temp_dir_obj_for_cleanup e fotos_processed_paths precisam ser inicializadas fora do try
# para que o bloco finally possa acessá-las corretamente.
temp_dir_obj_for_cleanup = None 
fotos_processed_paths = [] # Inicializa como lista vazia

if submitted:
    # Este bloco try-except-finally gerencia todo o fluxo do relatório
    # e garante a limpeza dos arquivos temporários no final.
    try:
        # Validações básicas antes de prosseguir
        if not obra or obra == "":
            st.error("Por favor, selecione a 'Obra'.")
            st.stop()
        if not contrato or contrato == "":
            st.error("Por favor, selecione o 'Contrato'.")
            st.stop()
        if not nome_empresa:
            st.error("Por favor, preencha o campo 'Responsável pela empresa'.")
            st.stop()

        # Registro de dados do formulário
        registro = {
            "Obra": obra,
            "Local": local,
            "Data": data.strftime("%d/%m/%Y"),
            "Contrato": contrato,
            "Clima": clima,
            "Máquinas": maquinas,
            "Serviços": servicos,
            "Efetivo": json.dumps(efetivo_lista, ensure_ascii=False), # Converte lista para JSON string
            "Ocorrências": ocorrencias,
            "Responsável Empresa": nome_empresa,
            "Fiscalização": nome_fiscal
        }

        # --- Processamento das Fotos ---
        with st.spinner("Processando fotos... Isso pode levar alguns segundos..."):
            fotos_processed_paths = processar_fotos(fotos, obra, data) if fotos else []
            
            # Captura o diretório temporário para limpeza, se fotos foram processadas
            if fotos_processed_paths:
                temp_dir_obj_for_cleanup = Path(fotos_processed_paths[0]).parent
            elif fotos: # Se o usuário enviou fotos, mas nenhuma foi processada com sucesso
                st.warning("⚠️ Nenhuma foto foi processada corretamente. O PDF pode não conter imagens.")
            
        # --- Geração do PDF ---
        with st.spinner("Gerando PDF..."):
            nome_pdf = f"Diario_{obra.replace(' ', '_')}_{data.strftime('%Y-%m-%d')}.pdf"
            pdf_buffer = gerar_pdf(registro, fotos_processed_paths)

            if pdf_buffer is None:
                st.error("Falha crítica ao gerar o PDF. Por favor, tente novamente ou verifique os logs para detalhes.")
                st.stop() # Para a execução se o PDF não puder ser gerado
            
        # --- Download do PDF ---
        st.download_button(
            label="📥 Baixar Relatório PDF",
            data=pdf_buffer,
            file_name=nome_pdf,
            mime="application/pdf",
            type="primary" # Botão primário para mais destaque
        )

        # --- Upload para Google Drive ---
        drive_id = None # Inicializa drive_id como None
        with st.spinner("Enviando relatório para o Google Drive..."):
            # O pdf_buffer já está com o ponteiro no início após o download_button
            drive_id = upload_para_drive_seguro(pdf_buffer, nome_pdf)

            if drive_id:
                st.success(f"PDF salvo com sucesso no Google Drive! ID: {drive_id}")
                st.markdown(f"**[Clique aqui para abrir no Google Drive](https://drive.google.com/file/d/{drive_id}/view)**")

                # --- Envio de E-mail de Notificação ---
                with st.spinner("Enviando e-mail de notificação..."):
                    assunto_email = f"📋 Novo Diário de Obra - {obra} ({data.strftime('%d/%m/%Y')})"
                    
                    # Corpo do e-mail em HTML (já com tags HTML como seu amigo sugeriu)
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
        # Este bloco garante que o diretório temporário e seus arquivos sejam limpos
        # após toda a execução, independentemente de sucesso ou falha.
        try:
            if temp_dir_obj_for_cleanup and temp_dir_obj_for_cleanup.exists():
                st.info(f"Limpando diretório temporário: {temp_dir_obj_for_cleanup}")
                shutil.rmtree(temp_dir_obj_for_cleanup)
            # else: # Comentei para não poluir os logs se não houver temp_dir
            #     st.info("Nenhum diretório temporário para limpar ou já limpo.")
        except Exception as e:
            st.warning(f"Erro ao tentar limpar arquivos temporários: {str(e)}. Por favor, verifique os logs.")
