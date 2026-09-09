"""ERP Produccion Rols — MUESTRAS FABRICADAS.

Seguimiento de las muestras que se tejen en fabrica (prototipos, disenos,
contramuestras, pompones de laboratorio...): cada una tiene un NUMERO DE M
(M-5448, con sufijo de variante M-5448-C), un cliente, quien la encarga, una
prioridad, el telar/tecnica y un ESTADO que recorre el proceso de fabricacion
(diseno → hilatura → tintoreria → bobinado → telar → aprestos → terminada).

Sustituye al "LIBRO DE MUESTRAS.xlsx" (X:\\06. MUESTRAS): sus tres hojas
—Registro de numeros de M, Seguimiento de fabricacion y Muestras
terminadas— se importaron como seed inicial (ver `_import` en cada
registro). El diario del laboratorio (antes una celda con "11.03.2025 Se
envian los kgs... 14.03.2025 Se amplian...") se guarda troceado en apuntes
fechados.

Documento (jsonstore, key "muestras_fabricadas"):
{
  "_meta": {"version_schema": 1, "ultimo_numero": 5529, ...},
  "catalogos": {"telares": [...], "personas": [...]},
  "muestras": [
    {
      "id": "5448-C",             # numero + sufijo de variante (estable, no cambia)
      "numero": 5448,
      "sufijo": "C",
      "fecha_solicitud": "2026-01-07",
      "cliente": "INTERNA ( NANDO )",
      "encargada_por": "Fernando",  # comercial/persona que la pide
      "prioridad": 2,               # 1 alta · 2 normal · 3 baja
      "telar": "Varilla",           # tecnica: Print, Tufting, Colortec, Varilla...
      "estado": "en_tintoreria",    # slug de ESTADOS
      "fecha_lista": null,          # cuando se entrega terminada
      "archivada": false,           # fuera de "En curso" sin estar terminada
      "descripcion": "...",         # descripcion de la muestra (comercial)
      "anotacion_registro": "...",  # nota corta del registro de numeros (si difiere)
      "resultado": "...",           # que paso despues (pedido, descartada...)
      "apuntes": [{"id": "a1b2c3", "fecha": "2026-01-12", "texto": "...", "usuario": null}],
      "historial": [{"fecha": "...", "usuario": "...", "tipo": "estado", "de": "...", "a": "..."}],
      "creado_en": "...", "actualizado_en": "...", "creado_por": "..."
    }
  ]
}

Reglas:
- Los slugs de estado NO cambian nunca (solo su label). `sin_seguimiento` es
  solo historico (muestras del registro antiguo sin hoja de seguimiento) y no
  se ofrece para cambios.
- El numero se asigna en servidor: `_meta.ultimo_numero + 1` (o el siguiente
  sufijo de variante). Se admite un numero manual (transicion desde el Excel).
- Todo load→mutate→save va dentro de `with jsonstore.store().tx()`.
"""
from __future__ import annotations

import os
import re
import secrets
import unicodedata
from datetime import date, datetime
from pathlib import Path

import jsonstore

DATA_PATH = Path(os.environ.get("ROLS_DATA_DIR")
                 or Path(__file__).resolve().parent.parent / "data") / "muestras_fabricadas.json"
_KEY = "muestras_fabricadas"

# ---------------------------------------------------------------------------
# Catalogos fijos
# ---------------------------------------------------------------------------

# (slug, label). El orden es el del proceso de fabricacion.
ESTADOS: tuple[tuple[str, str], ...] = (
    ("por_empezar",      "Por empezar"),
    ("en_diseno",        "En diseño"),
    ("en_hilatura",      "En hilatura"),
    ("en_tintoreria",    "En tintorería"),
    ("bobinando",        "Bobinando"),
    ("esperando_telar",  "Esperando a telar"),
    ("en_telar",         "En telar"),
    ("en_aprestos",      "En aprestos"),
    ("terminada",        "Terminada"),
    ("cancelada",        "Cancelada"),
    ("sin_seguimiento",  "Sin seguimiento"),
)
ESTADOS_LABEL = dict(ESTADOS)
ESTADOS_FLUJO = tuple(s for s, _ in ESTADOS[:9])          # por_empezar … terminada
ESTADOS_TERMINALES = {"terminada", "cancelada", "sin_seguimiento"}
ESTADOS_SELECCIONABLES = tuple(s for s, _ in ESTADOS[:10])  # todos menos sin_seguimiento

PRIORIDADES = {1: "Alta", 2: "Media", 3: "Baja"}

# Muestra para un cliente o desarrollo propio (lo que el libro apuntaba como
# "INTERNA ( NANDO )", "MOQUETAS ROLS", "ROLS (PACO)"...).
TIPOS = ("cliente", "interna")
_VERSION_SCHEMA = 2

# "Solo diseño" y "Escala" del libro antiguo se unificaron en Print y Rapier
# (sept 2026); normalizar_telar los sigue reconociendo como alias.
TELARES_DEFAULT = ["Print", "Tufting", "Colortec", "Varilla", "Lancetas",
                   "Raschel", "Pompón", "Kibby", "Rapier", "Festón"]
PERSONAS_DEFAULT = ["Fernando", "Damián", "JM", "Carmen", "Paco", "Emilio",
                    "Romu", "Victor", "Blanca", "Señor Gómez"]

CAMPOS_EDITABLES = {
    "tipo", "cliente", "descripcion", "encargada_por", "prioridad", "telar",
    "fecha_solicitud", "fecha_lista", "resultado", "anotacion_registro",
}
_MAX_TEXTO = 6000


# ---------------------------------------------------------------------------
# Persistencia
# ---------------------------------------------------------------------------

def _default() -> dict:
    return {
        "_meta": {"version_schema": _VERSION_SCHEMA, "ultimo_numero": 0},
        "catalogos": {"telares": list(TELARES_DEFAULT),
                      "personas": list(PERSONAS_DEFAULT)},
        "muestras": [],
    }


def _cargar_sin_migrar() -> dict:
    data = jsonstore.store().load(_KEY, _default, DATA_PATH)
    data.setdefault("_meta", {}).setdefault("ultimo_numero", 0)
    cat = data.setdefault("catalogos", {})
    cat.setdefault("telares", list(TELARES_DEFAULT))
    cat.setdefault("personas", list(PERSONAS_DEFAULT))
    data.setdefault("muestras", [])
    return data


def _version(data: dict) -> int:
    try:
        return int(data.get("_meta", {}).get("version_schema") or 1)
    except (TypeError, ValueError):
        return 1


def cargar() -> dict:
    """Carga el documento aplicando (una sola vez, dentro de una transaccion)
    las migraciones de esquema pendientes."""
    data = _cargar_sin_migrar()
    if _version(data) < _VERSION_SCHEMA:
        with jsonstore.store().tx():
            data = _cargar_sin_migrar()
            if _version(data) < _VERSION_SCHEMA:
                _migrar_v2(data)
                data["_meta"]["version_schema"] = _VERSION_SCHEMA
                _guardar(data)
    return data


# Erratas de fecha de solicitud del libro: (valor erroneo, valor del registro)
_FECHAS_LIBRO_CORREGIDAS = {
    "4202": ("2012-09-02", "2016-09-02"),
    "5463": ("2005-05-14", "2025-05-14"),
}


def _migrar_v2(data: dict) -> None:
    """v1 → v2 (sept 2026): `tipo` cliente/interna deducido del nombre del
    cliente, telares unificados (Escala→Rapier, Solo diseño→Print), dos
    erratas de fecha del libro y fuera las 6 M de dic-2014 (solo estaban en
    el registro, sin seguimiento). Idempotente."""
    cat = data.setdefault("catalogos", {})
    telares: list[str] = []
    for t in (cat.get("telares") or TELARES_DEFAULT):
        t2 = normalizar_telar(t, TELARES_DEFAULT)
        if t2 and not any(_clave(t2) == _clave(x) for x in telares):
            telares.append(t2)
    cat["telares"] = telares
    quedan = []
    for m in data.get("muestras", []):
        if _anio(m.get("fecha_solicitud")) == 2014:
            continue
        m["telar"] = normalizar_telar(m.get("telar"), telares)
        if m.get("tipo") not in TIPOS:
            m["tipo"] = tipo_por_cliente(m.get("cliente"))
        corr = _FECHAS_LIBRO_CORREGIDAS.get(m.get("id"))
        if corr and m.get("fecha_solicitud") == corr[0]:
            m["fecha_solicitud"] = corr[1]
            _historial(m, None, "campo", campo="fecha_solicitud", de=corr[0], a=corr[1],
                       texto="errata de fecha del libro, corregida con el registro de numeros")
        quedan.append(m)
    data["muestras"] = quedan


def _guardar(data: dict) -> None:
    data.setdefault("_meta", {})
    data["_meta"]["actualizado_en"] = _ahora()
    jsonstore.store().save(_KEY, data)


def _ahora() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _hoy() -> str:
    return date.today().isoformat()


def _nuevo_id_apunte() -> str:
    return secrets.token_hex(3)


# ---------------------------------------------------------------------------
# Normalizacion (compartida con el importador del Excel)
# ---------------------------------------------------------------------------

def _sin_acentos(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "")
    return "".join(c for c in s if not unicodedata.combining(c))


def _clave(s) -> str:
    """Clave de comparacion: sin acentos, minusculas, espacios colapsados."""
    return re.sub(r"\s+", " ", _sin_acentos(str(s or "")).lower()).strip()


# "5448", "5448-C", "4102 B", "M-4120 B", "4011-b", "4498-BC", "4085C",
# y sufijos con digito del libro antiguo: "4901-B2", "4440-1", "4440-1B".
_RE_NUMERO = re.compile(
    r"^\s*(?:M\s*-?\s*)?(\d{3,5})\s*(?:[-–—]?\s*([A-Za-z]{1,3}\d{0,2}|\d{1,2}[A-Za-z]?))?\s*\.?\s*$")


def normalizar_numero(raw) -> tuple[str | None, int | None, str]:
    """(id, numero, sufijo) a partir de lo que haya escrito en 'Numero de M'.
    Devuelve (None, None, "") si viene vacio. Si no encaja con el patron
    habitual, el id es el texto tal cual (colapsado, en mayusculas) y el
    numero el primer entero de 3-5 cifras que aparezca."""
    if raw is None:
        return None, None, ""
    if isinstance(raw, float) and raw.is_integer():
        raw = int(raw)
    s = str(raw).strip()
    if not s:
        return None, None, ""
    m = _RE_NUMERO.match(s)
    if m:
        numero = int(m.group(1))
        sufijo = (m.group(2) or "").upper()
        return (f"{numero}-{sufijo}" if sufijo else str(numero)), numero, sufijo
    # Sin patron de M ("Ped. 7185", "P.6776"...): no hay numero de M; el id es
    # el texto saneado (solo A-Z 0-9 . + -) para que sirva en una URL.
    s2 = re.sub(r"[^A-Z0-9.+-]+", "-", _sin_acentos(s).upper()).strip("-")
    return (s2 or None), None, ""


_ESTADO_POR_CLAVE = {
    "por empezar": "por_empezar",
    "en diseno": "en_diseno",
    "diseno": "en_diseno",
    "print": "en_diseno",
    "en hilatura": "en_hilatura",
    "hilatura": "en_hilatura",
    "en tintoreria": "en_tintoreria",
    "tintoreria": "en_tintoreria",
    "lana tintada en laboratorio": "en_tintoreria",
    "bobinando": "bobinando",
    "esperando a telar": "esperando_telar",
    "esperando telar": "esperando_telar",
    "en telar": "en_telar",
    "telar": "en_telar",
    "en aprestos": "en_aprestos",
    "aprestos": "en_aprestos",
    "terminada": "terminada",
    "cancelada": "cancelada",
    "sin seguimiento": "sin_seguimiento",
}


def normalizar_estado(raw) -> str | None:
    """Slug de estado a partir del texto del Excel (o de un slug)."""
    if raw is None:
        return None
    s = str(raw).strip()
    if not s or s.lower() == "[seleccionar]":
        return None
    if s in ESTADOS_LABEL:
        return s
    return _ESTADO_POR_CLAVE.get(_clave(s).replace("_", " "))


_TELAR_ALIAS = {
    "pompon": "Pompón", "pompones": "Pompón", "pompon labor.(raschel)": "Pompón",
    "print": "Print", "prints": "Print", "feston": "Festón", "kibby": "Kibby",
    # unificados en sept 2026
    "solo diseno": "Print", "diseno": "Print", "escala": "Rapier",
}


def normalizar_telar(raw, catalogo: list[str] | None = None) -> str:
    """Nombre canonico del telar/tecnica: casa (sin acentos ni mayusculas)
    con el catalogo; lo desconocido se devuelve limpio tal cual."""
    if raw is None:
        return ""
    s = re.sub(r"\s+", " ", str(raw)).strip()
    if not s or s.lower() == "[seleccionar]":
        return ""
    k = _clave(s)
    if k in _TELAR_ALIAS:
        return _TELAR_ALIAS[k]
    for t in (catalogo or TELARES_DEFAULT):
        if _clave(t) == k:
            return t
    return s


def normalizar_persona(raw) -> str:
    if raw is None:
        return ""
    s = re.sub(r"\s+", " ", str(raw)).strip()
    return "" if s.lower() == "[seleccionar]" else s


_RE_INTERNA = re.compile(r"\b(interna|interno|internp|rols|moquetas rols)\b")


def tipo_por_cliente(cliente) -> str:
    """'interna' si el texto del cliente es de los que el libro usaba para los
    desarrollos propios (INTERNA ( NANDO ), MOQUETAS ROLS, ROLS (PACO)...).
    'ROLLS SUPPLY' o 'HERMANOS ROLDAN' no cuentan (palabra completa)."""
    return "interna" if _RE_INTERNA.search(_clave(cliente)) else "cliente"


def _validar_tipo(v, cliente) -> tuple[str, str]:
    if v in (None, ""):
        return (tipo_por_cliente(cliente) if cliente else "cliente"), ""
    v = str(v).strip().lower()
    if v not in TIPOS:
        return "", "tipo debe ser 'cliente' o 'interna'"
    return v, ""


def iso_fecha(v) -> str | None:
    """'YYYY-MM-DD' desde datetime/date/str (dd/mm/yyyy, dd.mm.yyyy, ISO...)."""
    if v is None or v == "":
        return None
    if isinstance(v, datetime):
        return v.date().isoformat()
    if isinstance(v, date):
        return v.isoformat()
    s = str(v).strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d.%m.%Y", "%d-%m-%Y", "%d/%m/%y", "%d.%m.%y"):
        try:
            return datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            continue
    return None


# Fechas al estilo del laboratorio: "11.03.2025", "8.5.2026", "29,04,2016",
# "15/18.05.2026" (varios dias), "3/5/10.06.2026", "22/23.07.2026".
_RE_FECHA_APUNTE = re.compile(
    r"(?<!\d)((?:\d{1,2}\s*/\s*)*\d{1,2})\s*[.,/]\s*(\d{1,2})\s*[.,/]\s*(\d{4}|\d{2})(?!\d)")


def _fecha_de_match(m) -> str | None:
    dias, mes, anio = m.group(1), int(m.group(2)), m.group(3)
    dia = int(re.split(r"\s*/\s*", dias.strip())[0])
    anio_i = int(anio) if len(anio) == 4 else 2000 + int(anio)
    if not (1 <= mes <= 12 and 1 <= dia <= 31 and 1990 <= anio_i <= 2100):
        return None
    try:
        return date(anio_i, mes, dia).isoformat()
    except ValueError:
        return None


def parsear_diario(texto) -> list[dict]:
    """Trocea el texto de 'Comentarios LABORATORIO' en apuntes fechados.
    Sin perdida: lo que va antes de la primera fecha es un apunte sin fecha,
    y cada fecha abre un apunte hasta la siguiente. Una fecha imposible
    (mes 13...) se deja como texto."""
    if not texto:
        return []
    s = re.sub(r"\s+", " ", str(texto)).strip()
    if not s:
        return []
    cortes = []
    for m in _RE_FECHA_APUNTE.finditer(s):
        f = _fecha_de_match(m)
        if f:
            cortes.append((m.start(), m.end(), f))
    apuntes: list[dict] = []
    if not cortes:
        return [{"id": _nuevo_id_apunte(), "fecha": None, "texto": s, "usuario": None}]
    pre = s[:cortes[0][0]].strip(" -:·;,")
    if pre:
        apuntes.append({"id": _nuevo_id_apunte(), "fecha": None, "texto": pre, "usuario": None})
    for i, (ini, fin, f) in enumerate(cortes):
        sig = cortes[i + 1][0] if i + 1 < len(cortes) else len(s)
        cuerpo = s[fin:sig].strip(" -:·;,")
        apuntes.append({"id": _nuevo_id_apunte(), "fecha": f, "texto": cuerpo, "usuario": None})
    return apuntes


# ---------------------------------------------------------------------------
# Helpers de dominio
# ---------------------------------------------------------------------------

def es_activa(m: dict) -> bool:
    return (m.get("estado") or "") not in ESTADOS_TERMINALES


def en_curso(m: dict) -> bool:
    return es_activa(m) and not m.get("archivada")


def _dias_entre(a: str | None, b: str | None) -> int | None:
    try:
        return (date.fromisoformat(b) - date.fromisoformat(a)).days
    except (TypeError, ValueError):
        return None


def _anio(fecha: str | None) -> int | None:
    try:
        return int(fecha[:4]) if fecha else None
    except (TypeError, ValueError):
        return None


def _buscar(data: dict, mid: str) -> dict | None:
    mid = (mid or "").strip().upper()
    for m in data.get("muestras", []):
        if (m.get("id") or "").upper() == mid:
            return m
    return None


def _recortar(s, n: int) -> str:
    s = (s or "").strip()
    return s if len(s) <= n else s[: n - 1].rstrip() + "…"


def _historial(m: dict, usuario, tipo: str, **extra) -> None:
    m.setdefault("historial", []).append(
        {"fecha": _ahora(), "usuario": usuario or None, "tipo": tipo, **extra})


def _texto_buscable(m: dict) -> str:
    partes = [m.get("id"), m.get("cliente"), m.get("descripcion"),
              m.get("anotacion_registro"), m.get("resultado"),
              m.get("encargada_por"), m.get("telar"),
              ESTADOS_LABEL.get(m.get("estado") or "", ""),
              "interna" if m.get("tipo") == "interna" else ""]
    partes += [a.get("texto") for a in (m.get("apuntes") or [])]
    return _clave(" ".join(p for p in partes if p))


def _compacta(m: dict, hoy: str, recortar_textos: bool, n_variantes: int) -> dict:
    apuntes = m.get("apuntes") or []
    ultimo = apuntes[-1] if apuntes else None
    estado = m.get("estado") or ""
    if es_activa(m):
        dias, dias_tipo = _dias_entre(m.get("fecha_solicitud"), hoy), "en_curso"
    else:
        dias, dias_tipo = _dias_entre(m.get("fecha_solicitud"), m.get("fecha_lista")), "plazo"
    return {
        "id": m.get("id"), "numero": m.get("numero"), "sufijo": m.get("sufijo") or "",
        "fecha_solicitud": m.get("fecha_solicitud"), "cliente": m.get("cliente") or "",
        "tipo": m.get("tipo") or "cliente",
        "encargada_por": m.get("encargada_por") or "", "prioridad": m.get("prioridad"),
        "telar": m.get("telar") or "", "estado": estado,
        "estado_label": ESTADOS_LABEL.get(estado, estado or "—"),
        "fecha_lista": m.get("fecha_lista"), "archivada": bool(m.get("archivada")),
        "descripcion": _recortar(m.get("descripcion"), 220) if recortar_textos else (m.get("descripcion") or ""),
        "resultado": _recortar(m.get("resultado"), 160),
        "ultimo_apunte": ({"fecha": ultimo.get("fecha"), "texto": _recortar(ultimo.get("texto"), 180)}
                          if ultimo else None),
        "n_apuntes": len(apuntes), "dias": dias, "dias_tipo": dias_tipo,
        "n_variantes": n_variantes,
    }


# ---------------------------------------------------------------------------
# Lectura
# ---------------------------------------------------------------------------

def listar(vista: str = "en-curso", q: str = "", anio=None, estado: str = "",
           telar: str = "", persona: str = "", prioridad=None,
           limite: int | None = None, tipo: str = "") -> dict:
    """Listado compacto. vista: 'en-curso' (activas no archivadas, orden
    prioridad+antiguedad), 'historico' (el resto, mas recientes primero) o
    'todas'. `estado` admite el pseudo-valor 'activas_archivadas' (archivadas
    sin terminar). Devuelve {"muestras": [...], "total": n} (total = antes del limite)."""
    data = cargar()
    hoy = _hoy()
    por_numero: dict = {}
    for m in data["muestras"]:
        por_numero[m.get("numero")] = por_numero.get(m.get("numero"), 0) + 1
    qk = _clave(q)
    anio_i = None
    try:
        anio_i = int(anio) if anio not in (None, "", "todos") else None
    except (TypeError, ValueError):
        anio_i = None
    prio_i = None
    try:
        prio_i = int(prioridad) if prioridad not in (None, "") else None
    except (TypeError, ValueError):
        prio_i = None
    out = []
    for m in data["muestras"]:
        ec = en_curso(m)
        if vista == "en-curso" and not ec:
            continue
        if vista == "historico" and ec:
            continue
        if estado == "activas_archivadas":
            if not (es_activa(m) and m.get("archivada")):
                continue
        elif estado and (m.get("estado") or "") != estado:
            continue
        if telar and _clave(m.get("telar")) != _clave(telar):
            continue
        if persona and _clave(m.get("encargada_por")) != _clave(persona):
            continue
        if tipo in TIPOS and (m.get("tipo") or "cliente") != tipo:
            continue
        if prio_i is not None and m.get("prioridad") != prio_i:
            continue
        if anio_i is not None and _anio(m.get("fecha_solicitud")) != anio_i:
            continue
        if qk and qk not in _texto_buscable(m):
            continue
        out.append(m)
    if vista == "en-curso":
        out.sort(key=lambda m: (m.get("prioridad") or 9, m.get("fecha_solicitud") or "9999",
                                m.get("numero") or 0, m.get("sufijo") or ""))
    else:
        out.sort(key=lambda m: (m.get("fecha_solicitud") or "0000", m.get("numero") or 0,
                                m.get("sufijo") or ""), reverse=True)
    total = len(out)
    if limite:
        out = out[:limite]
    return {
        "muestras": [_compacta(m, hoy, vista != "en-curso", por_numero.get(m.get("numero"), 1))
                     for m in out],
        "total": total,
    }


def obtener(mid: str) -> dict | None:
    """Ficha completa (copia) + variantes hermanas + dias."""
    data = cargar()
    m = _buscar(data, mid)
    if not m:
        return None
    out = dict(m)
    out["tipo"] = out.get("tipo") or "cliente"
    out["estado_label"] = ESTADOS_LABEL.get(out.get("estado") or "", out.get("estado") or "—")
    out["prioridad_label"] = PRIORIDADES.get(out.get("prioridad") or 0, "")
    out["activa"] = es_activa(m)
    out["en_curso"] = en_curso(m)
    hoy = _hoy()
    if es_activa(m):
        out["dias"], out["dias_tipo"] = _dias_entre(m.get("fecha_solicitud"), hoy), "en_curso"
    else:
        out["dias"], out["dias_tipo"] = _dias_entre(m.get("fecha_solicitud"), m.get("fecha_lista")), "plazo"
    out["variantes"] = [
        {"id": v.get("id"), "sufijo": v.get("sufijo") or "", "estado": v.get("estado"),
         "estado_label": ESTADOS_LABEL.get(v.get("estado") or "", "—"),
         "cliente": v.get("cliente") or "", "fecha_solicitud": v.get("fecha_solicitud"),
         "descripcion": _recortar(v.get("descripcion"), 120)}
        for v in data["muestras"]
        if v.get("numero") is not None and v.get("numero") == m.get("numero") and v is not m
    ]
    out["variantes"].sort(key=lambda v: v["sufijo"])
    return out


def catalogos() -> dict:
    data = cargar()
    cat = data.get("catalogos", {})
    clientes = sorted({(m.get("cliente") or "").strip() for m in data["muestras"]
                       if (m.get("cliente") or "").strip()
                       and (m.get("tipo") or "cliente") != "interna"},
                      key=lambda s: _clave(s))
    personas = list(cat.get("personas") or [])
    for m in data["muestras"]:
        p = (m.get("encargada_por") or "").strip()
        if p and en_curso(m) and not any(_clave(p) == _clave(x) for x in personas):
            personas.append(p)
    return {
        "estados": [{"slug": s, "label": l, "terminal": s in ESTADOS_TERMINALES,
                     "seleccionable": s in ESTADOS_SELECCIONABLES} for s, l in ESTADOS],
        "prioridades": [{"valor": k, "label": v} for k, v in PRIORIDADES.items()],
        "tipos": [{"valor": "cliente", "label": "Cliente"}, {"valor": "interna", "label": "Interna"}],
        "telares": list(cat.get("telares") or []),
        "personas": personas,
        "clientes": clientes,
        "siguiente_numero": int(data["_meta"].get("ultimo_numero") or 0) + 1,
    }


def resumen() -> dict:
    """Cifras de cabecera: en curso por estado, prioridad alta, ritmo del ano."""
    data = cargar()
    hoy = date.today()
    anio = hoy.year
    por_estado = {s: 0 for s, _ in ESTADOS}
    n_curso = n_alta = n_solic = n_term = n_archivadas_activas = 0
    anios = set()
    for m in data["muestras"]:
        a = _anio(m.get("fecha_solicitud"))
        if a:
            anios.add(a)
        if en_curso(m):
            n_curso += 1
            por_estado[m.get("estado") or ""] = por_estado.get(m.get("estado") or "", 0) + 1
            if m.get("prioridad") == 1:
                n_alta += 1
        elif es_activa(m) and m.get("archivada"):
            n_archivadas_activas += 1
        if a == anio:
            n_solic += 1
        if (m.get("estado") == "terminada") and _anio(m.get("fecha_lista")) == anio:
            n_term += 1
    return {
        "en_curso": n_curso,
        "por_estado": por_estado,
        "prioridad_alta": n_alta,
        "solicitadas_anio": n_solic,
        "terminadas_anio": n_term,
        "media_mes_anio": round(n_solic / max(1, hoy.month), 1),
        "archivadas_sin_terminar": n_archivadas_activas,
        "anio": anio,
        "anios": sorted(anios, reverse=True),
        "total": len(data["muestras"]),
        "siguiente_numero": int(data["_meta"].get("ultimo_numero") or 0) + 1,
    }


def analisis(anio=None) -> dict:
    """Cifras para la pestana Analisis: por ano (solicitadas, terminadas,
    canceladas, plazo medio), por mes (ano actual y anterior), y por
    telar/persona (del ano pedido o de todo)."""
    data = cargar()
    hoy = date.today()
    try:
        anio_sel = int(anio) if anio not in (None, "", "todos") else None
    except (TypeError, ValueError):
        anio_sel = None
    por_anio: dict[int, dict] = {}
    por_mes = {hoy.year: [0] * 12, hoy.year - 1: [0] * 12}
    por_telar: dict[str, int] = {}
    por_persona: dict[str, int] = {}
    por_estado_sel: dict[str, int] = {}
    for m in data["muestras"]:
        a = _anio(m.get("fecha_solicitud"))
        if a:
            fila = por_anio.setdefault(a, {"anio": a, "solicitadas": 0, "terminadas": 0,
                                           "canceladas": 0, "plazos": []})
            fila["solicitadas"] += 1
            if a in por_mes:
                try:
                    por_mes[a][int(m["fecha_solicitud"][5:7]) - 1] += 1
                except (TypeError, ValueError, IndexError):
                    pass
        # Terminadas por ano de la fecha lista; si no se apunto (el libro
        # antiguo no la llevaba hasta ~2019), por el de la solicitud.
        al = _anio(m.get("fecha_lista")) or a
        if m.get("estado") == "terminada" and al:
            fila = por_anio.setdefault(al, {"anio": al, "solicitadas": 0, "terminadas": 0,
                                            "canceladas": 0, "plazos": []})
            fila["terminadas"] += 1
            d = _dias_entre(m.get("fecha_solicitud"), m.get("fecha_lista"))
            if d is not None and 0 <= d <= 730:
                fila["plazos"].append(d)
        if m.get("estado") == "cancelada" and a:
            por_anio[a]["canceladas"] += 1
        if anio_sel is None or a == anio_sel:
            t = (m.get("telar") or "").strip() or "—"
            por_telar[t] = por_telar.get(t, 0) + 1
            p = (m.get("encargada_por") or "").strip() or "—"
            por_persona[p] = por_persona.get(p, 0) + 1
            e = m.get("estado") or ""
            por_estado_sel[e] = por_estado_sel.get(e, 0) + 1
    filas = []
    for a in sorted(por_anio, reverse=True):
        f = por_anio[a]
        meses = hoy.month if a == hoy.year else 12
        plazos = f.pop("plazos")
        f["media_mes"] = round(f["solicitadas"] / max(1, meses), 1)
        f["plazo_medio_dias"] = round(sum(plazos) / len(plazos)) if plazos else None
        f["n_plazos"] = len(plazos)
        filas.append(f)
    return {
        "anio_sel": anio_sel,
        "por_anio": filas,
        "por_mes": {str(k): v for k, v in por_mes.items()},
        "por_telar": sorted(({"telar": k, "n": v} for k, v in por_telar.items()),
                            key=lambda x: -x["n"]),
        "por_persona": sorted(({"persona": k, "n": v} for k, v in por_persona.items()),
                              key=lambda x: -x["n"]),
        "por_estado": [{"estado": k, "label": ESTADOS_LABEL.get(k, k or "—"), "n": v}
                       for k, v in sorted(por_estado_sel.items(), key=lambda x: -x[1])],
    }


# ---------------------------------------------------------------------------
# Escritura
# ---------------------------------------------------------------------------

def _validar_texto(v, campo: str, maximo: int = _MAX_TEXTO) -> tuple[str, str]:
    if v is None:
        return "", ""
    if not isinstance(v, str):
        return "", f"{campo} debe ser texto"
    v = v.strip()
    if len(v) > maximo:
        return "", f"{campo} demasiado largo (max {maximo})"
    return v, ""


def _validar_prioridad(v) -> tuple[int | None, str]:
    if v in (None, ""):
        return None, ""
    try:
        p = int(v)
    except (TypeError, ValueError):
        return None, "prioridad debe ser 1, 2 o 3"
    if p not in PRIORIDADES:
        return None, "prioridad debe ser 1, 2 o 3"
    return p, ""


def _validar_fecha(v, campo: str) -> tuple[str | None, str]:
    if v in (None, ""):
        return None, ""
    f = iso_fecha(v)
    if not f:
        return None, f"{campo}: fecha no valida (usa AAAA-MM-DD)"
    return f, ""


def _siguiente_sufijo(data: dict, numero: int) -> tuple[str, str]:
    letras = sorted({(m.get("sufijo") or "") for m in data["muestras"]
                     if m.get("numero") == numero and (m.get("sufijo") or "")})
    letras = [l for l in letras if len(l) == 1]
    if not letras:
        return "B", ""
    ultima = letras[-1]
    if ultima >= "Z":
        return "", f"la muestra {numero} ya no admite mas variantes (llego a la Z)"
    return chr(ord(ultima) + 1), ""


def _anadir_a_catalogo(data: dict, tipo: str, valor: str) -> None:
    valor = (valor or "").strip()
    if not valor:
        return
    lista = data.setdefault("catalogos", {}).setdefault(tipo, [])
    if not any(_clave(x) == _clave(valor) for x in lista):
        lista.append(valor)


def crear(datos: dict, usuario: str | None = None) -> tuple[dict | None, str]:
    """Alta de una muestra. Asigna el numero de M en servidor:
    - `variante_de` (numero base) → siguiente sufijo (B, C, D...).
    - `numero_manual` → ese numero (unico), p.ej. si ya se apunto en el Excel.
    - si no → `_meta.ultimo_numero + 1`."""
    if not isinstance(datos, dict):
        return None, "datos debe ser un objeto"
    cliente, err = _validar_texto(datos.get("cliente"), "cliente", 160)
    if err:
        return None, err
    tipo, err = _validar_tipo(datos.get("tipo"), cliente)
    if err:
        return None, err
    if tipo == "cliente" and not cliente:
        return None, "el cliente es obligatorio (o marca la muestra como interna)"
    descripcion, err = _validar_texto(datos.get("descripcion"), "descripcion")
    if err:
        return None, err
    resultado, err = _validar_texto(datos.get("resultado"), "resultado")
    if err:
        return None, err
    persona = normalizar_persona(datos.get("encargada_por"))
    if len(persona) > 60:
        return None, "encargada_por demasiado largo"
    prioridad, err = _validar_prioridad(datos.get("prioridad", 2))
    if err:
        return None, err
    fecha, err = _validar_fecha(datos.get("fecha_solicitud"), "fecha_solicitud")
    if err:
        return None, err
    fecha = fecha or _hoy()
    estado = normalizar_estado(datos.get("estado")) or "por_empezar"
    if estado not in ESTADOS_SELECCIONABLES:
        return None, f"estado no valido: {datos.get('estado')!r}"
    with jsonstore.store().tx():
        data = cargar()
        telar = normalizar_telar(datos.get("telar"), data["catalogos"].get("telares"))
        if len(telar) > 60:
            return None, "telar demasiado largo"
        variante_de = datos.get("variante_de")
        numero_manual = datos.get("numero_manual")
        if variante_de not in (None, ""):
            _, base, _ = normalizar_numero(variante_de)
            if base is None or not any(m.get("numero") == base for m in data["muestras"]):
                return None, f"no existe ninguna muestra con el numero {variante_de!r}"
            sufijo, err = _siguiente_sufijo(data, base)
            if err:
                return None, err
            numero = base
        elif numero_manual not in (None, ""):
            try:
                numero = int(numero_manual)
            except (TypeError, ValueError):
                return None, "numero_manual debe ser un entero"
            if numero <= 0 or numero > 99999:
                return None, "numero_manual fuera de rango"
            sufijo = ""
            if _buscar(data, str(numero)):
                return None, f"ya existe la muestra M-{numero}"
            if numero > int(data["_meta"].get("ultimo_numero") or 0):
                data["_meta"]["ultimo_numero"] = numero
        else:
            numero = int(data["_meta"].get("ultimo_numero") or 0) + 1
            while _buscar(data, str(numero)):
                numero += 1
            sufijo = ""
            data["_meta"]["ultimo_numero"] = numero
        mid = f"{numero}-{sufijo}" if sufijo else str(numero)
        if _buscar(data, mid):
            return None, f"ya existe la muestra M-{mid}"
        ahora = _ahora()
        nueva = {
            "id": mid, "numero": numero, "sufijo": sufijo,
            "fecha_solicitud": fecha, "cliente": cliente, "tipo": tipo,
            "encargada_por": persona, "prioridad": prioridad if prioridad is not None else 2,
            "telar": telar, "estado": estado, "fecha_lista": None, "archivada": False,
            "descripcion": descripcion, "anotacion_registro": "", "resultado": resultado,
            "apuntes": [], "historial": [],
            "creado_en": ahora, "actualizado_en": ahora, "creado_por": usuario or None,
        }
        _historial(nueva, usuario, "creacion",
                   texto=(f"Variante de M-{numero}" if sufijo else "Alta de la muestra"))
        _anadir_a_catalogo(data, "telares", telar)
        _anadir_a_catalogo(data, "personas", persona)
        data["muestras"].append(nueva)
        _guardar(data)
        return obtener(mid), ""


def actualizar(mid: str, datos: dict, usuario: str | None = None) -> tuple[dict | None, str]:
    """Edita campos de la ficha (solo los que vengan en `datos`)."""
    if not isinstance(datos, dict):
        return None, "datos debe ser un objeto"
    desconocidos = set(datos) - CAMPOS_EDITABLES
    if desconocidos:
        return None, f"campos no editables: {sorted(desconocidos)}"
    with jsonstore.store().tx():
        data = cargar()
        m = _buscar(data, mid)
        if not m:
            return None, f"la muestra {mid!r} no existe"
        tipo_final = m.get("tipo") or "cliente"
        if "tipo" in datos:
            tipo_final, err = _validar_tipo(datos.get("tipo"), None)
            if err:
                return None, err
        cambios = []
        for k, v in datos.items():
            if k == "tipo":
                v = tipo_final
            elif k in ("cliente", "descripcion", "resultado", "anotacion_registro"):
                v, err = _validar_texto(v, k, 160 if k == "cliente" else _MAX_TEXTO)
                if err:
                    return None, err
                if k == "cliente" and not v and tipo_final == "cliente":
                    return None, "el cliente no puede quedar vacio (o marca la muestra como interna)"
            elif k == "prioridad":
                v, err = _validar_prioridad(v)
                if err:
                    return None, err
            elif k in ("fecha_solicitud", "fecha_lista"):
                v, err = _validar_fecha(v, k)
                if err:
                    return None, err
                if k == "fecha_solicitud" and not v:
                    return None, "la fecha de solicitud es obligatoria"
            elif k == "telar":
                v = normalizar_telar(v, data["catalogos"].get("telares"))
                if len(v) > 60:
                    return None, "telar demasiado largo"
                _anadir_a_catalogo(data, "telares", v)
            elif k == "encargada_por":
                v = normalizar_persona(v)
                if len(v) > 60:
                    return None, "encargada_por demasiado largo"
                _anadir_a_catalogo(data, "personas", v)
            if m.get(k) != v:
                cambios.append((k, m.get(k), v))
                m[k] = v
        if tipo_final == "cliente" and not (m.get("cliente") or "").strip():
            return None, "una muestra de cliente necesita el nombre del cliente"
        if cambios:
            for k, de, a in cambios:
                _historial(m, usuario, "campo", campo=k,
                           de=_recortar(str(de) if de is not None else "", 80),
                           a=_recortar(str(a) if a is not None else "", 80))
            m["actualizado_en"] = _ahora()
            _guardar(data)
        return obtener(mid), ""


def cambiar_estado(mid: str, estado: str, usuario: str | None = None,
                   nota: str = "", fecha: str | None = None) -> tuple[dict | None, str]:
    """Mueve la muestra de estado. Al pasar a 'terminada' fija fecha_lista
    (si no la tenia) y al reabrir una terminada/cancelada la limpia y la
    desarchiva. `nota` (opcional) se guarda ademas como apunte del diario."""
    slug = normalizar_estado(estado)
    if not slug or slug not in ESTADOS_SELECCIONABLES:
        return None, f"estado no valido: {estado!r}"
    nota, err = _validar_texto(nota, "nota", 2000)
    if err:
        return None, err
    fecha, err = _validar_fecha(fecha, "fecha")
    if err:
        return None, err
    fecha = fecha or _hoy()
    with jsonstore.store().tx():
        data = cargar()
        m = _buscar(data, mid)
        if not m:
            return None, f"la muestra {mid!r} no existe"
        anterior = m.get("estado") or ""
        if anterior != slug:
            m["estado"] = slug
            if slug == "terminada":
                if not m.get("fecha_lista"):
                    m["fecha_lista"] = fecha
            elif slug not in ESTADOS_TERMINALES and anterior in ESTADOS_TERMINALES:
                m["fecha_lista"] = None
                m["archivada"] = False
            _historial(m, usuario, "estado", de=anterior, a=slug,
                       nota=nota or "", fecha_efecto=fecha)
        if nota:
            m.setdefault("apuntes", []).append(
                {"id": _nuevo_id_apunte(), "fecha": fecha, "texto": nota, "usuario": usuario or None})
        m["actualizado_en"] = _ahora()
        _guardar(data)
        return obtener(mid), ""


def archivar(mid: str, usuario: str | None = None, valor: bool = True) -> tuple[dict | None, str]:
    """Saca (o devuelve) una muestra de 'En curso' sin tocar su estado —
    lo que en el Excel era mover la fila a la hoja de terminadas."""
    with jsonstore.store().tx():
        data = cargar()
        m = _buscar(data, mid)
        if not m:
            return None, f"la muestra {mid!r} no existe"
        if bool(m.get("archivada")) != bool(valor):
            m["archivada"] = bool(valor)
            m["archivada_en"] = _ahora() if valor else None
            _historial(m, usuario, "archivo", a=("archivada" if valor else "reabierta"))
            m["actualizado_en"] = _ahora()
            _guardar(data)
        return obtener(mid), ""


def anadir_apunte(mid: str, texto: str, usuario: str | None = None,
                  fecha: str | None = None) -> tuple[dict | None, str]:
    texto, err = _validar_texto(texto, "texto", 4000)
    if err:
        return None, err
    if not texto:
        return None, "el apunte no puede estar vacio"
    fecha, err = _validar_fecha(fecha, "fecha")
    if err:
        return None, err
    with jsonstore.store().tx():
        data = cargar()
        m = _buscar(data, mid)
        if not m:
            return None, f"la muestra {mid!r} no existe"
        m.setdefault("apuntes", []).append(
            {"id": _nuevo_id_apunte(), "fecha": fecha or _hoy(), "texto": texto,
             "usuario": usuario or None})
        m["actualizado_en"] = _ahora()
        _guardar(data)
        return obtener(mid), ""


def editar_apunte(mid: str, apunte_id: str, texto: str | None = None,
                  fecha: str | None = None, usuario: str | None = None) -> tuple[dict | None, str]:
    with jsonstore.store().tx():
        data = cargar()
        m = _buscar(data, mid)
        if not m:
            return None, f"la muestra {mid!r} no existe"
        ap = next((a for a in m.get("apuntes", []) if a.get("id") == apunte_id), None)
        if not ap:
            return None, "el apunte no existe"
        if texto is not None:
            texto, err = _validar_texto(texto, "texto", 4000)
            if err:
                return None, err
            if not texto:
                return None, "el apunte no puede estar vacio"
            ap["texto"] = texto
        if fecha is not None:
            f, err = _validar_fecha(fecha, "fecha")
            if err:
                return None, err
            ap["fecha"] = f
        ap["editado_por"] = usuario or None
        ap["editado_en"] = _ahora()
        m["actualizado_en"] = _ahora()
        _guardar(data)
        return obtener(mid), ""


def borrar_apunte(mid: str, apunte_id: str, usuario: str | None = None) -> tuple[dict | None, str]:
    with jsonstore.store().tx():
        data = cargar()
        m = _buscar(data, mid)
        if not m:
            return None, f"la muestra {mid!r} no existe"
        apuntes = m.get("apuntes", [])
        idx = next((i for i, a in enumerate(apuntes) if a.get("id") == apunte_id), -1)
        if idx < 0:
            return None, "el apunte no existe"
        quitado = apuntes.pop(idx)
        _historial(m, usuario, "apunte_borrado", texto=_recortar(quitado.get("texto"), 80),
                   fecha_apunte=quitado.get("fecha"))
        m["actualizado_en"] = _ahora()
        _guardar(data)
        return obtener(mid), ""


def borrar(mid: str) -> tuple[bool, str]:
    """Elimina la muestra. Pensado para altas por error: para lo demas esta
    'cancelada' (queda el historico)."""
    with jsonstore.store().tx():
        data = cargar()
        idx = next((i for i, m in enumerate(data["muestras"])
                    if (m.get("id") or "").upper() == (mid or "").strip().upper()), -1)
        if idx < 0:
            return False, f"la muestra {mid!r} no existe"
        del data["muestras"][idx]
        _guardar(data)
        return True, ""


def anadir_catalogo(tipo: str, valor: str) -> tuple[list | None, str]:
    if tipo not in ("telares", "personas"):
        return None, "catalogo desconocido"
    valor, err = _validar_texto(valor, "valor", 60)
    if err:
        return None, err
    if not valor:
        return None, "el valor no puede estar vacio"
    with jsonstore.store().tx():
        data = cargar()
        _anadir_a_catalogo(data, tipo, valor)
        _guardar(data)
        return list(data["catalogos"][tipo]), ""


# ---------------------------------------------------------------------------
# CLI util
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys
    if not sys.argv[1:] or sys.argv[1] == "list":
        r = listar("en-curso")
        for m in r["muestras"]:
            print(f"  M-{m['id']:<8s} {m['estado_label']:<18s} {m['cliente'][:28]:<28s} "
                  f"{m['telar']:<10s} p{m['prioridad']}  {m['fecha_solicitud']}")
        print(f"{r['total']} en curso · resumen: {resumen()}")
    elif sys.argv[1] == "ver" and len(sys.argv) > 2:
        import json
        print(json.dumps(obtener(sys.argv[2]), ensure_ascii=False, indent=2))
    else:
        print("Uso: python muestras_fabricadas.py [list | ver <id>]")
