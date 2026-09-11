"""Resumen de una muestra fabricada en PDF (A4, una hoja).

Pensado para imprimirlo y meterlo en la caja de la muestra física: quién la
pidió, para quién, qué es, sus datos técnicos y el diario del laboratorio. El
QR de la cabecera abre la ficha en el ERP.

Mismo estilo que `pdf_pedido_proveedor.py` (logo Rols, paleta tan/grafito).
"""
from __future__ import annotations

import io
from datetime import datetime
from pathlib import Path

import muestras_fabricadas as mf

# reportlab es OPCIONAL: el modulo se importa igual y solo falla al generar
# (mismo criterio que pdf_pedido_proveedor).
try:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.lib.enums import TA_CENTER, TA_RIGHT
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer, Image, Table, TableStyle, KeepTogether,
    )
    REPORTLAB_OK = True

    ROLS_TAN_DARK = colors.HexColor("#B89368")
    ROLS_ACCENT = colors.HexColor("#D5B38C")
    ROLS_SAND = colors.HexColor("#FAF8F6")
    ROLS_BORDER = colors.HexColor("#E5DCD2")
    TEXT_DARK = colors.HexColor("#2a2a2a")
    TEXT_MUTED = colors.HexColor("#7A7A7A")
except ImportError:  # pragma: no cover - solo si falta la dependencia
    REPORTLAB_OK = False

_HERE = Path(__file__).resolve().parent.parent          # .../shared
_LOGO_CANDIDATOS = [
    _HERE.parent / "static" / "logo-rols.png",          # el del ERP
    _HERE / "static" / "logo-rols.png",
]
LOGO_PATH = next((p for p in _LOGO_CANDIDATOS if p.exists()), None)

MAX_APUNTES = 14          # el diario entero no cabe: se enseñan los ultimos


def _esc(s) -> str:
    """Escape minimo: los Paragraph de reportlab parsean mini-HTML."""
    if s is None:
        return ""
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _fecha(iso) -> str:
    if not iso:
        return "—"
    try:
        return datetime.strptime(str(iso)[:10], "%Y-%m-%d").strftime("%d/%m/%Y")
    except ValueError:
        return str(iso)


def _qr(url: str, lado_mm: float = 24):
    """Dibujo del QR que abre la ficha; None si reportlab no trae el modulo."""
    if not url:
        return None
    try:
        from reportlab.graphics.barcode import qr
        from reportlab.graphics.shapes import Drawing
    except ImportError:
        return None
    lado = lado_mm * mm
    widget = qr.QrCodeWidget(url, barLevel="M")
    x0, y0, x1, y1 = widget.getBounds()
    d = Drawing(lado, lado, transform=[lado / (x1 - x0), 0, 0, lado / (y1 - y0), 0, 0])
    d.add(widget)
    return d


def generar_pdf_muestra(m: dict, base_url: str = "") -> bytes:
    """Genera el PDF de la ficha `m` (la que devuelve `muestras_fabricadas.obtener`)
    y devuelve los bytes."""
    if not REPORTLAB_OK:
        raise RuntimeError(
            "La exportación a PDF no está disponible: falta 'reportlab' en el "
            "servidor. Instálala con `.venv/bin/pip install reportlab`."
        )
    mid = m.get("id") or ""
    telar = m.get("telar") or ""
    url = f"{(base_url or '').rstrip('/')}/muestras-fabricadas/{mid}" if base_url else ""

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=16 * mm, rightMargin=16 * mm, topMargin=13 * mm, bottomMargin=13 * mm,
        title=f"Muestra M-{mid}", author="Moquetas Rols S.A.",
    )
    ancho = doc.width

    styles = getSampleStyleSheet()
    st_num = ParagraphStyle("num", parent=styles["Normal"], fontName="Helvetica-Bold",
                            fontSize=30, leading=32, textColor=TEXT_DARK)
    st_cliente = ParagraphStyle("cliente", parent=styles["Normal"], fontName="Helvetica-Bold",
                                fontSize=15, leading=18, textColor=TEXT_DARK)
    st_ref = ParagraphStyle("ref", parent=styles["Normal"], fontSize=11, leading=14,
                            textColor=ROLS_TAN_DARK)
    st_seccion = ParagraphStyle("seccion", parent=styles["Normal"], fontName="Helvetica-Bold",
                                fontSize=8, leading=10, textColor=ROLS_TAN_DARK)
    st_label = ParagraphStyle("label", parent=styles["Normal"], fontName="Helvetica-Bold",
                              fontSize=7, leading=9, textColor=TEXT_MUTED)
    st_valor = ParagraphStyle("valor", parent=styles["Normal"], fontSize=9.5, leading=12,
                              textColor=TEXT_DARK)
    st_texto = ParagraphStyle("texto", parent=styles["Normal"], fontSize=9, leading=12.5,
                              textColor=TEXT_DARK)
    st_th = ParagraphStyle("th", parent=styles["Normal"], fontName="Helvetica-Bold",
                           fontSize=7, leading=9, textColor=TEXT_MUTED)
    st_td = ParagraphStyle("td", parent=styles["Normal"], fontSize=8.5, leading=11,
                           textColor=TEXT_DARK)
    st_fecha_ap = ParagraphStyle("fecha-ap", parent=st_td, fontName="Helvetica-Bold",
                                 textColor=ROLS_TAN_DARK)
    st_pie = ParagraphStyle("pie", parent=styles["Normal"], fontSize=7, leading=9.5,
                            textColor=TEXT_MUTED, alignment=TA_CENTER)
    st_qr_pie = ParagraphStyle("qr-pie", parent=styles["Normal"], fontSize=6, leading=8,
                               textColor=TEXT_MUTED, alignment=TA_CENTER)

    flow = []

    # ---------------------------------------------------------------- cabecera
    izq = []
    if LOGO_PATH:
        izq.append(Image(str(LOGO_PATH), width=30 * mm, height=12 * mm, kind="proportional"))
        izq.append(Spacer(1, 3 * mm))
    izq.append(Paragraph("MUESTRA FABRICADA", st_seccion))
    izq.append(Paragraph(f"M-{_esc(mid)}", st_num))
    interna = (m.get("tipo") or "cliente") == "interna"
    cliente = m.get("cliente") or ("Interna" if interna else "—")
    izq.append(Paragraph(_esc(cliente) + (" · interna" if interna else ""), st_cliente))
    if m.get("referencia"):
        izq.append(Spacer(1, 1 * mm))
        izq.append(Paragraph(_esc(m["referencia"]), st_ref))

    qr_d = _qr(url)
    der = []
    if qr_d is not None:
        der = [qr_d, Spacer(1, 1 * mm), Paragraph("Abre la ficha", st_qr_pie)]

    flow.append(Table([[izq, der]], colWidths=[ancho - 28 * mm, 28 * mm],
                      style=TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"),
                                        ("ALIGN", (1, 0), (1, 0), "CENTER"),
                                        ("LEFTPADDING", (0, 0), (-1, -1), 0),
                                        ("RIGHTPADDING", (0, 0), (-1, -1), 0)])))
    flow.append(Spacer(1, 5 * mm))

    # -------------------------------------------------------------- los datos
    def par(label, valor):
        return [Paragraph(_esc(label), st_label), Paragraph(_esc(valor) or "—", st_valor)]

    terminal = (m.get("estado") or "") in mf.ESTADOS_TERMINALES
    filas = [
        par("Solicitada", _fecha(m.get("fecha_solicitud"))) + par("Estado", m.get("estado_label")),
        par("Encargada por", m.get("encargada_por")) + par("Prioridad", mf.PRIORIDADES.get(m.get("prioridad") or 0, "—")),
        par("Telar / técnica", telar) + par(
            "Muestra lista" if terminal else "Lista prevista",
            _fecha(m.get("fecha_lista") if terminal else m.get("fecha_estimada"))),
    ]
    if m.get("cliente_navision") or m.get("proximo_hito_fecha"):
        hito = _fecha(m.get("proximo_hito_fecha"))
        if m.get("proximo_hito"):
            hito += f" · {m['proximo_hito']}"
        filas.append(par("Cliente Navision", m.get("cliente_navision"))
                     + par("Próximo hito", hito if m.get("proximo_hito_fecha") else "—"))
    col = (ancho - 4 * mm) / 2
    tabla_datos = Table(filas, colWidths=[26 * mm, col - 26 * mm, 26 * mm, col - 26 * mm])
    tabla_datos.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LINEBELOW", (0, 0), (-1, -2), 0.4, ROLS_BORDER),
    ]))
    flow.append(tabla_datos)
    flow.append(Spacer(1, 5 * mm))

    # ------------------------------------------------------- datos de tejeduria
    def seccion(titulo, contenido, hint=""):
        cab = Paragraph(_esc(titulo) + (f'  <font color="#9a9a9a">{_esc(hint)}</font>' if hint else ""), st_seccion)
        flow.append(KeepTogether([cab, Spacer(1, 1.5 * mm)] + contenido + [Spacer(1, 4 * mm)]))

    if mf.lleva_tejeduria(telar):
        tej = [("Pasadas", m.get("pasadas")), ("Altura felpa", m.get("altura_felpa")),
               (mf.etiqueta_n_cuerpos(telar), m.get("n_cuerpos")),
               ("Construcción", mf.PELOS_LABEL.get(m.get("pelo"), m.get("pelo"))),
               ("Acabado", mf.ACABADOS_LABEL.get(m.get("acabado"), m.get("acabado")))]
        celdas = [[Paragraph(_esc(k), st_label) for k, _ in tej],
                  [Paragraph(_esc(v) or "—", st_valor) for _, v in tej]]
        t = Table(celdas, colWidths=[ancho / len(tej)] * len(tej))
        t.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"), ("BACKGROUND", (0, 0), (-1, -1), ROLS_SAND),
            ("BOX", (0, 0), (-1, -1), 0.5, ROLS_BORDER),
            ("LEFTPADDING", (0, 0), (-1, -1), 5), ("RIGHTPADDING", (0, 0), (-1, -1), 5),
            ("TOPPADDING", (0, 0), (-1, 0), 5), ("BOTTOMPADDING", (0, 1), (-1, 1), 5),
        ]))
        seccion("DATOS DE TEJEDURÍA", [t])

    # -------------------------------------------------------- datos de materias
    materias = [f for f in (m.get("materias") or [])
                if any((f.get(k) or "").strip() for k in ("materia", "hilos_pua", "colorido"))]
    if materias:
        con_hilos = mf.lleva_hilos_pua(telar)
        cab = [mf.etiqueta_cuerpo(telar), "Materia"] + (["Hilos púa"] if con_hilos else []) + ["Colorido"]
        filas_m = [[Paragraph(_esc(x), st_th) for x in cab]]
        for f in materias:
            fila = [f.get("cuerpo"), f.get("materia")] + ([f.get("hilos_pua")] if con_hilos else []) + [f.get("colorido")]
            filas_m.append([Paragraph(_esc(x) or "—", st_td) for x in fila])
        anchos = ([20 * mm, ancho - 105 * mm, 20 * mm, 65 * mm] if con_hilos
                  else [20 * mm, ancho - 85 * mm, 65 * mm])
        t = Table(filas_m, colWidths=anchos, repeatRows=1)
        t.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LINEBELOW", (0, 0), (-1, 0), 0.6, ROLS_BORDER),
            ("LINEBELOW", (0, 1), (-1, -2), 0.3, ROLS_BORDER),
            ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ("TOPPADDING", (0, 0), (-1, -1), 3.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 3.5),
        ]))
        seccion("DATOS DE MATERIAS", [t])

    # ------------------------------------------------------------- descripcion
    if (m.get("descripcion") or "").strip():
        seccion("DESCRIPCIÓN DE LA MUESTRA",
                [Paragraph(_esc(m["descripcion"]).replace("\n", "<br/>"), st_texto)])

    if (m.get("resultado") or "").strip():
        seccion("RESULTADO (COMERCIAL)",
                [Paragraph(_esc(m["resultado"]).replace("\n", "<br/>"), st_texto)])

    # ------------------------------------------------------------------ diario
    apuntes = m.get("apuntes") or []
    if apuntes:
        recortado = len(apuntes) > MAX_APUNTES
        ultimos = apuntes[-MAX_APUNTES:]
        filas_d = []
        for a in ultimos:
            quien = a.get("usuario_nombre") or ""
            txt = _esc(a.get("texto"))
            if quien:
                txt += f'  <font size="7" color="#9a9a9a">— {_esc(quien)}</font>'
            filas_d.append([Paragraph(_fecha(a.get("fecha")) if a.get("fecha") else "s/f", st_fecha_ap),
                            Paragraph(txt, st_td)])
        t = Table(filas_d, colWidths=[22 * mm, ancho - 22 * mm])
        t.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 2),
            ("TOPPADDING", (0, 0), (-1, -1), 2.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
            ("LINEBELOW", (0, 0), (-1, -2), 0.3, ROLS_BORDER),
        ]))
        hint = f"los {len(ultimos)} últimos de {len(apuntes)}" if recortado else ""
        seccion("DIARIO DEL LABORATORIO", [t], hint)

    # -------------------------------------------------------------------- pie
    pie = f"Impreso el {datetime.now().strftime('%d/%m/%Y %H:%M')} · Rols Producción · Muestras fabricadas"
    if url:
        pie += f"<br/>{_esc(url)}"
    flow.append(Spacer(1, 2 * mm))
    flow.append(Paragraph(pie, st_pie))

    doc.build(flow)
    return buf.getvalue()
