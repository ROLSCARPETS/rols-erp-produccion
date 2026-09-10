"""Avisos por correo de Muestras fabricadas, a quien encargo la muestra.

Tres disparadores (los pidio el usuario, sept 2026):
  - cambia de etapa (estado)                      → aviso_cambio_estado
  - se marca terminada o cancelada                → aviso_cambio_estado (mismo camino, otro asunto)
  - llega la fecha del proximo hito               → chequear_hitos (una vez por fecha)

Reglas:
  - Destinatario: `encargada_por_usuario` → su e-mail segun el directorio de
    cuentas (snapshot guardado en el documento) o, si el usuario ya es un
    e-mail (fernando@rolscarpets.com), ese mismo.
  - No se avisa a quien hace el cambio (ya lo sabe).
  - Cada intento queda en el historial de la muestra (tipo "aviso", ok/error).
  - Best-effort: sin correo configurado no se hace nada; un fallo de SMTP se
    apunta en el historial y no afecta a la operacion.
"""
from __future__ import annotations

import html as _html
import logging
from datetime import date, datetime

import correo
import muestras_fabricadas as mf

log = logging.getLogger("muestras.avisos")

_FLUJO_ORDEN = {s: i for i, s in enumerate(mf.ESTADOS_FLUJO)}


# ---------------------------------------------------------------------------
# Destinatarios
# ---------------------------------------------------------------------------

def email_de_usuario(usuario: str | None, directorio) -> tuple[str, str]:
    """(email, nombre) del usuario segun el directorio [{username, nombre, email}].
    Si el username ya es un e-mail y no esta en el directorio, se usa tal cual."""
    u = (usuario or "").strip().lower()
    if not u:
        return "", ""
    for p in (directorio or []):
        if not isinstance(p, dict):
            continue
        if (p.get("username") or p.get("usuario") or "").strip().lower() == u:
            email = (p.get("email") or "").strip().lower()
            if not email and "@" in u:
                email = u
            return email, (p.get("nombre") or "").strip()
    if "@" in u:
        return u, ""
    return "", ""


# ---------------------------------------------------------------------------
# Plantillas
# ---------------------------------------------------------------------------

def _fmt_fecha(iso: str | None) -> str:
    if not iso:
        return ""
    try:
        return datetime.strptime(iso[:10], "%Y-%m-%d").strftime("%d/%m/%Y")
    except ValueError:
        return iso


def _url_ficha(base_url: str, mid: str) -> str:
    from urllib.parse import quote
    return f"{(base_url or '').rstrip('/')}/muestras-fabricadas/{quote(mid, safe='')}"


def _cabecera(m: dict) -> str:
    cliente = m.get("cliente") or ("Interna" if m.get("tipo") == "interna" else "—")
    return f"M-{m.get('id')} · {cliente}"


def _bloque_datos(m: dict) -> list[tuple[str, str]]:
    filas = [("Cliente", (m.get("cliente") or "") + ("  (interna)" if m.get("tipo") == "interna" else ""))]
    if m.get("descripcion"):
        filas.append(("Muestra", mf._recortar(m.get("descripcion"), 300)))
    if m.get("telar"):
        filas.append(("Telar / técnica", m["telar"]))
    filas.append(("Prioridad", mf.PRIORIDADES.get(m.get("prioridad") or 0, "—")))
    if m.get("fecha_solicitud"):
        filas.append(("Solicitada", _fmt_fecha(m["fecha_solicitud"])))
    if m.get("fecha_estimada") and m.get("estado") not in mf.ESTADOS_TERMINALES:
        filas.append(("Lista prevista", _fmt_fecha(m["fecha_estimada"])))
    if m.get("proximo_hito_fecha"):
        filas.append(("Próximo hito", _fmt_fecha(m["proximo_hito_fecha"])
                      + (f" — {m['proximo_hito']}" if m.get("proximo_hito") else "")))
    return filas


def _render(titulo: str, lineas: list[str], m: dict, base_url: str, nombre_dest: str) -> tuple[str, str]:
    """(texto, html) con el mismo contenido."""
    url = _url_ficha(base_url, m.get("id") or "")
    saludo = f"Hola {nombre_dest.split(' ')[0]}," if nombre_dest else "Hola,"
    datos = _bloque_datos(m)
    texto = "\n".join([saludo, "", titulo, *lineas, "",
                       *[f"{k}: {v}" for k, v in datos], "",
                       f"Ficha: {url}", "",
                       "— Rols Producción · Muestras fabricadas (aviso automático)"])
    e = _html.escape
    filas_html = "".join(
        f"<tr><td style='padding:4px 12px 4px 0;color:#7a7a7a;white-space:nowrap;vertical-align:top'>{e(k)}</td>"
        f"<td style='padding:4px 0;color:#2a2a2a'>{e(v)}</td></tr>" for k, v in datos)
    lineas_html = "".join(f"<p style='margin:6px 0;color:#2a2a2a'>{e(l)}</p>" for l in lineas)
    html = f"""<!doctype html><html><body style="margin:0;padding:0;background:#faf8f6;font-family:Inter,'Segoe UI',Arial,sans-serif">
<div style="max-width:640px;margin:0 auto;padding:24px 16px">
  <div style="background:#fff;border:1px solid #e5dcd2;border-radius:14px;padding:22px 26px">
    <div style="font-size:11px;letter-spacing:.14em;text-transform:uppercase;color:#b89368;font-weight:700;margin-bottom:10px">Rols Producción · Muestras fabricadas</div>
    <p style="margin:0 0 12px;color:#2a2a2a">{e(saludo)}</p>
    <h2 style="margin:0 0 10px;font-size:18px;font-weight:600;color:#2a2a2a">{e(titulo)}</h2>
    {lineas_html}
    <table style="border-collapse:collapse;margin:14px 0;font-size:14px">{filas_html}</table>
    <p style="margin:16px 0 0"><a href="{e(url)}" style="display:inline-block;background:#d5b38c;color:#fff;text-decoration:none;padding:9px 16px;border-radius:999px;font-weight:600">Abrir la ficha M-{e(m.get('id') or '')}</a></p>
  </div>
  <p style="font-size:11px;color:#9a9a9a;margin:12px 4px 0">Aviso automático a quien encargó la muestra. Se envía al cambiar de etapa, al terminar o cancelar, y el día del próximo hito.</p>
</div></body></html>"""
    return texto, html


def _asunto_estado(m: dict, nuevo: str) -> str:
    cab = _cabecera(m)
    if nuevo == "terminada":
        return f"[Muestras] {cab} · TERMINADA" + (f" (lista el {_fmt_fecha(m.get('fecha_lista'))})" if m.get("fecha_lista") else "")
    if nuevo == "cancelada":
        return f"[Muestras] {cab} · CANCELADA"
    return f"[Muestras] {cab} · ahora en {mf.ESTADOS_LABEL.get(nuevo, nuevo)}"


# ---------------------------------------------------------------------------
# Disparadores
# ---------------------------------------------------------------------------

def aviso_cambio_estado(mid: str, anterior: str, nuevo: str, actor, nota: str,
                        directorio, base_url: str) -> dict:
    """Avisa a quien encargo la muestra de que ha cambiado de etapa (o se ha
    terminado/cancelado). Devuelve {"enviado": bool, "motivo": str}."""
    if anterior == nuevo:
        return {"enviado": False, "motivo": "sin cambio"}
    if not correo.configurado():
        return {"enviado": False, "motivo": "correo no configurado"}
    m = mf.obtener(mid)
    if not m:
        return {"enviado": False, "motivo": "muestra no existe"}
    actor_u = (actor.get("username") if isinstance(actor, dict) else actor) or ""
    actor_n = (actor.get("nombre") if isinstance(actor, dict) else "") or actor_u
    dest_u = (m.get("encargada_por_usuario") or "").strip().lower()
    if not dest_u:
        return {"enviado": False, "motivo": "la muestra no tiene usuario que la encargue"}
    if dest_u == str(actor_u).strip().lower():
        return {"enviado": False, "motivo": "el cambio lo hace quien la encargó"}
    email, nombre = email_de_usuario(dest_u, directorio)
    nombre = nombre or m.get("encargada_por") or dest_u
    motivo = "terminada" if nuevo == "terminada" else ("cancelada" if nuevo == "cancelada" else "estado")
    if not email:
        mf.registrar_aviso(mid, motivo, dest_u, False, "sin e-mail conocido para el usuario")
        return {"enviado": False, "motivo": "sin e-mail"}
    de_lbl = mf.ESTADOS_LABEL.get(anterior, anterior or "—")
    a_lbl = mf.ESTADOS_LABEL.get(nuevo, nuevo)
    if nuevo == "terminada":
        titulo = f"La muestra {_cabecera(m)} está terminada"
        lineas = [f"Lista el {_fmt_fecha(m.get('fecha_lista'))}." if m.get("fecha_lista") else "Marcada como terminada."]
    elif nuevo == "cancelada":
        titulo = f"La muestra {_cabecera(m)} se ha cancelado"
        lineas = ["Pasa al histórico como cancelada."]
    else:
        retro = _FLUJO_ORDEN.get(nuevo, 99) < _FLUJO_ORDEN.get(anterior, -1)
        titulo = f"La muestra {_cabecera(m)} {'vuelve a' if retro else 'pasa a'} {a_lbl}"
        lineas = [f"Etapa anterior: {de_lbl}."]
    lineas.append(f"Cambio hecho por {actor_n} el {datetime.now().strftime('%d/%m/%Y %H:%M')}.")
    if nota:
        lineas.append(f"Nota: {nota}")
    texto, html = _render(titulo, lineas, m, base_url, nombre)
    ok, err = correo.enviar(email, _asunto_estado(m, nuevo), texto, html)
    mf.registrar_aviso(mid, motivo, email, ok, err, asunto=_asunto_estado(m, nuevo))
    if not ok:
        log.warning("aviso %s de M-%s a %s fallo: %s", motivo, mid, email, err)
    return {"enviado": ok, "motivo": err or "ok", "a": email}


def chequear_hitos(directorio, base_url: str, hoy: str | None = None) -> dict:
    """Avisa de los hitos cuya fecha ha llegado (hoy o antes) y aun no se
    avisaron. Reclama cada hito en transaccion (idempotente entre workers)."""
    hoy = hoy or date.today().isoformat()
    res = {"enviados": 0, "fallidos": 0, "sin_email": 0, "saltados": 0, "pendientes": 0}
    if not correo.configurado():
        return res
    pendientes = mf.hitos_pendientes(hoy)
    res["pendientes"] = len(pendientes)
    for m in pendientes:
        mid = m.get("id")
        fecha = m.get("proximo_hito_fecha")
        if not mf.reclamar_hito(mid, fecha):
            res["saltados"] += 1
            continue
        dest_u = (m.get("encargada_por_usuario") or "").strip().lower()
        email, nombre = email_de_usuario(dest_u, directorio)
        nombre = nombre or m.get("encargada_por") or dest_u
        if not email:
            res["sin_email"] += 1
            mf.registrar_aviso(mid, "hito", dest_u or "(sin usuario)", False,
                               "sin e-mail conocido para quien la encargó")
            continue
        que = (m.get("proximo_hito") or "").strip()
        tarde = fecha < hoy
        titulo = (f"Hoy toca el hito de {_cabecera(m)}" if not tarde
                  else f"El hito de {_cabecera(m)} previsto para el {_fmt_fecha(fecha)} ha llegado")
        lineas = [f"Previsto: {que}" if que else "Fecha de próximo hito alcanzada.",
                  f"Estado actual: {mf.ESTADOS_LABEL.get(m.get('estado') or '', '—')}."]
        asunto = f"[Muestras] {_cabecera(m)} · hito {_fmt_fecha(fecha)}" + (f": {mf._recortar(que, 60)}" if que else "")
        texto, html = _render(titulo, lineas, m, base_url, nombre)
        ok, err = correo.enviar(email, asunto, texto, html)
        mf.registrar_aviso(mid, "hito", email, ok, err, asunto=asunto)
        if ok:
            res["enviados"] += 1
        else:
            res["fallidos"] += 1
            log.warning("aviso de hito de M-%s a %s fallo: %s", mid, email, err)
    return res


def correo_de_prueba(actor, directorio, base_url: str) -> tuple[bool, str, str]:
    """Envia un correo de prueba a quien lo pide. (ok, error, email)."""
    u = (actor.get("username") if isinstance(actor, dict) else actor) or ""
    email, nombre = email_de_usuario(u, directorio)
    if not email:
        return False, "no sé tu e-mail: tu usuario de One no tiene correo en cuentas", ""
    nombre = nombre or (actor.get("nombre") if isinstance(actor, dict) else "") or u
    m = {"id": "0000", "cliente": "CLIENTE DE PRUEBA", "descripcion": "Correo de prueba de los avisos de muestras",
         "telar": "Varilla", "prioridad": 2, "fecha_solicitud": date.today().isoformat()}
    texto, html = _render("Los avisos por correo funcionan", ["Este es un correo de prueba enviado desde Muestras fabricadas."],
                          m, base_url, nombre)
    ok, err = correo.enviar(email, "[Muestras] Correo de prueba", texto, html)
    return ok, err, email
