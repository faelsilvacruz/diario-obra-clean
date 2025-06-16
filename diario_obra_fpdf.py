import os
import io
from datetime import datetime
from fpdf import FPDF

LOGO_PDF_PATH = "LOGO_RDV_AZUL.png"

class DiarioObraPDF(FPDF):
    def header(self):
        self.set_fill_color(15, 42, 77)
        self.rect(0, 0, self.w, 35, 'F')
        if os.path.exists(LOGO_PDF_PATH):
            self.image(LOGO_PDF_PATH, 12, 8, 19, 13)
        self.set_xy(0, 10)
        self.set_font('Arial', 'B', 17)
        self.set_text_color(255, 255, 255)
        self.cell(self.w, 10, 'DIÁRIO DE OBRA', border=0, ln=2, align='C')
        self.set_font('Arial', 'B', 12)
        self.cell(self.w, 7, 'RDV ENGENHARIA', border=0, ln=1, align='C')
        self.ln(7)

    def footer(self):
        self.set_y(-15)
        self.set_font('Arial', 'I', 8)
        self.set_text_color(130, 130, 130)
        self.cell(0, 6, f'Gerado em: {datetime.now().strftime("%d/%m/%Y %H:%M")} - Página {self.page_no()}', 0, 0, 'R')

def gerar_pdf_fpdf(dados_obra, colaboradores, maquinas, servicos, controle_doc, intercorrencias, responsavel, fiscal, clima, fotos_paths=None):
    pdf = DiarioObraPDF()
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=20)

    # --- Dados da Obra ---
    pdf.set_font('Arial', 'B', 11)
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
        pdf.set_font('Arial', '', 11)
        pdf.cell(80, 8, valor, 0, 1)
        pdf.set_font('Arial', 'B', 11)

    # --- Serviços Executados ---
    pdf.ln(3)
    pdf.set_fill_color(220, 230, 242)
    pdf.cell(0, 7, 'SERVIÇOS EXECUTADOS:', 0, 1, 'L', True)
    pdf.set_font('Arial', '', 10)
    pdf.multi_cell(0, 7, servicos.strip() if servicos.strip() else "Nenhum serviço informado.", 0, 1)

    # --- Máquinas e Equipamentos ---
    pdf.ln(2)
    pdf.set_font('Arial', 'B', 11)
    pdf.cell(0, 7, 'MÁQUINAS/EQUIPAMENTOS:', 0, 1, 'L', True)
    pdf.set_font('Arial', '', 10)
    pdf.multi_cell(0, 7, maquinas.strip() if maquinas.strip() else "Nenhuma máquina/equipamento informado.", 0, 1)

    # --- Efetivo de Pessoal ---
    pdf.ln(2)
    pdf.set_font('Arial', 'B', 11)
    pdf.cell(0, 7, 'EFETIVO DE PESSOAL', 0, 1, 'L', True)
    pdf.set_fill_color(15, 42, 77)
    pdf.set_text_color(255, 255, 255)
    pdf.set_font('Arial', 'B', 10)
    pdf.cell(70, 8, 'NOME', 1, 0, 'C', True)
    pdf.cell(40, 8, 'FUNÇÃO', 1, 0, 'C', True)
    pdf.cell(30, 8, 'ENTRADA', 1, 0, 'C', True)
    pdf.cell(30, 8, 'SAÍDA', 1, 1, 'C', True)
    pdf.set_text_color(0, 0, 0)
    pdf.set_font('Arial', '', 9)
    for row in colaboradores:
        pdf.cell(70, 8, row[0], 1)
        pdf.cell(40, 8, row[1], 1)
        pdf.cell(30, 8, row[2], 1)
        pdf.cell(30, 8, row[3], 1)
        pdf.ln()
    pdf.ln(2)

    # --- Controle de Documentação de Segurança ---
    pdf.set_font('Arial', 'B', 11)
    pdf.set_fill_color(220, 230, 242)
    pdf.cell(0, 7, 'CONTROLE DE DOCUMENTAÇÃO DE SEGURANÇA:', 0, 1, 'L', True)
    pdf.set_font('Arial', '', 10)
    pdf.multi_cell(0, 7, controle_doc.strip() if controle_doc.strip() else "Não informado.", 0, 1)
    pdf.ln(2)

    # --- Intercorrências ---
    pdf.set_font('Arial', 'B', 11)
    pdf.set_fill_color(220, 230, 242)
    pdf.cell(0, 7, 'INTERCORRÊNCIAS:', 0, 1, 'L', True)
    pdf.set_font('Arial', '', 10)
    pdf.multi_cell(0, 7, intercorrencias.strip() if intercorrencias.strip() else "Sem intercorrências.", 0, 1)
    pdf.ln(2)

    # --- Assinaturas ---
    pdf.set_font('Arial', 'B', 11)
    pdf.set_fill_color(220, 230, 242)
    pdf.cell(0, 7, 'ASSINATURAS:', 0, 1, 'L', True)
    pdf.ln(10)

    largura_linha = 60
    distancia_entre = 45
    largura_total = (2 * largura_linha) + distancia_entre
    x_inicio = (pdf.w - largura_total) / 2
    y_assin = pdf.get_y()
    pdf.set_draw_color(70, 70, 70)
    pdf.line(x_inicio, y_assin, x_inicio + largura_linha, y_assin)
    pdf.line(x_inicio + largura_linha + distancia_entre, y_assin, x_inicio + 2 * largura_linha + distancia_entre, y_assin)

    espaco_vertical = 3
    pdf.set_font('Arial', '', 11)
    pdf.set_xy(x_inicio, y_assin + espaco_vertical)
    pdf.cell(largura_linha, 7, "Responsável Técnico:", 0, 2, 'C')
    pdf.cell(largura_linha, 7, f"Nome: {responsavel}", 0, 0, 'C')

    pdf.set_xy(x_inicio + largura_linha + distancia_entre, y_assin + espaco_vertical)
    pdf.cell(largura_linha, 7, "Fiscalização:", 0, 2, 'C')
    pdf.cell(largura_linha, 7, f"Nome: {fiscal}", 0, 0, 'C')
    pdf.ln(20)

    # --- Fotos (cada uma em nova página) ---
    if fotos_paths:
        for path in fotos_paths:
            if os.path.exists(path):
                pdf.add_page()
                pdf.set_font('Arial', 'B', 12)
                pdf.cell(0, 10, f'Foto: {os.path.basename(path)}', 0, 1)
                pdf.image(path, x=30, w=150)

    # Retorno do PDF em buffer
    pdf_buffer = io.BytesIO(pdf.output(dest='S').encode('latin1'))
    return pdf_buffer
