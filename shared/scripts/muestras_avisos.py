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
import re
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
# aunque el cambio lo haga esa misma persona. Es el valor de fabrica de esas
# dos etapas; se puede cambiar desde Analisis (ver config_avisos).
HITOS_CLAVE = ("revision_diseno", "terminada")

# ---------------------------------------------------------------------------
# Quien recibe cada aviso (configurable desde la pestana Analisis)
# ---------------------------------------------------------------------------
# Una fila por momento: el alta ("nueva"), cada etapa y el proximo hito
# ("hito"). De cada fila:
#   encargada → "no" | "salvo_actor" (no si el cambio lo hace ella) | "siempre"
#   creador   → si tambien se avisa a quien creo la muestra
#   buzones   → e-mails fijos que reciben esa fila pase lo que pase
MODOS_ENCARGADA = ("no", "salvo_actor", "siempre")
MAX_BUZONES = 5
_RE_EMAIL = re.compile(r"^[^@\s,;]+@[^@\s,;]+\.[^@\s,;]{2,}$")


def claves_aviso() -> list[str]:
    return ["nueva", *mf.ESTADOS_SELECCIONABLES, "hito"]


def _fila(encargada: str = "salvo_actor", creador: bool = False, buzones=()) -> dict:
    return {"encargada": encargada, "creador": bool(creador), "buzones": [b for b in buzones if b]}


def avisos_por_defecto() -> dict:
    """Los valores de fabrica: los que llevaba el ERP antes de poder cambiarlos."""
    lab, dis = email_laboratorio(), email_diseno()
    cfg = {c: _fila() for c in claves_aviso()}
    cfg["nueva"] = _fila("no", True, [lab])
    cfg["listo_diseno"] = _fila("salvo_actor", False, [dis])
    cfg["revision_diseno"] = _fila("siempre", True)
    cfg["diseno_listo"] = _fila("salvo_actor", False, [lab])
    cfg["terminada"] = _fila("siempre")
    cfg["hito"] = _fila("siempre")
    return cfg


def config_avisos() -> dict:
    """Los defectos con lo que se haya cambiado a mano por encima."""
    cfg = avisos_por_defecto()
    for k, v in (mf.avisos_guardados() or {}).items():
        if k in cfg and isinstance(v, dict):
            fila = dict(cfg[k])
            for campo in ("encargada", "creador", "buzones"):
                if campo in v:
                    fila[campo] = v[campo]
            cfg[k] = fila
    return cfg


def clave_aviso(estado, telar=None) -> str:
    """La fila de configuracion que toca a esa etapa."""
    return estado or ""


def _asunto_ejemplo(estado: str) -> str:
    if estado == "terminada":
        return "[Muestras] M-… · TERMINADA (lista el 11/09/2026)"
    if estado == "cancelada":
        return "[Muestras] M-… · CANCELADA"
    if estado == "revision_diseno":
        return "[Muestras] M-… · DISEÑO LISTO PARA TU REVISIÓN"
    if estado == "diseno_listo":
        return "[Muestras] M-… · DISEÑO LISTO"
    if estado == "listo_diseno":
        return "[Muestras] M-… · LISTO PARA EMPEZAR DISEÑO"
    return f"[Muestras] M-… · ahora en {mf.ESTADOS_LABEL.get(estado, estado)}"


def filas_aviso() -> list[dict]:
    """Para la UI: cada fila configurable, en orden, con su etiqueta y asunto."""
    out = [{"clave": "nueva", "etiqueta": "Se crea la muestra", "tipo": "alta",
            "nota": "el resumen de alta", "asunto": "[Muestras] Nueva muestra M-… · Cliente"}]
    for s in mf.ESTADOS_SELECCIONABLES:
        nota = ""
        if s == "listo_diseno":
            nota = "también las Print, que ahora pasan por aquí"
        out.append({"clave": s, "etiqueta": mf.ESTADOS_LABEL.get(s, s), "tipo": "etapa",
                    "nota": nota, "asunto": _asunto_ejemplo(s)})
    out.append({"clave": "hito", "etiqueta": "Llega la fecha del próximo hito", "tipo": "hito",
                "nota": "una sola vez por fecha",
                "asunto": "[Muestras] M-… · hito 15/10/2026: llegan los colores"})
    return out


def guardar_config_avisos(cambios: dict) -> tuple[dict | None, str]:
    """Valida y guarda las filas que vengan. Devuelve (config completa, error)."""
    if not isinstance(cambios, dict) or not cambios:
        return None, "no hay nada que cambiar"
    validas = set(claves_aviso())
    limpio = {}
    for clave, fila in cambios.items():
        if clave not in validas:
            return None, f"momento desconocido: {clave!r}"
        if not isinstance(fila, dict):
            return None, f"{clave}: la fila debe ser un objeto"
        out = {}
        if "encargada" in fila:
            if fila["encargada"] not in MODOS_ENCARGADA:
                return None, f"{clave}: «quien la encargó» no válido ({fila['encargada']!r})"
            out["encargada"] = fila["encargada"]
        if "creador" in fila:
            out["creador"] = bool(fila["creador"])
        if "buzones" in fila:
            crudos = fila["buzones"]
            if isinstance(crudos, str):
                crudos = re.split(r"[,;\s]+", crudos)
            if not isinstance(crudos, list):
                return None, f"{clave}: los buzones deben ser una lista"
            buzones = []
            for b in crudos:
                b = str(b or "").strip().lower()
                if not b:
                    continue
                if not _RE_EMAIL.match(b):
                    return None, f"{clave}: «{b}» no parece un e-mail"
                if b not in buzones:
                    buzones.append(b)
            if len(buzones) > MAX_BUZONES:
                return None, f"{clave}: como mucho {MAX_BUZONES} buzones"
            out["buzones"] = buzones
        if out:
            limpio[clave] = out
    if not limpio:
        return None, "no hay nada que cambiar"
    mf.guardar_avisos(limpio)
    return config_avisos(), ""
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


def listo_para_disenar(estado, telar=None) -> bool:
    """«Listo para empezar diseño»: la misma etapa en todas las técnicas."""
    return estado == "listo_diseno"


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

    cfg = config_avisos().get(clave_aviso(nuevo, telar), {})
    # 1) quien la encargo, segun lo configurado para esta etapa
    dest_u = (m.get("encargada_por_usuario") or "").strip().lower()
    sin_email_de = ""
    modo = cfg.get("encargada", "salvo_actor")
    if dest_u and (modo == "siempre" or (modo == "salvo_actor" and dest_u != actor_u)):
        email, nombre = email_de_usuario(dest_u, directorio)
        if not anadir(email, nombre or m.get("encargada_por") or dest_u):
            sin_email_de = dest_u
    # 2) quien la creo
    if cfg.get("creador"):
        cre_u = (m.get("creado_por") or "").strip().lower()
        if cre_u:
            email, nombre = email_de_usuario(cre_u, directorio)
            anadir(email, nombre or m.get("creado_por_nombre") or cre_u)
    # 3) los buzones de la etapa
    for b in cfg.get("buzones") or []:
        anadir(b)

    motivo = motivo_de_etapa(nuevo, telar)
    asunto = _asunto_estado(m, nuevo)
    if not destinos:
        if sin_email_de:
            mf.registrar_aviso(mid, motivo, sin_email_de, False,
                               "sin e-mail conocido para el usuario", asunto=asunto)
            return {"enviado": False, "motivo": "sin e-mail"}
        if not dest_u:
            return {"enviado": False, "motivo": "la muestra no tiene usuario que la encargue"}
        if modo == "no":
            return {"enviado": False, "motivo": "esta etapa no avisa a nadie"}
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
    cfg_todo = config_avisos()
    cfg = cfg_todo.get("nueva", {})
    destinos = []

    def _anadir(e):
        e = (e or "").strip().lower()
        if e and e not in destinos:
            destinos.append(e)

    for b in cfg.get("buzones") or []:
        _anadir(b)
    if cfg.get("creador", True):
        _anadir(email_actor)
    if cfg.get("encargada", "no") != "no":
        _anadir(email_de_usuario(m.get("encargada_por_usuario"), directorio)[0])
    # Si la muestra nace directamente en «Listo para empezar diseño», quien
    # reciba esa etapa se entera aquí: nunca llegará como cambio de etapa.
    if listo_para_disenar(m.get("estado")):
        for b in (cfg_todo.get("listo_diseno", {}).get("buzones") or []):
            _anadir(b)
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
        cfg_hito = config_avisos().get("hito", {})
        dest_u = (m.get("encargada_por_usuario") or "").strip().lower()
        email, nombre = email_de_usuario(dest_u, directorio)
        nombre = nombre or m.get("encargada_por") or dest_u
        if cfg_hito.get("encargada", "siempre") == "no":
            email = ""
        extras = [b for b in (cfg_hito.get("buzones") or []) if b]
        if cfg_hito.get("creador"):
            cre_e, _ = email_de_usuario((m.get("creado_por") or "").strip().lower(), directorio)
            if cre_e and cre_e != email:
                extras.append(cre_e)
        if not email and not extras:
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
        destinos_h = ([email] if email else []) + [b for b in extras if b != email]
        texto, html = _render(titulo, lineas, m, base_url, nombre if len(destinos_h) == 1 else "")
        ok, err = correo.enviar(destinos_h, asunto, texto, html)
        mf.registrar_aviso(mid, "hito", ", ".join(destinos_h), ok, err, asunto=asunto)
        if ok:
            res["enviados"] += 1
        else:
            res["fallidos"] += 1
            log.warning("aviso de hito de M-%s a %s fallo: %s", mid, destinos_h, err)
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
