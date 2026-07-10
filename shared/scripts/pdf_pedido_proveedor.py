"""Generador de PDF de pedido a proveedor.

Toma una lista de lineas {calidad, kg, eur_kg?, importe?} para un proveedor
y genera un PDF imprimible para enviar o adjuntar en email.

Paleta y estilo alineados con pdf_presupuesto.py de la calculadora (logo
Rols, colores tan/grafito, tipografias coherentes).
"""
from __future__ import annotations

import io
from datetime import datetime
from pathlib import Path

# reportlab OPCIONAL (solo para exportar el PDF). Si falta, el módulo se
# importa igual; solo falla al generar el PDF (ver guard en generar_pdf_*).
try:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer, Image, Table, TableStyle,
    )
    from reportlab.lib.enums import TA_LEFT, TA_RIGHT, TA_CENTER
    REPORTLAB_OK = True

    ROLS_TAN_DARK = colors.HexColor("#B89368")
    ROLS_SAND     = colors.HexColor("#FAF8F6")
    ROLS_BORDER   = colors.HexColor("#E5DCD2")
    TEXT_DARK     = colors.HexColor("#2a2a2a")
    TEXT_MUTED    = colors.HexColor("#7A7A7A")
except ImportError:
    REPORTLAB_OK = False

# Logo: intentamos rols-calculadora/static/logo-rols.png, sino fallback.
_HERE = Path(__file__).resolve().parent.parent
_LOGO_CANDIDATOS = [
    _HERE.parent / "rols-calculadora" / "static" / "logo-rols.png",
    _HERE.parent / "rols-consulta-stock" / "static" / "logo-rols.png",
    _HERE / "static" / "logo-rols.png",
]
LOGO_PATH = next((p for p in _LOGO_CANDIDATOS if p.exists()), None)


def _escape(s) -> str:
    """Escape minimo para los Paragraphs de reportlab (que parsean
    mini-HTML). Evita que un '&' o '<' inesperado rompa el PDF."""
    if s is None:
        return ""
    return (str(s)
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;"))


def _fmt_kg(v) -> str:
    if v in (None, ""):
        return "—"
    return f"{float(v):,.0f}".replace(",", ".") + " kg"


def _fmt_eur(v) -> str:
    if v in (None, ""):
        return "—"
    return f"{float(v):,.2f}".replace(",", "@").replace(".", ",").replace("@", ".") + " €"


def _fmt_eur_kg(v) -> str:
    if v in (None, ""):
        return "—"
    return f"{float(v):,.2f}".replace(",", "@").replace(".", ",").replace("@", ".") + " €/kg"


def generar_pdf_pedido(proveedor: str, lineas: list[dict],
                       ref_pedido: str = "", nota: str = "",
                       proveedor_data: dict | None = None) -> bytes:
    """Genera el PDF y devuelve los bytes.

    `lineas`: cada item lleva al menos {titulo, tipo, kg}; opcionalmente
    {eur_kg, importe, observaciones}.

    `proveedor_data` (opcional): ficha completa del proveedor con razon
    social, CIF, direccion, persona y email. Si se pasa, se incluye un
    bloque con sus datos en la cabecera del PDF (asi el destinatario es
    explicito y se ve mas profesional). Si no, solo aparece el nombre.
    """
    if not REPORTLAB_OK:
        raise RuntimeError(
            "La exportación a PDF no está disponible: falta 'reportlab' en el "
            "servidor. Instálala con `.venv/bin/pip install reportlab`."
        )
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=18 * mm, rightMargin=18 * mm,
        topMargin=15 * mm, bottomMargin=15 * mm,
        title=f"Pedido {ref_pedido} - {proveedor}",
        author="Moquetas Rols S.A.",
    )

    styles = getSampleStyleSheet()
    st_h1 = ParagraphStyle("h1", parent=styles["Heading1"],
                           fontSize=22, leading=26, textColor=TEXT_DARK,
                           spaceBefore=0, spaceAfter=2, fontName="Helvetica-Bold")
    st_h2 = ParagraphStyle("h2", parent=styles["Normal"],
                           fontSize=11, leading=14, textColor=ROLS_TAN_DARK,
                           fontName="Helvetica-Bold")
    st_meta_label = ParagraphStyle("meta-label", parent=styles["Normal"],
                                   fontSize=7, leading=9, textColor=TEXT_MUTED,
                                   fontName="Helvetica-Bold", alignment=TA_RIGHT)
    st_meta_value = ParagraphStyle("meta-value", parent=styles["Normal"],
                                   fontSize=10, leading=12, textColor=TEXT_DARK,
                                   alignment=TA_RIGHT)
    st_label = ParagraphStyle("label", parent=styles["Normal"],
                              fontSize=8, leading=10, textColor=TEXT_MUTED,
                              fontName="Helvetica-Bold")
    st_cell = ParagraphStyle("cell", parent=styles["Normal"],
                             fontSize=9, leading=12, textColor=TEXT_DARK)
    st_cell_right = ParagraphStyle("cell-right", parent=st_cell, alignment=TA_RIGHT)
    st_cell_th = ParagraphStyle("cell-th", parent=st_cell,
                                fontName="Helvetica-Bold", textColor=TEXT_MUTED,
                                fontSize=7.5)
    st_cell_th_right = ParagraphStyle("cell-th-right", parent=st_cell_th, alignment=TA_RIGHT)
    st_total_label = ParagraphStyle("total-label", parent=styles["Normal"],
                                    fontSize=10, leading=14, textColor=TEXT_DARK,
                                    fontName="Helvetica-Bold")
    st_total_value = ParagraphStyle("total-value", parent=st_total_label, alignment=TA_RIGHT)
    st_footer = ParagraphStyle("footer", parent=styles["Normal"],
                               fontSize=7, leading=10, textColor=TEXT_MUTED, alignment=TA_CENTER)

    flow = []

    # --- Cabecera ---
    logo = None
    if LOGO_PATH and LOGO_PATH.exists():
        logo = Image(str(LOGO_PATH), width=35 * mm, height=14 * mm, kind="proportional")

    fecha_hoy = datetime.now().strftime("%d/%m/%Y")

    meta_table = Table([
        [Paragraph("Fecha", st_meta_label), Paragraph(fecha_hoy, st_meta_value)],
        [Paragraph("Referencia", st_meta_label),
         Paragraph(ref_pedido or "—", st_meta_value)],
        [Paragraph("Proveedor", st_meta_label),
         Paragraph(proveedor or "—", st_meta_value)],
    ], colWidths=[30 * mm, 45 * mm])
    meta_table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
        ("TOPPADDING", (0, 0), (-1, -1), 1),
    ]))

    header_left_cells = [Paragraph("PEDIDO MATERIA PRIMA", st_h1)]
    if logo:
        header_left_cells.insert(0, logo)
        header_left_cells.insert(1, Spacer(1, 4 * mm))

    header_table = Table(
        [[header_left_cells, meta_table]],
        colWidths=[105 * mm, 70 * mm],
    )
    header_table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
    ]))
    flow.append(header_table)
    flow.append(Spacer(1, 6 * mm))

    # --- Datos remitente (Rols) y destinatario (proveedor) en 2 columnas ---
    st_blk_label = ParagraphStyle("blk-label", parent=styles["Normal"],
                                  fontSize=7, leading=9, textColor=TEXT_MUTED,
                                  fontName="Helvetica-Bold")
    st_blk_text = ParagraphStyle("blk-text", parent=styles["Normal"],
                                 fontSize=8.5, leading=11.5, textColor=TEXT_DARK)
    rols_block = [
        Paragraph("REMITE", st_blk_label),
        Paragraph(
            "<b>Moquetas Rols, S.A.</b><br/>"
            "Polígono Industrial Mas d'En Cisa<br/>"
            "C/ del Carrer, s/n · 08800 Sant Pere de Ribes (Barcelona)<br/>"
            "Tel. +34 938 962 100 · pedidos@rolscarpets.com",
            st_blk_text),
    ]
    # Destinatario: si tenemos ficha del proveedor, usamos sus datos;
    # si no, solo el nombre.
    if proveedor_data:
        razon = proveedor_data.get("razon_social") or proveedor or "—"
        cif = proveedor_data.get("cif") or ""
        partes_dir = [
            proveedor_data.get("direccion"),
            " · ".join(p for p in [
                proveedor_data.get("cp"),
                proveedor_data.get("ciudad"),
                proveedor_data.get("provincia"),
            ] if p),
            proveedor_data.get("pais"),
        ]
        dir_txt = "<br/>".join(p for p in partes_dir if p)
        contacto_partes = []
        if proveedor_data.get("contacto_persona"):
            contacto_partes.append("A/A " + proveedor_data["contacto_persona"])
        if proveedor_data.get("contacto_email"):
            contacto_partes.append(proveedor_data["contacto_email"])
        if proveedor_data.get("contacto_telefono"):
            contacto_partes.append("Tel. " + proveedor_data["contacto_telefono"])
        contacto_txt = " · ".join(contacto_partes)
        dest_html = (f"<b>{_escape(razon)}</b>"
                     + (f" · CIF {_escape(cif)}" if cif else "")
                     + ("<br/>" + dir_txt if dir_txt else "")
                     + ("<br/>" + _escape(contacto_txt) if contacto_txt else ""))
    else:
        dest_html = f"<b>{_escape(proveedor or '—')}</b>"
    dest_block = [
        Paragraph("DESTINATARIO", st_blk_label),
        Paragraph(dest_html, st_blk_text),
    ]
    partes_tbl = Table([[rols_block, dest_block]],
                       colWidths=[85 * mm, 90 * mm])
    partes_tbl.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (0, 0), 8),
        ("RIGHTPADDING", (1, 0), (-1, -1), 0),
    ]))
    flow.append(partes_tbl)
    flow.append(Spacer(1, 8 * mm))

    # --- Tabla de líneas ---
    # Si alguna linea trae partido_previsto, añadimos esa columna; si
    # no, omitimos para no ensuciar el PDF con una columna vacia.
    mostrar_partido = any((ln.get("partido_previsto") or "").strip() for ln in lineas)

    head = [
        Paragraph("CALIDAD", st_cell_th),
        Paragraph("TIPO", st_cell_th),
    ]
    if mostrar_partido:
        head.append(Paragraph("PARTIDO", st_cell_th))
    head.extend([
        Paragraph("CANTIDAD", st_cell_th_right),
        Paragraph("PRECIO €/KG", st_cell_th_right),
        Paragraph("IMPORTE", st_cell_th_right),
    ])
    rows = [head]
    total_kg = 0.0
    total_importe = 0.0
    importe_conocido = False
    for ln in lineas:
        kg = float(ln.get("kg") or 0)
        eur_kg = ln.get("eur_kg")
        importe = ln.get("importe")
        if importe is None and eur_kg is not None:
            importe = kg * float(eur_kg)
        total_kg += kg
        if importe is not None:
            total_importe += float(importe)
            importe_conocido = True
        row = [
            Paragraph(ln.get("titulo") or "—", st_cell),
            Paragraph(ln.get("tipo") or "—", st_cell),
        ]
        if mostrar_partido:
            row.append(Paragraph(ln.get("partido_previsto") or "—", st_cell))
        row.extend([
            Paragraph(_fmt_kg(kg), st_cell_right),
            Paragraph(_fmt_eur_kg(eur_kg), st_cell_right),
            Paragraph(_fmt_eur(importe), st_cell_right),
        ])
        rows.append(row)

    col_widths = ([35 * mm, 55 * mm]
                  + ([22 * mm] if mostrar_partido else [])
                  + [25 * mm, 25 * mm, 30 * mm])
    tabla = Table(rows, colWidths=col_widths, repeatRows=1)
    tabla.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), ROLS_SAND),
        ("LINEBELOW", (0, 0), (-1, 0), 0.6, ROLS_BORDER),
        ("LINEBELOW", (0, -1), (-1, -1), 0.4, ROLS_BORDER),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, ROLS_SAND]),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    flow.append(tabla)
    flow.append(Spacer(1, 5 * mm))

    # --- Totales ---
    rows_totales = [[
        Paragraph("Total kg", st_total_label),
        Paragraph(_fmt_kg(total_kg), st_total_value),
    ]]
    if importe_conocido:
        rows_totales.append([
            Paragraph("Importe estimado", st_total_label),
            Paragraph(_fmt_eur(total_importe), st_total_value),
        ])
    totales = Table(rows_totales, colWidths=[40 * mm, 30 * mm],
                    hAlign="RIGHT")
    totales.setStyle(TableStyle([
        ("LINEABOVE", (0, 0), (-1, 0), 0.8, ROLS_TAN_DARK),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    flow.append(totales)

    if nota:
        flow.append(Spacer(1, 8 * mm))
        flow.append(Paragraph("NOTAS", st_h2))
        flow.append(Paragraph(nota.replace("\n", "<br/>"),
                              ParagraphStyle("nota", parent=styles["Normal"],
                                             fontSize=9, leading=12,
                                             textColor=TEXT_DARK)))

    flow.append(Spacer(1, 10 * mm))
    flow.append(Paragraph(
        "Por favor, confirmen recepción del pedido y fecha estimada de entrega. "
        "Gracias.", st_footer))

    doc.build(flow)
    return buf.getvalue()
