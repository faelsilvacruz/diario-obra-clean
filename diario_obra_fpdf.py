import streamlit as st
from fpdf import FPDF
from datetime import datetime
import io
import os

class DiarioObraPDF(FPDF):
    def header(self):
        # Fundo azul institucional para o topo
        self.set_fill_color(15, 42, 77)  # azul institucional RDV
        self.rect(0, 0, self.w, 45, 'F')

        # Logo (ajuste y/x se necessário para centralizar na caixa)
        logo_path = "LOGO_RDV_AZUL.png"
        if os.path.exists(logo_path):
            self.image(logo_path, 18, 8, 32, 22)  # x, y, w, h (ajuste conforme sua logo)

        # Título centralizado, bem no meio do cabeçalho azul
        self.set_xy(0, 15)
        self.set_font('Arial', 'B', 22)
        self.set_text_color(255, 255, 255)
        self.cell(self.w, 10, 'DIÁRIO DE OBRA', border=0, ln=2, align='C')
        self.set_font('Arial', '', 13)
        # Caso queira remover, só comentar a próxima linha
        # self.cell(self.w, 8, 'RDV ENGENHARIA', border=0, ln=1, align='C')
        self.ln(7)
        self.set_text_color(0, 0, 0)

    def footer(self):
        self.set_y(-15)
        self.set_font('Arial', 'I', 8)
        self.set_text_color(130, 130, 130)
        self.cell(0, 6, f'Gerado em: {datetime.now().strftime("%d/%m/%Y %H:%M")} - Página {self.page_no()}', 0, 0, 'R')


def gerar_pdf_fpfd(
    dados_obra, colaboradores, maquinas, servicos,
    intercorrencias, responsavel, fiscal, clima, fotos_paths=None
):
    pdf = DiarioObraPDF()
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=20)
    pdf.ln(8)

    # --- Dados da Obra ---
    pdf.set_font('Arial', 'B', 12)
    pdf.set_text_color(0, 0, 0)
    campos = [
        ("OBRA:", dados_obra.get("obra", "")),
        ("LOCAL:", dados_obra.get("local", "")),
        ("DATA:", dados_obra.get("data", "")),
        ("CONTRATO:", dados_obra.get("contrato", "")),
        ("CLIMA:", clima)
    ]
    for rotulo, valor in campos:
        pdf.cell(25, 8, rotulo, 0, 0)
        pdf.set_font('Arial', '', 12)
        pdf.cell(80, 8, valor, 0, 1)
        pdf.set_font('Arial', 'B', 12)

    # --- Serviços Executados ---
    pdf.ln(3)
    pdf.set_fill_color(220, 230, 242)
    pdf.set_font('Arial', 'B', 12)
    pdf.cell(0, 8, 'SERVIÇOS EXECUTADOS:', 0, 1, 'L', True)
    pdf.set_font('Arial', '', 11)
    pdf.multi_cell(0, 7, servicos.strip() if servicos.strip() else "Nenhum serviço informado.", 0, 1)
    
    # --- Máquinas e Equipamentos ---
    pdf.ln(2)
    pdf.set_font('Arial', 'B', 12)
    pdf.cell(0, 8, 'MÁQUINAS/EQUIPAMENTOS:', 0, 1, 'L', True)
    pdf.set_font('Arial', '', 11)
    pdf.multi_cell(0, 7, maquinas.strip() if maquinas.strip() else "Nenhuma máquina/equipamento informado.", 0, 1)

    # --- Efetivo de Pessoal ---
    pdf.ln(2)
    pdf.set_font('Arial', 'B', 12)
    pdf.cell(0, 8, 'EFETIVO DE PESSOAL', 0, 1, 'L', True)
    pdf.set_fill_color(15, 42, 77)
    pdf.set_text_color(255, 255, 255)
    pdf.set_font('Arial', 'B', 10)
    pdf.cell(70, 8, 'NOME', 1, 0, 'C', True)
    pdf.cell(40, 8, 'FUNÇÃO', 1, 0, 'C', True)
    pdf.cell(30, 8, 'ENTRADA', 1, 0, 'C', True)
    pdf.cell(30, 8, 'SAÍDA', 1, 1, 'C', True)
    pdf.set_text_color(0, 0, 0)
    pdf.set_font('Arial', '', 10)
    for row in colaboradores:
        pdf.cell(70, 8, row[0], 1)
        pdf.cell(40, 8, row[1], 1)
        pdf.cell(30, 8, row[2], 1)
        pdf.cell(30, 8, row[3], 1)
        pdf.ln()
    pdf.ln(2)

    # --- Intercorrências ---
    pdf.set_font('Arial', 'B', 12)
    pdf.set_fill_color(220, 230, 242)
    pdf.cell(0, 8, 'INTERCORRÊNCIAS:', 0, 1, 'L', True)
    pdf.set_font('Arial', '', 11)
    pdf.multi_cell(0, 7, intercorrencias.strip() if intercorrencias.strip() else "Sem intercorrências.", 0, 1)
    pdf.ln(2)

    # --- Assinaturas (com linha centralizada e nomes centralizados) ---
    pdf.set_font('Arial', 'B', 12)
    pdf.set_fill_color(220, 230, 242)
    pdf.set_text_color(0, 0, 0)
    pdf.cell(0, 8, 'ASSINATURAS:', 0, 1, 'L', True)
    pdf.ln(6)

    largura_linha = 90
    espacamento = 40  # espaço entre as duas assinaturas
    pagina_largura = pdf.w - 2 * pdf.l_margin
    x_resp = pdf.l_margin + (pagina_largura // 4) - (largura_linha // 2)
    x_fisc = pdf.l_margin + (3 * pagina_largura // 4) - (largura_linha // 2)
    y_assin = pdf.get_y()

    # Linhas de assinatura
    pdf.set_draw_color(80, 80, 80)
    pdf.line(x_resp, y_assin, x_resp + largura_linha, y_assin)
    pdf.line(x_fisc, y_assin, x_fisc + largura_linha, y_assin)

    pdf.set_font('Arial', '', 11)
    pdf.ln(2)
    # Responsável Técnico
    pdf.set_xy(x_resp, y_assin + 5)
    pdf.cell(largura_linha, 7, "Responsável Técnico:", 0, 2, 'C')
    pdf.cell(largura_linha, 7, f"Nome: {responsavel}", 0, 0, 'C')
    # Fiscalização
    pdf.set_xy(x_fisc, y_assin + 5)
    pdf.cell(largura_linha, 7, "Fiscalização:", 0, 2, 'C')
    pdf.cell(largura_linha, 7, f"Nome: {fiscal}", 0, 0, 'C')
    pdf.ln(22)

    # --- Fotos (cada uma em nova página) ---
    if fotos_paths:
        for path in fotos_paths:
            if os.path.exists(path):
                pdf.add_page()
                pdf.set_font('Arial', 'B', 12)
                pdf.cell(0, 10, f'Foto: {os.path.basename(path)}', 0, 1)
                pdf.image(path, x=30, w=150)

    # --- PDF em memória ---
    pdf_buffer = io.BytesIO(pdf.output(dest='S').encode('latin1'))
    return pdf_buffer

# ---- STREAMLIT APP EXEMPLO ----
st.title("Gerar Diário de Obra - RDV Engenharia")

# Coleta os dados
dados_obra = {
    "obra": st.text_input("Obra", "Colecta - Suzano"),
    "local": st.text_input("Local", "Administrativo"),
    "data": st.text_input("Data", datetime.now().strftime("%d/%m/%Y")),
    "contrato": st.text_input("Contrato", "Lopes Engenharia")
}
clima = st.selectbox("Condições do dia", ["Bom", "Chuva", "Garoa", "Impraticável", "Feriado", "Guarda"], index=0)
servicos = st.text_area("Serviços executados", "Uso de andaimes. Em linguística, a noção de texto é ampla e ainda aberta...")
maquinas = st.text_area("Máquinas/Equipamentos", "Andaimes, betoneira, ferramentas manuais")
intercorrencias = st.text_area("Intercorrências", "Sem intercorrências")
responsavel = st.text_input("Responsável Técnico", "Wellyngton Silveira")
fiscal = st.text_input("Fiscalização", "Pedro Pascal")

# Tabela de colaboradores
st.subheader("Colaboradores")
collabs = []
num_colabs = st.number_input("Quantos colaboradores?", min_value=1, max_value=10, value=3)
for i in range(int(num_colabs)):
    cols = st.columns(4)
    nome = cols[0].text_input(f"Nome {i+1}", key=f"nome_{i}")
    funcao = cols[1].text_input(f"Função {i+1}", key=f"func_{i}")
    entrada = cols[2].text_input(f"Entrada {i+1}", value="08:00", key=f"ent_{i}")
    saida = cols[3].text_input(f"Saída {i+1}", value="17:00", key=f"sai_{i}")
    collabs.append([nome, funcao, entrada, saida])

# Upload de fotos
st.subheader("Fotos do serviço (opcional)")
fotos_upload = st.file_uploader("Selecione fotos", type=["jpg", "jpeg", "png"], accept_multiple_files=True)
fotos_paths = []
if fotos_upload:
    for up in fotos_upload:
        temp_path = f"/tmp/{up.name}"
        with open(temp_path, "wb") as f:
            f.write(up.getbuffer())
        fotos_paths.append(temp_path)

# Botão para gerar e baixar
if st.button("Gerar e Baixar PDF"):
    pdf_buffer = gerar_pdf_fpfd(
        dados_obra, collabs, maquinas, servicos,
        intercorrencias, responsavel, fiscal, clima, fotos_paths
    )
    st.success("PDF gerado com sucesso!")
    st.download_button(
        label="📥 Baixar Relatório PDF",
        data=pdf_buffer,
        file_name="Diario_Obra_RDV.pdf",
        mime="application/pdf"
    )
