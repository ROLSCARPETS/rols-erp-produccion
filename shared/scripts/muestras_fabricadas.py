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
from datetime import date, datetime, timedelta
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
_FLUJO_IDX = {s: i for i, s in enumerate(ESTADOS_FLUJO)}

PRIORIDADES = {1: "Alta", 2: "Media", 3: "Baja"}

# Muestra para un cliente o desarrollo propio (lo que el libro apuntaba como
# "INTERNA ( NANDO )", "MOQUETAS ROLS", "ROLS (PACO)"...).
TIPOS = ("cliente", "interna")
_VERSION_SCHEMA = 5

# "Solo diseño" y "Escala" del libro antiguo se unificaron en Print y Rapier
# (sept 2026); normalizar_telar los sigue reconociendo como alias.
TELARES_DEFAULT = ["Print", "Tufting", "Colortec", "Varilla", "Lancetas",
                   "Raschel", "Pompón", "Kibby", "Rapier", "Festón"]

# Datos tecnicos de la muestra cuando el telar es Varilla: material, pasadas,
# altura de felpa, pelo (corte / bucle / corte y bucle) y acabado (latex /
# sin aprestar). Van planos en la muestra y la UI los ensena solo con telar
# de varilla (si cambia de telar se conservan, no se borran).
PELOS: tuple[tuple[str, str], ...] = (("corte", "Corte"), ("bucle", "Bucle"),
                                      ("corte_bucle", "Corte y bucle"))
ACABADOS: tuple[tuple[str, str], ...] = (("latex", "Látex"), ("sin_aprestar", "Sin aprestar"))
PELOS_LABEL = dict(PELOS)
ACABADOS_LABEL = dict(ACABADOS)
CAMPOS_TECNICOS = ("material", "pasadas", "altura_felpa", "pelo", "acabado")

# Adjuntos de la muestra (el diseno): los ficheros van a
# ROLS_DATA_DIR/muestras_adjuntos/<id de la muestra>/<id adjunto>.<ext> y los
# metadatos en `adjuntos[]` de la muestra (nunca la ruta en disco).
ADJUNTOS_DIR = DATA_PATH.parent / "muestras_adjuntos"
ADJUNTO_EXTENSIONES = {"png", "jpg", "jpeg", "gif", "webp", "bmp", "tif", "tiff", "svg",
                       "pdf", "ai", "eps", "psd", "zip"}
ADJUNTO_MAX_BYTES = 25 * 1024 * 1024
# Tipos que el navegador puede abrir en la propia pestana; el resto se descarga.
ADJUNTO_INLINE = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
                  "gif": "image/gif", "webp": "image/webp", "pdf": "application/pdf"}
# Quien encarga la muestra debe ser un USUARIO DE ROLS ONE (cuentas): la lista
# viva llega desde app.py (`usuarios_one`, endpoint de cuentas
# /api/usuarios/con-permiso). Los nombres cortos del libro antiguo con usuario
# se pasaron a su cuenta (v3); los que no tienen usuario (Paco, Emilio,
# Blanca...) quedan como "antiguos": valen para filtrar el historico pero no
# para muestras nuevas.
_PERSONAS_LEGACY_A_ONE = {
    "fernando": ("Fernando Ferrández", "fernando@rolscarpets.com"),
    "jm":       ("Jose Manuel Sánchez", "jose manuel"),
    "damian":   ("Damián Fuentes", "damian"),
    "carmen":   ("Carmen Ferrández", "carmen"),
    "romu":     ("Romu Más", "romu"),
    "victor":   ("Víctor Penalva", "víctor"),
    "alberto":  ("Alberto Recio", "alberto"),      # v4
}

CAMPOS_EDITABLES = {
    "tipo", "cliente", "cliente_navision", "descripcion", "encargada_por",
    # Referencia muestra: resumen corto (una linea) que sale en el listado;
    # `descripcion` sigue siendo el texto largo.
    "referencia",
    "prioridad", "telar", "fecha_solicitud", "fecha_lista", "resultado",
    "anotacion_registro",
    # Fecha estimada de muestra lista (prevision mientras esta en curso;
    # fecha_lista es la real, la fija 'terminada').
    "fecha_estimada",
    # Proximo hito: fecha del siguiente paso previsto (llegan los colores,
    # entra a telar...) para que comercial y laboratorio sepan cuando mirar.
    "proximo_hito_fecha", "proximo_hito",
    # Datos tecnicos (telar de varilla)
    *CAMPOS_TECNICOS,
}
_MAX_TEXTO = 6000


# ---------------------------------------------------------------------------
# Persistencia
# ---------------------------------------------------------------------------

def _default() -> dict:
    return {
        "_meta": {"version_schema": _VERSION_SCHEMA, "ultimo_numero": 0},
        "catalogos": {"telares": list(TELARES_DEFAULT), "personas_legacy": []},
        "muestras": [],
    }


def _cargar_sin_migrar() -> dict:
    data = jsonstore.store().load(_KEY, _default, DATA_PATH)
    data.setdefault("_meta", {}).setdefault("ultimo_numero", 0)
    cat = data.setdefault("catalogos", {})
    cat.setdefault("telares", list(TELARES_DEFAULT))
    cat.setdefault("personas_legacy", [])
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
            v = _version(data)
            if v < _VERSION_SCHEMA:
                if v < 2:
                    _migrar_v2(data)
                if v < 4:
                    # v3 (usuarios de One) es idempotente; v4 solo amplia el
                    # mapeo (Alberto → Alberto Recio), asi que se reaplica.
                    _migrar_v3(data)
                if v < 5:
                    _migrar_v5(data)
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


def _migrar_v3(data: dict) -> None:
    """v2 → v3 (sept 2026): quien encarga pasa a ser un usuario de Rols One.
    Los nombres cortos del libro con cuenta se renombran (Fernando →
    Fernando Ferrández...) y guardan `encargada_por_usuario`; el resto queda
    como nombre antiguo en catalogos.personas_legacy. Idempotente."""
    legacy = set()
    for m in data.get("muestras", []):
        nombre = (m.get("encargada_por") or "").strip()
        if not nombre:
            continue
        ref = _PERSONAS_LEGACY_A_ONE.get(_clave(nombre))
        if ref:
            m["encargada_por"], m["encargada_por_usuario"] = ref
        elif not m.get("encargada_por_usuario"):
            legacy.add(nombre)
    cat = data.setdefault("catalogos", {})
    cat.pop("personas", None)
    cat["personas_legacy"] = sorted(legacy, key=_clave)


# v5 (sept 2026): "Referencia muestra" escrita a mano para las muestras que
# estaban en curso al estrenar el campo (resumen de su descripcion del libro).
_REFERENCIAS_V5 = {
    "5486-B": "Print Colortec 1300 g, diseño pasillos y salientes adaptado, colores 025 y 075",
    "5448-C": "2 muestras Wilton 30 TRAP, lana 100 3/c crema + 5/c caramel, picado doble",
    "5448-D": "3 muestras Wilton 30 TRAP, lana 100 4/c + 6/c, picado doble",
    "5448-E": "3 muestras Wilton 30 TRAP, lana 100 6/c + 8/c, picado doble",
    "5448-F": "Muestra Wilton 30 TRAP, lana 100 4/c + 6/c, picado doble, comb. cream / mocha",
    "5502": "Print Colortec 2.300 g",
    "5505": "6 muestras tejido plano (rombos, cuadros, dunas), calidades Maya y Nórdica",
    "5506": "Print Colortec 1400 g, 2 colores, diseño especial con logo del hotel",
    "5507": "Kibby Colortec",
    "5473-C": "4 muestras Lancetas 32x32, dib. 7516 jaspeado base latte, 4 combinaciones, calidad Manuela",
    "5510": "2 muestras Lancetas 32x36, chevron doble espiga, crudo / caramel, lana 140/4",
    "5512": "Prints",
    "5515": "Pompones de laboratorio Stria (Capasso / Carabello), lana 65 2/c, sage green",
    "5499-B": "Muestra Tufting 1/10 Paradise, nylon eco 1800/420, terciopelo suave termoendurecido",
    "5516": "Muestra Lancetas 32x36, dib. Lite, fileta degradé lana 140 5/c y 6/c, trama enfeltrado",
    "5517": "Muestras Palma, dibujo especial",
    "5522": "Print Wilton 30, dibujo pindot",
    "5525": "Print Colortec 1.100 g",
    "5528": "Print Wilton 4 cuerpos",
    "5530": "Print Wilton 4 cuerpos",
}


def _migrar_v5(data: dict) -> None:
    """v4 → v5: estrena `referencia` (resumen corto). Las muestras que estaban
    en curso reciben la referencia escrita a mano; el resto queda vacia (el
    listado ensena la descripcion mientras no tengan). Idempotente: no pisa
    una referencia ya puesta."""
    for m in data.get("muestras", []):
        if (m.get("referencia") or "").strip():
            continue
        ref = _REFERENCIAS_V5.get(str(m.get("id") or ""))
        if ref:
            m["referencia"] = ref


def _personas_conocidas(data: dict, usuarios_one, usuario_actual) -> list[dict]:
    """Usuarios de One que pueden encargar muestras [{nombre, usuario}]: la
    lista viva de cuentas si llega; si no (cuentas caido), los que ya aparecen
    en las muestras con usuario. El usuario de la sesion siempre esta."""
    out: list[dict] = []
    vistos: set[str] = set()

    def add(nombre, usuario):
        nombre = (nombre or "").strip()
        usuario = (usuario or "").strip().lower()
        if not nombre or not usuario or usuario in vistos:
            return
        vistos.add(usuario)
        out.append({"nombre": nombre, "usuario": usuario})

    if usuarios_one:
        for u in usuarios_one:
            if isinstance(u, dict):
                add(u.get("nombre"), u.get("username") or u.get("usuario"))
    else:
        for m in data.get("muestras", []):
            if m.get("encargada_por_usuario"):
                add(m.get("encargada_por"), m.get("encargada_por_usuario"))
    if isinstance(usuario_actual, dict):
        add(usuario_actual.get("nombre") or usuario_actual.get("username"),
            usuario_actual.get("username") or usuario_actual.get("usuario"))
    out.sort(key=lambda p: _clave(p["nombre"]))
    return out


def _resolver_persona(valor, personas: list[dict]) -> tuple[str, str | None, str]:
    """(nombre, usuario, error). Acepta el usuario o el nombre de una persona
    conocida; vacio = sin asignar. Sin lista (arranque vacio) no bloquea."""
    v = normalizar_persona(valor)
    if not v:
        return "", None, ""
    if len(v) > 80:
        return "", None, "encargada_por demasiado largo"
    k = _clave(v)
    for p in personas:
        if _clave(p["usuario"]) == k or _clave(p["nombre"]) == k:
            return p["nombre"], p["usuario"], ""
    if not personas:
        return v, None, ""
    return "", None, f"{v!r} no es un usuario de Rols One con acceso a muestras"


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


def _hito_vencido(m: dict, hoy: str) -> bool:
    """Proximo hito con fecha pasada en una muestra aun activa."""
    f = m.get("proximo_hito_fecha")
    return bool(f) and es_activa(m) and f < hoy


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


def _actor_username(u) -> str | None:
    """`usuario` puede ser el username (str) o {username, nombre} (app.py)."""
    if isinstance(u, dict):
        return (u.get("username") or u.get("usuario") or "").strip().lower() or None
    return (str(u).strip().lower() or None) if u else None


def _actor_nombre(u) -> str | None:
    if isinstance(u, dict):
        return (u.get("nombre") or "").strip() or None
    return None


def _historial(m: dict, usuario, tipo: str, **extra) -> None:
    m.setdefault("historial", []).append(
        {"fecha": _ahora(), "usuario": _actor_username(usuario),
         "usuario_nombre": _actor_nombre(usuario), "tipo": tipo, **extra})


def _texto_buscable(m: dict) -> str:
    partes = [m.get("id"), m.get("cliente"), m.get("cliente_navision"), m.get("referencia"), m.get("descripcion"),
              m.get("anotacion_registro"), m.get("resultado"),
              m.get("encargada_por"), m.get("telar"), m.get("material"),
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
        "cliente_navision": m.get("cliente_navision"),
        "encargada_por": m.get("encargada_por") or "",
        "encargada_por_usuario": m.get("encargada_por_usuario"),
        "prioridad": m.get("prioridad"),
        "telar": m.get("telar") or "", "estado": estado,
        "estado_label": ESTADOS_LABEL.get(estado, estado or "—"),
        "fecha_lista": m.get("fecha_lista"), "archivada": bool(m.get("archivada")),
        "fecha_estimada": m.get("fecha_estimada"),
        "proximo_hito_fecha": m.get("proximo_hito_fecha"),
        "proximo_hito": m.get("proximo_hito") or "",
        "hito_vencido": _hito_vencido(m, hoy),
        "referencia": m.get("referencia") or "",
        "descripcion": _recortar(m.get("descripcion"), 220) if recortar_textos else (m.get("descripcion") or ""),
        "resultado": _recortar(m.get("resultado"), 160),
        "ultimo_apunte": ({"fecha": ultimo.get("fecha"), "texto": _recortar(ultimo.get("texto"), 180),
                           "usuario_nombre": ultimo.get("usuario_nombre") or ultimo.get("usuario")}
                          if ultimo else None),
        "n_apuntes": len(apuntes), "dias": dias, "dias_tipo": dias_tipo,
        "n_variantes": n_variantes,
        "n_adjuntos": len(m.get("adjuntos") or []),
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
        if persona and _clave(persona) not in _clave(m.get("encargada_por")):
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
    out["referencia"] = out.get("referencia") or ""
    out["estado_label"] = ESTADOS_LABEL.get(out.get("estado") or "", out.get("estado") or "—")
    out["prioridad_label"] = PRIORIDADES.get(out.get("prioridad") or 0, "")
    out["activa"] = es_activa(m)
    out["en_curso"] = en_curso(m)
    hoy = _hoy()
    if es_activa(m):
        out["dias"], out["dias_tipo"] = _dias_entre(m.get("fecha_solicitud"), hoy), "en_curso"
    else:
        out["dias"], out["dias_tipo"] = _dias_entre(m.get("fecha_solicitud"), m.get("fecha_lista")), "plazo"
    out["hito_vencido"] = _hito_vencido(m, hoy)
    for k in CAMPOS_TECNICOS:
        out[k] = out.get(k) or ""
    out["es_varilla"] = _es_telar_tecnico(m.get("telar"))
    out["tecnica_resumen"] = resumen_tecnico(m)
    out["adjuntos"] = _adjuntos_publicos(m.get("adjuntos") or [])
    out["variantes"] = [
        {"id": v.get("id"), "sufijo": v.get("sufijo") or "", "estado": v.get("estado"),
         "estado_label": ESTADOS_LABEL.get(v.get("estado") or "", "—"),
         "cliente": v.get("cliente") or "", "fecha_solicitud": v.get("fecha_solicitud"),
         "referencia": v.get("referencia") or "",
         "descripcion": _recortar(v.get("descripcion"), 120)}
        for v in data["muestras"]
        if v.get("numero") is not None and v.get("numero") == m.get("numero") and v is not m
    ]
    out["variantes"].sort(key=lambda v: v["sufijo"])
    return out


def catalogos(usuarios_one=None, usuario_actual=None) -> dict:
    """`usuarios_one`: lista viva de cuentas [{username, nombre}] (None si no
    llega); `usuario_actual`: {username, nombre} de la sesion."""
    data = cargar()
    cat = data.get("catalogos", {})
    clientes = sorted({(m.get("cliente") or "").strip() for m in data["muestras"]
                       if (m.get("cliente") or "").strip()
                       and (m.get("tipo") or "cliente") != "interna"},
                      key=lambda s: _clave(s))
    materiales = sorted({(m.get("material") or "").strip() for m in data["muestras"]
                         if (m.get("material") or "").strip()}, key=_clave)
    activas = _personas_conocidas(data, usuarios_one, usuario_actual)
    nombres_activas = {_clave(p["nombre"]) for p in activas}
    legacy = sorted({(m.get("encargada_por") or "").strip() for m in data["muestras"]
                     if (m.get("encargada_por") or "").strip()
                     and _clave(m.get("encargada_por")) not in nombres_activas},
                    key=_clave)
    return {
        "estados": [{"slug": s, "label": l, "terminal": s in ESTADOS_TERMINALES,
                     "seleccionable": s in ESTADOS_SELECCIONABLES} for s, l in ESTADOS],
        "prioridades": [{"valor": k, "label": v} for k, v in PRIORIDADES.items()],
        "tipos": [{"valor": "cliente", "label": "Cliente"}, {"valor": "interna", "label": "Interna"}],
        "telares": list(cat.get("telares") or []),
        # activas = pueden encargar muestras nuevas; legacy = solo para filtrar
        "personas_activas": activas,
        "personas_legacy": legacy,
        "personas": [p["nombre"] for p in activas] + legacy,
        "usuarios_one_disponibles": usuarios_one is not None,
        "clientes": clientes,
        # Datos tecnicos (telar de varilla)
        "pelos": [{"valor": s, "label": l} for s, l in PELOS],
        "acabados": [{"valor": s, "label": l} for s, l in ACABADOS],
        "materiales": materiales,
        "siguiente_numero": int(data["_meta"].get("ultimo_numero") or 0) + 1,
    }


def resumen() -> dict:
    """Cifras de cabecera: en curso por estado, prioridad alta, ritmo del ano."""
    data = cargar()
    hoy = date.today()
    anio = hoy.year
    por_estado = {s: 0 for s, _ in ESTADOS}
    n_curso = n_alta = n_solic = n_term = n_archivadas_activas = 0
    n_hito_venc = n_hito_sem = 0
    hoy_iso = hoy.isoformat()
    semana_iso = (hoy + timedelta(days=7)).isoformat()
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
            f = m.get("proximo_hito_fecha")
            if f:
                if f < hoy_iso:
                    n_hito_venc += 1
                elif f <= semana_iso:
                    n_hito_sem += 1
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
        "hitos_vencidos": n_hito_venc,
        "hitos_semana": n_hito_sem,
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


def _validar_codigo_navision(v) -> tuple[str | None, str]:
    """Codigo de cliente de Navision (C6535, D2158...). Vacio = sin vincular."""
    if v in (None, ""):
        return None, ""
    if not isinstance(v, str):
        return None, "cliente_navision debe ser texto"
    v = v.strip().upper()
    if len(v) > 30 or not re.fullmatch(r"[A-Z0-9][A-Z0-9._/-]*", v):
        return None, "cliente_navision no parece un codigo de cliente"
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


def _validar_referencia(v) -> tuple[str, str]:
    """Referencia muestra: una sola linea de hasta 120 caracteres."""
    v, err = _validar_texto(v, "referencia", 400)
    if err:
        return "", err
    v = " ".join(v.split())
    if len(v) > 120:
        return "", "referencia demasiado larga (max 120)"
    return v, ""


def _validar_opcion(v, campo: str, opciones) -> tuple[str, str]:
    """Selector cerrado: acepta el slug o la etiqueta (sin distinguir
    mayusculas ni acentos). Vacio = sin dato."""
    if v is None:
        return "", ""
    if not isinstance(v, str):
        return "", f"{campo} debe ser texto"
    v = v.strip()
    if not v:
        return "", ""
    for slug, label in opciones:
        if v.lower() == slug or _clave(v) == _clave(label):
            return slug, ""
    return "", f"{campo} no valido: {v!r} (" + ", ".join(s for s, _ in opciones) + ")"


def _validar_tecnico(k: str, v) -> tuple[str, str]:
    """Campos tecnicos del telar de varilla."""
    if k == "pelo":
        return _validar_opcion(v, k, PELOS)
    if k == "acabado":
        return _validar_opcion(v, k, ACABADOS)
    return _validar_texto(v, k, 200 if k == "material" else 40)


def _es_telar_tecnico(telar) -> bool:
    return (telar or "").strip().lower().startswith("varilla")


def resumen_tecnico(m: dict) -> str:
    """'Lana 100 3/c · 30 pasadas · felpa 12 mm · Corte · Látex' (solo lo
    relleno y solo si el telar es de varilla)."""
    if not _es_telar_tecnico(m.get("telar")):
        return ""
    partes = []
    mat = (m.get("material") or "").strip()
    if mat:
        partes.append(mat)
    pas = (m.get("pasadas") or "").strip()
    if pas:
        partes.append(pas if "pasada" in pas.lower() else f"{pas} pasadas")
    alt = (m.get("altura_felpa") or "").strip()
    if alt:
        partes.append(alt if "felpa" in alt.lower() else f"felpa {alt}")
    if m.get("pelo"):
        partes.append(PELOS_LABEL.get(m["pelo"], m["pelo"]))
    if m.get("acabado"):
        partes.append(ACABADOS_LABEL.get(m["acabado"], m["acabado"]))
    return " · ".join(partes)


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


def crear(datos: dict, usuario: str | None = None, usuarios_one=None,
          usuario_actual=None) -> tuple[dict | None, str]:
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
    cliente_navision, err = _validar_codigo_navision(datos.get("cliente_navision"))
    if err:
        return None, err
    descripcion, err = _validar_texto(datos.get("descripcion"), "descripcion")
    if err:
        return None, err
    referencia, err = _validar_referencia(datos.get("referencia"))
    if err:
        return None, err
    resultado, err = _validar_texto(datos.get("resultado"), "resultado")
    if err:
        return None, err
    hito_fecha, err = _validar_fecha(datos.get("proximo_hito_fecha"), "proximo_hito_fecha")
    if err:
        return None, err
    fecha_estimada, err = _validar_fecha(datos.get("fecha_estimada"), "fecha_estimada")
    if err:
        return None, err
    hito_txt, err = _validar_texto(datos.get("proximo_hito"), "proximo_hito", 200)
    if err:
        return None, err
    tecnicos = {}
    for k in CAMPOS_TECNICOS:
        tecnicos[k], err = _validar_tecnico(k, datos.get(k))
        if err:
            return None, err
    persona_raw = datos.get("encargada_por")
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
        persona, persona_usuario, err = _resolver_persona(
            persona_raw, _personas_conocidas(data, usuarios_one, usuario_actual))
        if err:
            return None, err
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
            "cliente_navision": cliente_navision,
            "encargada_por": persona, "encargada_por_usuario": persona_usuario,
            "prioridad": prioridad if prioridad is not None else 2,
            "telar": telar, "estado": estado, "fecha_lista": None, "archivada": False,
            "referencia": referencia,
            "descripcion": descripcion, "anotacion_registro": "", "resultado": resultado,
            "proximo_hito_fecha": hito_fecha, "proximo_hito": hito_txt,
            "fecha_estimada": fecha_estimada,
            **tecnicos, "adjuntos": [],
            "apuntes": [], "historial": [],
            "creado_en": ahora, "actualizado_en": ahora,
            "creado_por": _actor_username(usuario), "creado_por_nombre": _actor_nombre(usuario),
        }
        _historial(nueva, usuario, "creacion",
                   texto=(f"Variante de M-{numero}" if sufijo else "Alta de la muestra"))
        _anadir_a_catalogo(data, "telares", telar)
        data["muestras"].append(nueva)
        _guardar(data)
        return obtener(mid), ""


def actualizar(mid: str, datos: dict, usuario: str | None = None, usuarios_one=None,
               usuario_actual=None) -> tuple[dict | None, str]:
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
            elif k == "cliente_navision":
                v, err = _validar_codigo_navision(v)
                if err:
                    return None, err
            elif k == "referencia":
                v, err = _validar_referencia(v)
                if err:
                    return None, err
            elif k in ("cliente", "descripcion", "resultado", "anotacion_registro"):
                v, err = _validar_texto(v, k, 160 if k == "cliente" else _MAX_TEXTO)
                if err:
                    return None, err
                if k == "cliente" and not v and tipo_final == "cliente":
                    return None, "el cliente no puede quedar vacio (o marca la muestra como interna)"
            elif k == "proximo_hito_fecha":
                v, err = _validar_fecha(v, k)
                if err:
                    return None, err
            elif k == "proximo_hito":
                v, err = _validar_texto(v, k, 200)
                if err:
                    return None, err
            elif k in CAMPOS_TECNICOS:
                v, err = _validar_tecnico(k, v)
                if err:
                    return None, err
            elif k == "prioridad":
                v, err = _validar_prioridad(v)
                if err:
                    return None, err
            elif k in ("fecha_solicitud", "fecha_lista", "fecha_estimada"):
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
                v, v_usuario, err = _resolver_persona(
                    v, _personas_conocidas(data, usuarios_one, usuario_actual))
                if err:
                    return None, err
                m["encargada_por_usuario"] = v_usuario
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
    desarchiva. Cada cambio de etapa queda tambien como apunte del diario
    del laboratorio (`tipo: "estado"`, con la `nota` opcional a continuacion);
    si el estado no cambia, la nota se guarda como apunte normal."""
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
            if slug in ESTADOS_TERMINALES and (m.get("proximo_hito_fecha") or m.get("proximo_hito")):
                m["proximo_hito_fecha"] = None
                m["proximo_hito"] = ""
            elif slug not in ESTADOS_TERMINALES and anterior in ESTADOS_TERMINALES:
                m["fecha_lista"] = None
                m["archivada"] = False
            _historial(m, usuario, "estado", de=anterior, a=slug,
                       nota=nota or "", fecha_efecto=fecha)
            # El cambio de etapa se apunta tambien en el diario del laboratorio
            m.setdefault("apuntes", []).append(
                {"id": _nuevo_id_apunte(), "fecha": fecha,
                 "texto": _texto_cambio_estado(anterior, slug, nota),
                 "tipo": "estado", "estado_de": anterior, "estado": slug,
                 "usuario": _actor_username(usuario), "usuario_nombre": _actor_nombre(usuario)})
        elif nota:
            m.setdefault("apuntes", []).append(
                {"id": _nuevo_id_apunte(), "fecha": fecha, "texto": nota,
                 "usuario": _actor_username(usuario), "usuario_nombre": _actor_nombre(usuario)})
        m["actualizado_en"] = _ahora()
        _guardar(data)
        return obtener(mid), ""


def _texto_cambio_estado(anterior: str, nuevo: str, nota: str = "") -> str:
    """Frase del apunte automatico del diario al cambiar de etapa."""
    a = ESTADOS_LABEL.get(nuevo, nuevo)
    if nuevo == "terminada":
        frase = "Muestra terminada."
    elif nuevo == "cancelada":
        frase = "Muestra cancelada."
    elif anterior in ESTADOS_TERMINALES:
        frase = f"Se reabre la muestra: vuelve a «{a}»."
    else:
        ia, ib = _FLUJO_IDX.get(anterior), _FLUJO_IDX.get(nuevo)
        frase = f"Vuelve a «{a}»." if (ia is not None and ib is not None and ib < ia) else f"Pasa a «{a}»."
    return f"{frase} {nota.strip()}" if nota and nota.strip() else frase


# ---------------------------------------------------------------------------
# Adjuntos (el diseno de la muestra)
# ---------------------------------------------------------------------------

# Que es cada fichero adjunto: una version del diseno (se numeran por orden
# de subida), el diseno final, u otra cosa (foto, referencia...).
CLASES_ADJUNTO: tuple[tuple[str, str], ...] = (("version", "Versión"), ("final", "Diseño final"),
                                              ("otro", "Otro"))
CLASES_ADJUNTO_LABEL = dict(CLASES_ADJUNTO)


def _validar_clase_adjunto(v) -> tuple[str, str]:
    """Slug o etiqueta; vacio o el antiguo 'diseno' = version."""
    if v is None:
        return "version", ""
    if not isinstance(v, str):
        return "", "clase debe ser texto"
    v = v.strip()
    if not v or v.lower() == "diseno":
        return "version", ""
    for slug, label in CLASES_ADJUNTO:
        if v.lower() == slug or _clave(v) == _clave(label):
            return slug, ""
    return "", f"clase no valida: {v!r} (version, final, otro)"


def _adjunto_publico(a: dict) -> dict:
    """Metadatos del adjunto para la UI (sin nada del disco)."""
    ext = a.get("ext") or ""
    clase, _ = _validar_clase_adjunto(a.get("clase"))
    clase = clase or "otro"
    return {"id": a.get("id"), "nombre": a.get("nombre"), "ext": ext,
            "tamano": a.get("tamano"), "fecha": a.get("fecha"),
            "clase": clase, "clase_label": CLASES_ADJUNTO_LABEL.get(clase, clase),
            "usuario": a.get("usuario"), "usuario_nombre": a.get("usuario_nombre"),
            "inline": ext in ADJUNTO_INLINE,
            "imagen": ADJUNTO_INLINE.get(ext, "").startswith("image/")}


def _adjuntos_publicos(lista) -> list[dict]:
    """Lista para la UI; las versiones se numeran por orden de subida."""
    out, n = [], 0
    for a in lista or []:
        pub = _adjunto_publico(a)
        if pub["clase"] == "version":
            n += 1
            pub["version_n"] = n
            pub["clase_label"] = f"Versión {n}"
        out.append(pub)
    return out


def _carpeta_adjuntos(mid: str) -> Path:
    return ADJUNTOS_DIR / re.sub(r"[^A-Za-z0-9_-]", "_", str(mid))


def _nombre_adjunto(nombre) -> tuple[str, str, str]:
    """(nombre limpio para ensenar, extension, error)."""
    nombre = (nombre or "").strip().replace("\\", "/").split("/")[-1]
    nombre = re.sub(r"[\x00-\x1f]", "", nombre).strip()[:150]
    if "." not in nombre or nombre.startswith("."):
        return "", "", "el fichero no tiene extension"
    ext = nombre.rsplit(".", 1)[1].lower()
    if ext not in ADJUNTO_EXTENSIONES:
        return "", "", f"tipo de fichero no admitido (.{ext}); vale imagen, PDF, AI/EPS/PSD o ZIP"
    return nombre, ext, ""


def guardar_adjunto(mid: str, nombre, contenido: bytes, usuario: str | None = None,
                    clase: str = "diseno") -> tuple[dict | None, str]:
    """Guarda un fichero adjunto (por defecto el diseno) y lo registra en la
    muestra. El fichero se escribe en ADJUNTOS_DIR/<mid>/<id>.<ext>."""
    nombre, ext, err = _nombre_adjunto(nombre)
    if err:
        return None, err
    if not contenido:
        return None, "el fichero esta vacio"
    if len(contenido) > ADJUNTO_MAX_BYTES:
        return None, f"el fichero pasa de {ADJUNTO_MAX_BYTES // (1024 * 1024)} MB"
    clase, err = _validar_clase_adjunto(clase)
    if err:
        return None, err
    with jsonstore.store().tx():
        data = cargar()
        m = _buscar(data, mid)
        if not m:
            return None, f"la muestra {mid!r} no existe"
        lista = m.setdefault("adjuntos", [])
        aid = _nuevo_id_apunte()
        while any(a.get("id") == aid for a in lista):
            aid = _nuevo_id_apunte()
        carpeta = _carpeta_adjuntos(mid)
        carpeta.mkdir(parents=True, exist_ok=True)
        (carpeta / f"{aid}.{ext}").write_bytes(contenido)
        lista.append({"id": aid, "nombre": nombre, "ext": ext, "tamano": len(contenido),
                      "clase": clase, "fecha": _ahora(),
                      "usuario": _actor_username(usuario), "usuario_nombre": _actor_nombre(usuario)})
        _historial(m, usuario, "adjunto", a="anadido", nombre=nombre, clase=clase)
        m["actualizado_en"] = _ahora()
        _guardar(data)
        return obtener(mid), ""


def ruta_adjunto(mid: str, aid: str) -> tuple[Path | None, dict | None, str]:
    """(ruta en disco, metadatos, error) de un adjunto."""
    m = _buscar(cargar(), mid)
    if not m:
        return None, None, f"la muestra {mid!r} no existe"
    a = next((x for x in (m.get("adjuntos") or []) if x.get("id") == aid), None)
    if not a:
        return None, None, "el adjunto no existe"
    ruta = _carpeta_adjuntos(mid) / f"{a['id']}.{a.get('ext') or ''}"
    if not ruta.is_file():
        return None, a, "el fichero del adjunto no esta en el servidor"
    return ruta, a, ""


def etiquetar_adjunto(mid: str, aid: str, clase, usuario: str | None = None) -> tuple[dict | None, str]:
    """Cambia que es el fichero (version / diseno final / otro)."""
    clase, err = _validar_clase_adjunto(clase)
    if err:
        return None, err
    with jsonstore.store().tx():
        data = cargar()
        m = _buscar(data, mid)
        if not m:
            return None, f"la muestra {mid!r} no existe"
        a = next((x for x in (m.get("adjuntos") or []) if x.get("id") == aid), None)
        if not a:
            return None, "el adjunto no existe"
        anterior, _ = _validar_clase_adjunto(a.get("clase"))
        if anterior != clase:
            a["clase"] = clase
            _historial(m, usuario, "adjunto", a="etiqueta", nombre=a.get("nombre") or "",
                       clase=clase, de=anterior)
            m["actualizado_en"] = _ahora()
            _guardar(data)
        return obtener(mid), ""


def borrar_adjunto(mid: str, aid: str, usuario: str | None = None) -> tuple[dict | None, str]:
    with jsonstore.store().tx():
        data = cargar()
        m = _buscar(data, mid)
        if not m:
            return None, f"la muestra {mid!r} no existe"
        lista = m.get("adjuntos") or []
        a = next((x for x in lista if x.get("id") == aid), None)
        if not a:
            return None, "el adjunto no existe"
        lista.remove(a)
        try:
            (_carpeta_adjuntos(mid) / f"{a['id']}.{a.get('ext') or ''}").unlink()
        except FileNotFoundError:
            pass
        _historial(m, usuario, "adjunto", a="borrado", nombre=a.get("nombre") or "",
                   clase=a.get("clase") or "diseno")
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
             "usuario": _actor_username(usuario), "usuario_nombre": _actor_nombre(usuario)})
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
        ap["editado_por"] = _actor_username(usuario)
        ap["editado_por_nombre"] = _actor_nombre(usuario)
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
    if tipo != "telares":
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
# Avisos por correo (muestras_avisos.py): rastro en el historial, hitos
# pendientes de avisar y snapshot del directorio de usuarios de One (el job
# de hitos corre sin sesion y necesita los e-mails).
# ---------------------------------------------------------------------------

def registrar_aviso(mid: str, motivo: str, destinatario: str, ok: bool,
                    detalle: str = "", asunto: str = "") -> None:
    with jsonstore.store().tx():
        data = cargar()
        m = _buscar(data, mid)
        if not m:
            return
        _historial(m, None, "aviso", motivo=motivo, a=destinatario or "", ok=bool(ok),
                   detalle=_recortar(detalle or "", 200), asunto=_recortar(asunto or "", 120))
        _guardar(data)


def hitos_pendientes(hoy: str | None = None) -> list[dict]:
    """Muestras en curso cuyo proximo hito ha llegado (fecha <= hoy) y aun no
    se ha avisado de ESA fecha."""
    hoy = hoy or _hoy()
    return [dict(m) for m in cargar()["muestras"]
            if en_curso(m) and m.get("proximo_hito_fecha")
            and m["proximo_hito_fecha"] <= hoy
            and m.get("hito_avisado") != m["proximo_hito_fecha"]]


def reclamar_hito(mid: str, fecha: str) -> bool:
    """Marca el hito `fecha` como avisado. True si lo reclama esta llamada
    (idempotente entre workers: solo uno envia)."""
    with jsonstore.store().tx():
        data = cargar()
        m = _buscar(data, mid)
        if not m or m.get("proximo_hito_fecha") != fecha or m.get("hito_avisado") == fecha:
            return False
        m["hito_avisado"] = fecha
        _guardar(data)
        return True


def guardar_directorio(usuarios) -> None:
    """Snapshot [{username, nombre, email}] del directorio de cuentas. Solo
    escribe si cambia."""
    if not isinstance(usuarios, list):
        return
    limpio = [{"username": (u.get("username") or "").strip().lower(),
               "nombre": (u.get("nombre") or "").strip(),
               "email": (u.get("email") or "").strip().lower()}
              for u in usuarios if isinstance(u, dict) and u.get("username")]
    with jsonstore.store().tx():
        data = cargar()
        actual = data["_meta"].get("directorio_one") or {}
        if actual.get("usuarios") == limpio:
            return
        data["_meta"]["directorio_one"] = {"en": _ahora(), "usuarios": limpio}
        _guardar(data)


def directorio_guardado() -> list[dict]:
    return list((cargar()["_meta"].get("directorio_one") or {}).get("usuarios") or [])


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
