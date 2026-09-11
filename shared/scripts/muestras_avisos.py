"""Avisos por correo de Muestras fabricadas, a quien encargo la muestra.

Tres disparadores (los pidio el usuario, sept 2026):
  - cambia de etapa (estado)                      → aviso_cambio_estado
  - se marca terminada o cancelada                → aviso_cambio_estado (mismo camino, otro asunto)
  - llega la fecha del proximo hito               → chequear_hitos (una vez por fecha)

Reglas:
  - Destinatario: `encargada_por_usuario` → su e-mail segun el directorio de
    cuentas (snapshot guardado en el documento) o, si el usuario ya es un
    e-mail (fernando@rolscarpets.com), ese mismo.
  - No se avisa a quien hace el cambio (ya lo sabe), salvo en los HITOS_CLAVE.
  - Etapas de diseno: «Listo para empezar diseno» avisa al buzon de diseno,
    «Listo para revision diseno» a quien la encargo Y a quien la creo, y
    «Diseno listo» al buzon del laboratorio.
  - Cada intento queda en el historial de la muestra (tipo "aviso", ok/error).
  - Best-effort: sin correo configurado no se hace nada; un fallo de SMTP se
    apunta en el historial y no afecta a la operacion.
"""
from __future__ import annotations

import html as _html
import logging
import os
from datetime import date, datetime

import correo
import muestras_fabricadas as mf

log = logging.getLogger("muestras.avisos")


# ---------------------------------------------------------------------------
# Destinatarios
# ---------------------------------------------------------------------------

# Buzon del laboratorio: el resumen de cada muestra nueva y las que llegan a
# «Diseño listo». Buzon de diseno: las que llegan a «Listo para empezar diseño».
# Sin acentos en la direccion a proposito: una ñ en la parte local exige
# SMTPUTF8 y no todos los servidores lo aceptan (se cambia por .env si el
# buzon real es otro).
LAB_EMAIL_DEFECTO = "laboratorio@rolscarpets.com"
DISENO_EMAIL_DEFECTO = "diseno@rolscarpets.com"
# Hitos clave: al llegar a ellos se avisa SIEMPRE a quien encargo la muestra,
# aunque el cambio lo haga esa misma persona (en el resto de etapas no se
# avisa a quien hace el cambio).
HITOS_CLAVE = ("revision_diseno", "terminada")
PIE_DEFECTO = ("Aviso automático a quien encargó la muestra. Se envía al cambiar de etapa, "
               "al terminar o cancelar, y el día del próximo hito.")
PIES_ETAPA = {
    "listo_diseno": "Aviso automático: al llegar a «Listo para empezar diseño» se avisa a diseño y a quien encargó la muestra.",
    "revision_diseno": "Aviso automático: al llegar a «Listo para revisión diseño» se avisa a quien encargó la muestra y a quien la creó.",
    "diseno_listo": "Aviso automático: al llegar a «Diseño listo» se avisa al laboratorio y a quien encargó la muestra.",
}


def email_laboratorio() -> str:
    return (os.environ.get("ROLS_MUESTRAS_LAB_EMAIL") or LAB_EMAIL_DEFECTO).strip().lower()


def email_diseno() -> str:
    return (os.environ.get("ROLS_MUESTRAS_DISENO_EMAIL") or DISENO_EMAIL_DEFECTO).strip().lower()


def listo_para_disenar(estado, telar) -> bool:
    """«Listo para empezar diseño», sea cual sea la técnica: la etapa propia de
    Varilla (`listo_diseno`) y, en Print, la inicial, que se lee igual."""
    return estado == "listo_diseno" or (estado == "por_empezar" and mf.es_print(telar))


def buzon_de_etapa(estado, telar) -> str:
    """Buzón que tiene que enterarse de esta etapa (además de las personas)."""
    if listo_para_disenar(estado, telar):
        return email_diseno()
    if estado == "diseno_listo":
        return email_laboratorio()
    return ""


def motivo_de_etapa(estado, telar) -> str:
    """Etiqueta del aviso en el historial de la muestra."""
    if estado in ("terminada", "cancelada", "revision_diseno", "diseno_listo"):
        return estado
    if listo_para_disenar(estado, telar):
        return "listo_diseno"
    return "estado"


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
    if m.get("referencia"):
        filas.append(("Referencia", m["referencia"]))
    if m.get("descripcion"):
        filas.append(("Muestra", mf._recortar(m.get("descripcion"), 300)))
    if m.get("telar"):
        filas.append(("Telar / técnica", m["telar"]))
    filas.append(("Prioridad", mf.PRIORIDADES.get(m.get("prioridad") or 0, "—")))
    tec = mf.resumen_tecnico(m)
    if tec:
        filas.append(("Técnica", tec))
    if m.get("fecha_solicitud"):
        filas.append(("Solicitada", _fmt_fecha(m["fecha_solicitud"])))
    if m.get("fecha_estimada") and m.get("estado") not in mf.ESTADOS_TERMINALES:
        filas.append(("Lista prevista", _fmt_fecha(m["fecha_estimada"])))
    if m.get("proximo_hito_fecha"):
        filas.append(("Próximo hito", _fmt_fecha(m["proximo_hito_fecha"])
                      + (f" — {m['proximo_hito']}" if m.get("proximo_hito") else "")))
    return filas


def _render(titulo: str, lineas: list[str], m: dict, base_url: str, nombre_dest: str,
            pie: str | None = None) -> tuple[str, str]:
    """(texto, html) con el mismo contenido. `pie`: nota al pie (por defecto la
    de los avisos a quien encargo la muestra)."""
    pie = pie or PIE_DEFECTO
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
  <p style="font-size:11px;color:#9a9a9a;margin:12px 4px 0">{e(pie)}</p>
</div></body></html>"""
    return texto, html


def _asunto_estado(m: dict, nuevo: str) -> str:
    cab = _cabecera(m)
    if nuevo == "terminada":
        return f"[Muestras] {cab} · TERMINADA" + (f" (lista el {_fmt_fecha(m.get('fecha_lista'))})" if m.get("fecha_lista") else "")
    if nuevo == "cancelada":
        return f"[Muestras] {cab} · CANCELADA"
    if nuevo == "revision_diseno":
        return f"[Muestras] {cab} · DISEÑO LISTO PARA TU REVISIÓN"
    if nuevo == "diseno_listo":
        return f"[Muestras] {cab} · DISEÑO LISTO"
    if listo_para_disenar(nuevo, m.get("telar")):
        return f"[Muestras] {cab} · LISTO PARA EMPEZAR DISEÑO"
    return f"[Muestras] {cab} · ahora en {mf.etiqueta_estado(nuevo, m.get('telar'))}"


# ---------------------------------------------------------------------------
# Disparadores
# ---------------------------------------------------------------------------

def aviso_cambio_estado(mid: str, anterior: str, nuevo: str, actor, nota: str,
                        directorio, base_url: str) -> dict:
    """Avisa del cambio de etapa. Quien lo recibe:

      - quien encargo la muestra, en cualquier etapa, salvo que el cambio lo
        haga esa misma persona (en los HITOS_CLAVE se le avisa igualmente);
      - en «Listo para revision diseno», tambien quien la creo;
      - el buzon de la etapa: diseno en «Listo para empezar diseno» (Print o
        Varilla) y laboratorio en «Diseno listo».

    Sale un solo correo con todos los destinatarios.
    Devuelve {"enviado": bool, "motivo": str, "a": [e-mails]}."""
    if anterior == nuevo:
        return {"enviado": False, "motivo": "sin cambio"}
    if not correo.configurado():
        return {"enviado": False, "motivo": "correo no configurado"}
    m = mf.obtener(mid)
    if not m:
        return {"enviado": False, "motivo": "muestra no existe"}
    telar = m.get("telar")
    actor_u = str((actor.get("username") if isinstance(actor, dict) else actor) or "").strip().lower()
    actor_n = (actor.get("nombre") if isinstance(actor, dict) else "") or actor_u

    destinos: list[str] = []
    nombres: list[str] = []

    def anadir(email, nombre="") -> bool:
        e = (email or "").strip().lower()
        if not e or e in destinos:
            return bool(e)
        destinos.append(e)
        if nombre:
            nombres.append(nombre)
        return True

    # 1) quien la encargo (no a quien hace el cambio, salvo en los hitos clave)
    dest_u = (m.get("encargada_por_usuario") or "").strip().lower()
    sin_email_de = ""
    if dest_u and (dest_u != actor_u or nuevo in HITOS_CLAVE):
        email, nombre = email_de_usuario(dest_u, directorio)
        if not anadir(email, nombre or m.get("encargada_por") or dest_u):
            sin_email_de = dest_u
    # 2) en la revision del diseno, tambien quien la creo
    if nuevo == "revision_diseno":
        cre_u = (m.get("creado_por") or "").strip().lower()
        if cre_u:
            email, nombre = email_de_usuario(cre_u, directorio)
            anadir(email, nombre or m.get("creado_por_nombre") or cre_u)
    # 3) el buzon de la etapa
    anadir(buzon_de_etapa(nuevo, telar))

    motivo = motivo_de_etapa(nuevo, telar)
    asunto = _asunto_estado(m, nuevo)
    if not destinos:
        if sin_email_de:
            mf.registrar_aviso(mid, motivo, sin_email_de, False,
                               "sin e-mail conocido para el usuario", asunto=asunto)
            return {"enviado": False, "motivo": "sin e-mail"}
        if not dest_u:
            return {"enviado": False, "motivo": "la muestra no tiene usuario que la encargue"}
        return {"enviado": False, "motivo": "el cambio lo hace quien la encargó"}

    de_lbl = mf.etiqueta_estado(anterior, telar) if anterior else "—"
    a_lbl = mf.etiqueta_estado(nuevo, telar)
    if nuevo == "terminada":
        titulo = f"La muestra {_cabecera(m)} está terminada"
        lineas = [f"Lista el {_fmt_fecha(m.get('fecha_lista'))}." if m.get("fecha_lista") else "Marcada como terminada."]
    elif nuevo == "cancelada":
        titulo = f"La muestra {_cabecera(m)} se ha cancelado"
        lineas = ["Pasa al histórico como cancelada."]
    elif nuevo == "revision_diseno":
        titulo = f"El diseño de {_cabecera(m)} está listo para revisión"
        lineas = ["Entra en la ficha, revisa el diseño adjunto y, si está bien, marca «Verificación de diseño». "
                  "Si hay cambios, déjalos en el diario del laboratorio."]
    elif nuevo == "diseno_listo":
        titulo = f"El diseño de {_cabecera(m)} está listo"
        lineas = ["El diseño queda cerrado: el laboratorio ya puede seguir con la muestra."]
    elif listo_para_disenar(nuevo, telar):
        titulo = f"Se puede empezar el diseño de {_cabecera(m)}"
        lineas = ["La muestra queda a la espera de diseño. En la ficha están los datos y, si los hay, los ficheros."]
    else:
        retro = mf.es_retroceso(anterior, nuevo, telar)
        titulo = f"La muestra {_cabecera(m)} {'vuelve a' if retro else 'pasa a'} {a_lbl}"
        lineas = [f"Etapa anterior: {de_lbl}."]
    lineas.append(f"Cambio hecho por {actor_n} el {datetime.now().strftime('%d/%m/%Y %H:%M')}.")
    if nota:
        lineas.append(f"Nota: {nota}")
    # Saludo por el nombre solo cuando va a una sola persona
    nombre_dest = nombres[0] if (len(destinos) == 1 and nombres) else ""
    texto, html = _render(titulo, lineas, m, base_url, nombre_dest, pie=PIES_ETAPA.get(motivo))
    ok, err = correo.enviar(destinos, asunto, texto, html)
    mf.registrar_aviso(mid, motivo, ", ".join(destinos), ok, err, asunto=asunto)
    if not ok:
        log.warning("aviso %s de M-%s a %s fallo: %s", motivo, mid, destinos, err)
    return {"enviado": ok, "motivo": err or "ok", "a": destinos}


def aviso_nueva_muestra(mid: str, actor, directorio, base_url: str) -> dict:
    """Al dar de alta una muestra: resumen al laboratorio
    (ROLS_MUESTRAS_LAB_EMAIL, por defecto laboratorio@rolscarpets.com) y a
    quien la ha creado. Devuelve {"enviado": bool, "motivo": str}."""
    if not correo.configurado():
        return {"enviado": False, "motivo": "correo no configurado"}
    m = mf.obtener(mid)
    if not m:
        return {"enviado": False, "motivo": "muestra no existe"}
    actor_u = (actor.get("username") if isinstance(actor, dict) else actor) or ""
    actor_n = (actor.get("nombre") if isinstance(actor, dict) else "") or ""
    email_actor, nombre_actor = email_de_usuario(actor_u, directorio)
    nombre_actor = nombre_actor or actor_n or actor_u or "—"
    destinos = []
    lab = email_laboratorio()
    if lab:
        destinos.append(lab)
    if email_actor and email_actor not in destinos:
        destinos.append(email_actor)
    # Una Print nace ya en «Listo para empezar diseño»: diseño se entera aquí,
    # porque esa etapa no llega nunca como cambio de etapa.
    if listo_para_disenar(m.get("estado"), m.get("telar")):
        dis = email_diseno()
        if dis and dis not in destinos:
            destinos.append(dis)
    asunto = f"[Muestras] Nueva muestra {_cabecera(m)}"
    if not destinos:
        mf.registrar_aviso(mid, "nueva", "", False, "sin destinatarios", asunto=asunto)
        return {"enviado": False, "motivo": "sin destinatarios"}
    titulo = f"Nueva muestra {_cabecera(m)}"
    lineas = [f"Creada por {nombre_actor} el {datetime.now().strftime('%d/%m/%Y %H:%M')}."]
    if m.get("encargada_por"):
        lineas.append(f"Encargada por {m['encargada_por']}.")
    if m.get("sufijo") and m.get("numero") is not None:
        lineas.append(f"Es variante de M-{m['numero']}.")
    lineas.append(f"Estado inicial: {mf.etiqueta_estado(m.get('estado'), m.get('telar'))}.")
    texto, html = _render(titulo, lineas, m, base_url, "",
                          pie="Aviso automático de alta de muestra: llega al laboratorio, a quien la ha creado y, "
                              "si nace lista para empezar diseño, también a diseño.")
    ok, err = correo.enviar(destinos, asunto, texto, html)
    mf.registrar_aviso(mid, "nueva", ", ".join(destinos), ok, err, asunto=asunto)
    if not ok:
        log.warning("aviso de alta de M-%s a %s fallo: %s", mid, destinos, err)
    return {"enviado": ok, "motivo": err or "ok", "a": destinos}


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
                  f"Estado actual: {mf.etiqueta_estado(m.get('estado'), m.get('telar'))}."]
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
