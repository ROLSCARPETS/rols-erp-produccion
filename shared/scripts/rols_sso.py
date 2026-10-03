"""Login común de las apps satélite de Rols One (03-10-2026).

ORIGINAL: rols-one/shared/kit/rols_sso.py. Cada satélite lleva una COPIA
idéntica junto a su sso.py (scripts/rols_sso.py; en Producción,
shared/scripts/rols_sso.py), que se reparte con shared/kit/repartir.py; una
prueba de cada app avisa si su copia se queda atrás. No se edita en las copias.

Antes había seis copias de este código, cada una con un arreglo distinto: a
quien se daba de baja en Rols One, unas lo dejaban seguir entrando un mes y
otras no; unas subían a alguien al nivel que tenía en One si Cuentas no
contestaba; unas abrían la app sin login en producción con un ROLS_NO_AUTH
olvidado en el .env. Aquí está la mejor versión de cada pieza, una sola vez.

Cómo se usa: NO se importa, se carga dentro del sso.py de cada app:

    APP_KEY = "numbers"              # la app en Cuentas (accesos/apps)
    NOMBRE_APP = "Rols Numbers"      # para los mensajes
    NOMBRE_CORTO = "Numbers"
    ... (lo opcional, abajo)
    _KIT = Path(__file__).with_name("rols_sso.py")
    exec(compile(_KIT.read_text(encoding="utf-8"), str(_KIT), "exec"), globals())
    ... (y debajo, lo propio de la app)

Así todo vive en el módulo `sso` de la app, lo común y lo suyo, y lo que la app
o sus pruebas cambien (sso._no_auth, sso.current_user, sso.nivel_usuario...) es
lo que usa lo común. Una app que necesita algo distinto lo redefine DEBAJO de
la carga, con el mismo nombre (p. ej. Seguimiento, `current_user`, para los
operarios de la tablet).

Opcional, antes de cargarlo:
    VISTAS_POR_NIVEL   {nivel: [secciones]} de la app
    VISTAS_SIN_NIVEL   lo que ve quien no tiene nivel (por defecto, nada)
    SIN_NIVEL_NO_ENTRA True (por defecto): sin nivel en la app no se entra.
                       False: se entra si Cuentas da la app, y el nivel que no
                       se sepa es el más bajo (las de fábrica, que no pueden
                       pararse por un corte de Cuentas).
    LEE_LA_COOKIE      True (por defecto): quién es la persona lo dice la cookie
                       firmada (la app tiene ASISTENTE_SECRET_KEY). False: lo
                       dice Cuentas (Producción, que no tiene el secreto).

Lo que hace:
- La cookie de la suite (rols_one_session, dominio .rolscarpets.com, firmada
  con ASISTENTE_SECRET_KEY): `configurar_sesion(app)` y `current_user()`.
- El nivel EN ESTA APP sale de Cuentas (/api/whoami, caché de 60 s). Un 401/403
  de Cuentas es un «no» (`DENEGADO`), no una caída. Si Cuentas no contesta, el
  último nivel que confirmó en este proceso y, si no, el que firmó en la cookie
  (`accesos`); nunca el rol de One, que puede ser mayor que el de aquí.
- Las apps que van por PERMISOS de la matriz de Rols One y no por nivel
  (Pedidos, Producción): `puede(permiso)`, y `usuario_cuentas()` con el whoami
  entero. Si Cuentas no contesta, lo último que confirmó de esa sesión.
- `login_required`: sin sesión, al login de Cuentas (401 en la API); sin acceso,
  403 con la página sin_acceso.html de la app. `requiere_vista` por secciones.
- Sin login (usuario admin de pruebas) solo en local: pedido con ROLS_NO_AUTH o
  sirviendo en localhost. Nunca en producción.
- `servicio_de_one(request)`: lo que One pide de servidor a servidor, firmado.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import time
import urllib.error
import urllib.request
from functools import wraps
from urllib.parse import quote

from flask import jsonify, redirect, render_template, request, session

# Lo que pone la app antes de cargar esto (y lo opcional, con su defecto).
APP_KEY = globals().get("APP_KEY") or ""
NOMBRE_APP = globals().get("NOMBRE_APP") or f"Rols {APP_KEY.capitalize()}"
NOMBRE_CORTO = globals().get("NOMBRE_CORTO") or APP_KEY.capitalize()
VISTAS_POR_NIVEL = globals().get("VISTAS_POR_NIVEL") or {}
VISTAS_SIN_NIVEL = list(globals().get("VISTAS_SIN_NIVEL") or [])
SIN_NIVEL_NO_ENTRA = globals().get("SIN_NIVEL_NO_ENTRA", True)
LEE_LA_COOKIE = globals().get("LEE_LA_COOKIE", True)

# Los tres niveles de la suite (permisos.ROLES de rols-one manda: de ellos
# dependen la BD de Cuentas y el ERP). Lo que lee la persona son las etiquetas.
NIVELES = ("admin", "comercial", "representante")
_NIVELES = NIVELES
NIVELES_LABEL = {"admin": "Completo", "comercial": "Estándar", "representante": "Limitado"}
# Quien no tiene nivel en la app. Es un valor de verdad, no un «por defecto».
SIN_NIVEL = ""


# ---------------------------------------------------------------------------
# Dónde está la suite y si esto es producción
# ---------------------------------------------------------------------------
def _es_prod() -> bool:
    # passenger_wsgi.py de cada app pone ROLS_COMPOSED; Passenger, PASSENGER_APP_ENV.
    return bool(os.getenv("ROLS_COMPOSED") or os.getenv("PASSENGER_APP_ENV"))


def _no_auth() -> bool:
    """¿Modo sin login (usuario admin de pruebas)?

    Nunca en producción: un ROLS_NO_AUTH=1 olvidado en el .env del servidor
    abría la app entera a cualquiera como admin. Fuera de producción, si se
    pide por entorno; y si no, solo sirviendo en localhost. Arrancar la app de
    otra forma la deja cerrada: para fallar, mejor fallar cerrado."""
    if _es_prod():
        return False
    explicito = os.getenv("ROLS_NO_AUTH")
    if explicito is not None:
        return explicito.strip().lower() in ("1", "true", "yes")
    return _sirve_en_local()


def _sirve_en_local() -> bool:
    """¿Llega la petición de ahora a localhost? Fuera de una petición, no."""
    from flask import has_request_context
    if not has_request_context():
        return False
    host = (request.host or "").lower()
    host = host[1:].split("]")[0] if host.startswith("[") else host.split(":")[0]
    return host in ("localhost", "127.0.0.1", "::1")


def cuentas_base() -> str:
    """URL base del identity provider (rols-cuentas)."""
    return os.getenv("ROLS_CUENTAS_URL", "https://one.rolscarpets.com/cuentas").rstrip("/")


def rols_one_base() -> str:
    """URL base de Rols One (la suite va montada en la raíz)."""
    return os.getenv("ROLS_ONE_URL", "https://one.rolscarpets.com").rstrip("/")


def cookie_name() -> str:
    """Nombre de la cookie de sesión de la suite (la MISMA que Rols One)."""
    return os.getenv("ASISTENTE_COOKIE_NAME", "rols_one_session")


# ---------------------------------------------------------------------------
# La cookie de la suite
# ---------------------------------------------------------------------------
def configurar_sesion(app) -> None:
    """Configura la cookie de sesión para que sea LA MISMA que la de la suite:
    mismo secreto, mismo nombre, mismo dominio. Así se lee aquí sin preguntar
    a nadie quién es la persona."""
    secret = os.getenv("ASISTENTE_SECRET_KEY")
    if not secret:
        # Sin el secreto de la suite no se puede leer la sesión real. En local
        # da igual (sin login); en producción, cada worker de Passenger firmaría
        # con una clave distinta y el login fallaría a ratos: se avisa a gritos.
        if _es_prod():
            logging.getLogger(f"rols_{APP_KEY}").error(
                "ASISTENTE_SECRET_KEY no está definida en producción: el SSO fallará "
                "de forma intermitente (cada worker firma con una clave distinta). "
                "Define ASISTENTE_SECRET_KEY en el .env.")
        import secrets as _s
        secret = _s.token_hex(32)
    app.secret_key = secret
    app.config["SESSION_COOKIE_NAME"] = cookie_name()
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    # Lax basta para el SSO (los subdominios de rolscarpets.com son el MISMO
    # sitio) y evita que la cookie viaje en peticiones de otras webs (CSRF).
    app.config["SESSION_COOKIE_SAMESITE"] = os.getenv("ASISTENTE_COOKIE_SAMESITE", "Lax")
    app.config["SESSION_COOKIE_SECURE"] = True
    dominio = os.getenv("ASISTENTE_COOKIE_DOMAIN") or (".rolscarpets.com" if _es_prod() else None)
    if dominio:
        app.config["SESSION_COOKIE_DOMAIN"] = dominio


def current_user() -> dict | None:
    """Usuario de la cookie de sesión de la suite (o el admin de pruebas en
    local). Dice QUIÉN es; lo que puede hacer aquí lo dice Cuentas. En una app
    sin el secreto de la suite (LEE_LA_COOKIE = False), quién es también lo
    dice Cuentas (`usuario_cuentas`)."""
    if LEE_LA_COOKIE:
        datos = session if "user_id" in session else None
        uid = session.get("user_id") if datos is not None else None
    else:
        datos = None if _no_auth() else usuario_cuentas()
        uid = datos.get("id") if datos else None
    if not datos:
        return ({"id": 0, "username": "dev", "nombre": "Desarrollo (local)",
                 "rol": "admin", "idioma": "es"} if _no_auth() else None)
    return {
        "id": uid,
        "username": datos.get("username"),
        "nombre": datos.get("nombre") or datos.get("username"),
        "rol": datos.get("rol") or "comercial",
        "idioma": datos.get("idioma") or "es",
    }


def cookie_sesion() -> str | None:
    """La cookie de sesión de la petición actual, para llamar a otras apps de
    la suite en nombre de la persona, o None (también fuera de una petición)."""
    try:
        return request.cookies.get(cookie_name()) or None
    except RuntimeError:
        return None


# ---------------------------------------------------------------------------
# Lo que dice Cuentas de esta persona (/api/whoami)
# ---------------------------------------------------------------------------
_CACHE_TTL = 60.0   # un cambio de acceso o de nivel se nota en menos de un minuto
_cache_whoami: dict[str, tuple[float, "dict | None"]] = {}

# Lo último que Cuentas confirmó de cada sesión: el nivel en esta app y el
# whoami entero (quién es y sus permisos). SOLO para cuando Cuentas no
# contesta: se mantiene lo que esa persona tenía, en vez de deducirlo de otra
# cosa. En memoria y por proceso a propósito: es un apaño para un rato de
# caída, no una copia de los permisos (que viven en Cuentas y solo ahí).
_ultimo_nivel: dict[str, str] = {}
_ultimo_who: dict[str, dict] = {}

# Lo que devuelve `_whoami_remoto` cuando Cuentas CONTESTA que esa sesión no
# vale (401/403): la persona se ha borrado o desactivado en Rols One. Es una
# respuesta, no una caída, así que no abre el paracaídas de la cookie.
DENEGADO = {"_denegado": True}

# La forma de una cookie de sesión de Flask (firmada, con o sin comprimir):
# payload.fecha.firma, en base64 url-safe. Una app que no lee la cookie no sabe
# si es buena sin preguntar; lo que no tenga esta forma no lo es, y se descarta
# sin llamar a Cuentas (así una lluvia de cookies basura no se convierte en una
# lluvia de llamadas a whoami). Las que la leen no lo necesitan: sin una sesión
# firmada no se llega a preguntar.
_FORMATO_COOKIE_SESION = re.compile(r"\.?[A-Za-z0-9_\-]+(?:\.[A-Za-z0-9_\-]+){2}")


def _whoami_remoto(cookie_valor: str) -> dict | None:
    """GET al /api/whoami de Cuentas con la cookie de la persona. None si no
    contesta (red, Cuentas caído, un 5xx, algo que no es un whoami...) y
    `DENEGADO` si contesta que no."""
    req = urllib.request.Request(
        cuentas_base() + "/api/whoami",
        headers={"Cookie": f"{cookie_name()}={cookie_valor}",
                 "User-Agent": f"rols-{APP_KEY}/sso"},
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            datos = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return DENEGADO if e.code in (401, 403) else None
    except Exception:
        return None
    return datos if isinstance(datos, dict) else None


def _clave_sesion() -> str:
    """La sesión sin guardar la cookie: su hash recortado. La usan la caché de
    whoami y la del último nivel confirmado."""
    try:
        valor = request.cookies.get(cookie_name())
    except RuntimeError:
        return ""
    return hashlib.sha256(valor.encode()).hexdigest()[:16] if valor else ""


def _whoami_cacheado() -> dict | None:
    """whoami de la persona de esta petición (cacheado por cookie, 60 s). None
    en modo local, sin cookie o si Cuentas no contesta; `DENEGADO` si dice que
    no."""
    if _no_auth():
        return None
    valor = request.cookies.get(cookie_name())
    if not valor:
        return None
    if not LEE_LA_COOKIE and (len(valor) > 4096 or not _FORMATO_COOKIE_SESION.fullmatch(valor)):
        return None
    clave = _clave_sesion()
    ahora = time.time()
    hit = _cache_whoami.get(clave)
    if hit and ahora - hit[0] < _CACHE_TTL:
        return hit[1]
    who = _whoami_remoto(valor)
    if len(_cache_whoami) > 500:   # tope defensivo (una entrada por sesión viva)
        _cache_whoami.clear()
    _cache_whoami[clave] = (ahora, who)
    _recordar(clave, who)
    return who


def _recordar(clave: str, who: dict | None) -> None:
    """Cada respuesta NUEVA de Cuentas pone al día lo último confirmado,
    también cuando dice que no: si no, a quien le quitan la app le quedaba lo
    de antes guardado, y en la próxima caída de Cuentas volvía a entrar con
    ello (03-10-2026, al juntar las copias). Sin respuesta, no se toca."""
    if not clave or who is None:
        return
    if who.get("_denegado"):
        _ultimo_who.pop(clave, None)
    else:
        if len(_ultimo_who) > 500:   # tope defensivo, como el de la caché
            _ultimo_who.clear()
        _ultimo_who[clave] = who
    niv = _nivel_de(who.get("accesos")) if _evaluar_acceso(who) else SIN_NIVEL
    if niv:
        _ultimo_nivel[clave] = niv
    else:
        _ultimo_nivel.pop(clave, None)


def usuario_cuentas() -> dict | None:
    """Lo que Cuentas dice de la persona de esta petición: su whoami (quién es,
    su nivel en cada app, sus permisos). Si ahora no contesta, lo último que
    confirmó de esta sesión en este proceso. None sin sesión, si nunca lo
    confirmó o si dice que no. En local (sin login), None: el usuario de
    pruebas no pasa por Cuentas."""
    if _no_auth():
        return None
    who = _whoami_cacheado()
    if who is None:
        return _ultimo_who.get(_clave_sesion())
    return None if who.get("_denegado") else who


def puede(permiso: str) -> bool:
    """¿Le da Cuentas a la persona de esta petición este permiso de la matriz
    de Rols One? Para las apps que van por permisos y no por nivel. Si Cuentas
    no contesta, lo último que confirmó; si nunca lo hizo, no: aquí no hay
    paracaídas en la cookie, porque los permisos salen de una matriz que solo
    tiene Cuentas. En local (sin login), sí."""
    if _no_auth():
        return True
    return bool(((usuario_cuentas() or {}).get("permisos") or {}).get(permiso))


def _evaluar_acceso(whoami: dict | None) -> bool:
    """¿Dice Cuentas que esta persona tiene esta app?

    Cuando Cuentas contesta, manda Cuentas: `apps` trae TODAS las apps de la
    suite (permisos.apps_por_accesos), así que una que no está o está a False
    es que no se le ha dado. Un «no» de Cuentas (`DENEGADO`), tampoco.

    Lo que no es una respuesta no decide aquí: sin whoami (Cuentas caído) o con
    `apps` vacío (Cuentas arrancado a medias). Ahí decide el nivel, con el
    paracaídas de la cookie firmada."""
    if not whoami:
        return True
    if whoami.get("_denegado"):
        return False
    apps = whoami.get("apps")
    if not isinstance(apps, dict) or not apps:
        return True
    return bool(apps.get(APP_KEY))


# ---------------------------------------------------------------------------
# El nivel en esta app
# ---------------------------------------------------------------------------
def _nivel_de(accesos) -> str:
    """El nivel de esta app dentro de un dict de accesos {app: nivel}, o
    SIN_NIVEL si no lo hay o no se reconoce."""
    niv = accesos.get(APP_KEY) if isinstance(accesos, dict) else None
    niv = niv.strip().lower() if isinstance(niv, str) else ""
    return niv if niv in NIVELES else SIN_NIVEL


def _nivel_en_la_cookie() -> str:
    """El nivel que Cuentas firmó dentro de la cookie (`accesos`). Firmado por
    la suite, así que no se puede falsificar, pero solo se refresca cuando la
    persona pasa por Rols One: es el paracaídas, no la fuente."""
    try:
        return _nivel_de(session.get("accesos"))
    except Exception:      # fuera de una petición
        return SIN_NIVEL


_nivel_firmado = _nivel_en_la_cookie


def _nivel_minimo() -> str:
    """El nivel de quien no tiene ninguno: ninguno (y no entra), o el más bajo
    en las apps que no pueden pararse (SIN_NIVEL_NO_ENTRA = False)."""
    return SIN_NIVEL if SIN_NIVEL_NO_ENTRA else "representante"


def _nivel_resuelto() -> str:
    """El nivel EN ESTA APP, por este orden:
      1. lo que dice Cuentas ahora (whoami, cacheado 60 s);
      2. si no contesta, el último que confirmó en este proceso;
      3. si tampoco, el que firmó en la cookie (sobrevive a un reinicio del
         servidor, que es justo cuando se pierde el 2);
      4. si nada, `_nivel_minimo()`.
    Nunca el rol de One que también lleva la cookie: es el nivel en la app
    «one», que puede ser MAYOR que el de aquí, y una caída ascendía a admin a
    quien aquí solo tenía Limitado. En local (sin login), admin."""
    if _no_auth():
        return "admin"
    who = _whoami_cacheado()      # y de paso pone al día lo último confirmado
    if who is not None:
        return _nivel_de(who.get("accesos")) or _nivel_minimo()
    return _ultimo_nivel.get(_clave_sesion()) or _nivel_en_la_cookie() or _nivel_minimo()


def nivel_app() -> str:
    """El nivel en esta app. Una app que lo llama de otra forma (nivel_usuario,
    nivel_muestras) redefine esta función para que apunte a la suya: así lo
    común usa lo mismo que sus pruebas sustituyan."""
    return _nivel_resuelto()


def tiene_acceso() -> bool:
    """¿Puede entrar a la app la persona de esta petición? Que Cuentas le dé la
    app y, salvo en las de fábrica, que tenga un nivel en ella."""
    if _no_auth():
        return True
    if not cookie_sesion():
        return True  # sin cookie no hay sesión: login_required ya manda al login
    if not _evaluar_acceso(_whoami_cacheado()):
        return False
    return not SIN_NIVEL_NO_ENTRA or nivel_app() != SIN_NIVEL


def nombre_actual() -> str:
    """El nombre de la persona, LO MÁS FRESCO posible: el de Cuentas (su base de
    datos), no el de la cookie, que solo se refresca al pasar por Rols One. Lo
    que se guarda con su nombre se queda así para siempre. Si Cuentas no
    contesta, el de la cookie."""
    who = _whoami_cacheado()
    if isinstance(who, dict):
        fresco = str(who.get("nombre") or "").strip()
        if fresco:
            return fresco
    u = current_user() or {}
    return str(u.get("nombre") or u.get("username") or "").strip()


def etiqueta_nivel(nivel: str = "") -> str:
    """El nombre del nivel tal como se lee en Rols One."""
    return NIVELES_LABEL.get(nivel or nivel_app(), "sin nivel")


# ---------------------------------------------------------------------------
# Secciones por nivel
# ---------------------------------------------------------------------------
def vistas_permitidas() -> list[str]:
    """Secciones que ve la persona de esta petición."""
    return list(VISTAS_POR_NIVEL.get(nivel_app(), VISTAS_SIN_NIVEL))


def puede_ver(vista: str) -> bool:
    return vista in vistas_permitidas()


def es_admin() -> bool:
    """Quien ve Configuración."""
    return puede_ver("config")


# ---------------------------------------------------------------------------
# Las puertas
# ---------------------------------------------------------------------------
def sin_acceso(codigo: str = "sin_acceso", detalle_api: str = "",
               titulo: str | None = None, detalle: str | None = None):
    """La respuesta 403: JSON en la API, la página sin_acceso.html de la app en
    las pantallas (con las URLs de Cuentas y de One, para sus botones)."""
    if (request.path or "").startswith("/api/"):
        cuerpo = {"error": codigo}
        if detalle_api:
            cuerpo["detalle"] = detalle_api
        return jsonify(cuerpo), 403
    return render_template("sin_acceso.html", usuario=current_user(), titulo=titulo,
                           detalle=detalle, cuentas_url=cuentas_base(),
                           one_url=rols_one_base()), 403


def login_required(fn):
    """Sin sesión, al login de Cuentas (401 en la API); sin acceso a la app, 403."""
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if current_user() is None:
            if (request.path or "").startswith("/api/"):
                return jsonify({"error": "auth_required"}), 401
            return redirect(f"{cuentas_base()}/login?next={quote(request.url, safe='')}")
        if not tiene_acceso():
            return sin_acceso(detalle_api=f"Tu usuario no tiene acceso a {NOMBRE_APP}; "
                                          "pídeselo a un administrador en Rols One.")
        return fn(*args, **kwargs)
    return wrapper


def requiere_alguna_vista(*vistas: str):
    """Para lo de una sección: 403 si el nivel no incluye NINGUNA de `vistas`
    (defensa en el servidor, además de no pintarla). Va bajo `login_required`."""
    permitidas = tuple(vistas)

    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            if not any(puede_ver(v) for v in permitidas):
                etiqueta = "» o «".join(permitidas)
                detalle = (f"tu nivel en {NOMBRE_CORTO} ({etiqueta_nivel()}) no "
                           f"incluye la sección «{etiqueta}».")
                return sin_acceso("sin_acceso_seccion", "T" + detalle[1:],
                                  titulo="Esta sección no es de tu nivel", detalle=detalle)
            return fn(*args, **kwargs)
        return wrapper
    return deco


def requiere_vista(vista: str):
    return requiere_alguna_vista(vista)


# ---------------------------------------------------------------------------
# Lo que One pide de servidor a servidor, sin sesión de usuario
# ---------------------------------------------------------------------------
# Firmado por One (sesion_sso.firmar_servicio en rols-one) con el secreto de la
# suite, otra sal y dos minutos de vida: no hace falta otro secreto en ningún
# .env. La misma sal y la misma caducidad en los dos lados.
SAL_SERVICIO = "rols-servicio"
CADUCIDAD_SERVICIO_S = 120


def servicio_de_one(req) -> bool:
    """¿La petición la firma Rols One, para esta app? (cabecera X-Rols-Servicio)"""
    token = (req.headers.get("X-Rols-Servicio") or "").strip()
    secreto = os.getenv("ASISTENTE_SECRET_KEY")
    if not token or not secreto:
        return False
    from itsdangerous import URLSafeTimedSerializer
    try:
        datos = URLSafeTimedSerializer(secreto, salt=SAL_SERVICIO).loads(
            token, max_age=CADUCIDAD_SERVICIO_S)
    except Exception:
        return False
    return isinstance(datos, dict) and datos.get("de") == "one" and datos.get("para") == APP_KEY
