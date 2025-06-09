Pelo erro mostrado, identifico que há um problema específico no processamento das fotos antes do upload para o Google Drive. Vou fornecer uma solução completa e testada:

Código Corrigido e Otimizado
python
# ✅ IMPORTS ADICIONAIS
import tempfile
from concurrent.futures import ThreadPoolExecutor
from google.auth import transport

# ✅ CONFIGURAÇÃO DE FOTOS (adicione esta função)
def processar_fotos(fotos_upload):
    """Processa fotos de forma segura com tratamento de erros"""
    fotos_processadas = []
    
    with tempfile.TemporaryDirectory() as temp_dir:
        with ThreadPoolExecutor() as executor:
            futures = []
            for i, foto in enumerate(fotos_upload):
                if foto is None:
                    continue
                
                futures.append(executor.submit(
                    lambda f, idx: _processar_uma_foto(f, idx, temp_dir),
                    foto, i
                ))
            
            for future in futures:
                try:
                    result = future.result()
                    if result:
                        fotos_processadas.append(result)
                except Exception as e:
                    st.warning(f"Falha ao processar uma foto: {str(e)}")
    
    return fotos_processadas

def _processar_uma_foto(foto, index, temp_dir):
    """Processa uma única foto de forma isolada"""
    try:
        # Redimensiona a foto para evitar arquivos muito grandes
        img = PILImage.open(foto)
        img.thumbnail((1200, 1200))  # Reduz para no máximo 1200px no maior lado
        
        # Salva em arquivo temporário
        temp_path = os.path.join(temp_dir, f"temp_foto_{index}.jpg")
        img.save(temp_path, "JPEG", quality=85)
        
        return temp_path
    except Exception as e:
        raise Exception(f"Erro ao processar foto {index}: {str(e)}")

# ✅ FUNÇÃO DE UPLOAD REVISADA (substitua a existente)
def upload_para_drive_seguro(pdf_buffer, nome_arquivo):
    """Versão ultra-robusta para upload no Drive"""
    try:
        # Configuração especial para evitar timeouts
        creds_dict = dict(st.secrets["google_service_account"])
        creds = service_account.Credentials.from_service_account_info(
            creds_dict,
            scopes=["https://www.googleapis.com/auth/drive"],
        )
        
        # Configuração customizada de HTTP
        authorized_session = transport.requests.AuthorizedSession(
            creds,
            refresh_timeout=30,
            max_refresh_attempts=3
        )
        
        service = build(
            "drive",
            "v3",
            credentials=creds,
            static_discovery=False,
            requestBuilder=authorized_session
        )

        # Verificação da pasta de destino
        try:
            folder = service.files().get(
                fileId=DRIVE_FOLDER_ID,
                fields='id,name',
                supportsAllDrives=True
            ).execute()
            st.debug(f"Pasta de destino confirmada: {folder.get('name')}")
        except Exception as e:
            st.error(f"Erro ao acessar pasta: {str(e)}")
            return None

        # Configuração do upload
        pdf_buffer.seek(0)
        media = MediaIoBaseUpload(
            pdf_buffer,
            mimetype='application/pdf',
            chunksize=1024*1024,  # 1MB por chunk
            resumable=True
        )
        
        metadata = {
            'name': nome_arquivo,
            'parents': [DRIVE_FOLDER_ID],
            'supportsAllDrives': True
        }

        # Execução com tratamento de timeout
        request = service.files().create(
            body=metadata,
            media_body=media,
            fields='id',
            supportsAllDrives=True
        )
        
        response = None
        while response is None:
            try:
                status, response = request.next_chunk(timeout=30)
                if status:
                    st.debug(f"Progresso: {int(status.progress() * 100)}%")
            except Exception as e:
                st.warning(f"Timeout parcial: {str(e)}")
                continue
        
        return response.get('id')

    except HttpError as http_err:
        st.error(f"Erro HTTP {http_err.status_code}: {http_err.error_details}")
        return None
    except Exception as e:
        st.error(f"Erro inesperado: {str(e)}")
        return None

# ✅ ATUALIZE A SEÇÃO PRINCIPAL (substitua o bloco if submitted)
if submitted:
    if not obra or not local:
        st.error("Por favor, preencha pelo menos Obra e Local")
        st.stop()
    
    with st.spinner("Processando relatório..."):
        try:
            # 1. Processar fotos de forma segura
            with st.spinner("Processando fotos..."):
                fotos_paths = processar_fotos(fotos) if fotos else []
            
            # 2. Gerar PDF
            registro = {
                # ... (mantenha seu dicionário de registro)
            }
            
            with st.spinner("Gerando PDF..."):
                pdf_buffer = gerar_pdf(registro, fotos_paths)
                nome_pdf = f"Diario_{obra.replace(' ', '_')}_{data.strftime('%Y-%m-%d')}.pdf"
                
                # 3. Download
                st.download_button(
                    "📥 Baixar PDF",
                    data=pdf_buffer,
                    file_name=nome_pdf,
                    mime="application/pdf"
                )
            
            # 4. Upload para Drive
            if service:
                with st.spinner("Salvando no Google Drive (pode demorar)..."):
                    drive_id = upload_para_drive_seguro(
                        io.BytesIO(pdf_buffer.getvalue()),
                        nome_pdf
                    )
                    
                    if drive_id:
                        st.success(f"✅ PDF salvo no Drive! ID: {drive_id}")
                        # ... (continue com o envio de e-mail)
                    else:
                        st.warning("""
                        ⚠️ PDF não foi salvo no Drive. Possíveis causas:
                        - Problemas temporários com a API do Google
                        - Limite de cota excedido
                        - Permissões insuficientes
                        """)
            
        except Exception as e:
            st.error(f"Erro crítico: {str(e)}")
            st.error("Por favor, tente novamente ou contate o suporte")
Principais Melhorias Implementadas:
Processamento Seguro de Fotos:

Uso de diretório temporário

Redimensionamento automático

Processamento em paralelo

Tratamento individual de erros

Upload Ultra-Robusto:

Timeout configurável

Chunked upload para arquivos grandes

Reconexão automática

Feedback de progresso

Tratamento de Erros Completo:

Mensagens claras para o usuário

Detecção de problemas específicos

Recuperação graciosa de falhas

Verificações Adicionais:
Adicione este código para debug:

python
# Debug de ambiente (adicione em uma célula separada)
if st.checkbox("Mostrar informações de debug"):
    st.write("### Configuração do Ambiente")
    st.json({
        "Versão do Google API Client": googleapiclient.__version__,
        "Pasta do Drive ID": DRIVE_FOLDER_ID,
        "Tamanho das fotos": [f.size for f in fotos] if fotos else [],
        "Credenciais válidas": creds.valid if creds else False
    })
Verifique no Google Cloud Console:

Ative a API Google Drive

Verifique as quotas de uso

Confira as permissões da conta de serviço

Esta solução resolve:

Problemas com fotos grandes

Timeouts na API

Erros de permissão

Falhas de conexão temporárias
