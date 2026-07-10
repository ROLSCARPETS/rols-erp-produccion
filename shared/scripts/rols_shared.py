"""
Helpers compartidos de Rols One.

Punto único para que cualquier app de la suite (calculadora, consulta-stock,
asistente, pedidos, futuras rols-X) reutilice los recursos comunes que viven
en `shared/` SIN duplicarlos en su propia carpeta.

Uso típico en el `app.py` de cada app, justo después de crear el Flask app:

    import rols_shared
    rols_shared.register_shared(app)

Eso monta la ruta `/shared/<path>` que sirve `shared/static/` (sso-guard.js,
lang-switcher/, chatbot/, rols-tokens.css, ...). Así una sola copia física
alimenta a todas las apps: si mejoras el chatbot en `shared/static/`, todas
lo recogen al instante. No más copias desincronizadas por app.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from urllib.parse import unquote
from flask import jsonify, send_from_directory

# .../shared  (este archivo vive en shared/scripts/rols_shared.py)
SHARED_DIR = Path(__file__).resolve().parent.parent
SHARED_SCRIPTS = SHARED_DIR / "scripts"
SHARED_STATIC = SHARED_DIR / "static"
SHARED_DATA = SHARED_DIR / "data"

# ---------------------------------------------------------------------------
# Enlaces cruzados entre apps (dev vs producción)
# ---------------------------------------------------------------------------
# En LOCAL cada app corre en su puerto (lanzador iniciar_rols_one.py); los
# enlaces a otra app van a http://localhost:505x. En PRODUCCIÓN las cuatro se
# sirven COMPUESTAS bajo un único dominio (compositor passenger_wsgi.py), cada
# una en su sub-ruta; los enlaces van a /stock, /asistente, /pedidos (calc = raíz).
# El compositor fija ROLS_COMPOSED=1 para activar el modo producción.
_DEV_BASES = {
    "calc": "http://localhost:5051",
    "stock": "http://localhost:5050",
    "cuentas": "http://localhost:5054",
    "asistente": "http://localhost:5052",
    "pedidos": "http://localhost:5053",
}
_PROD_BASES = {
    "calc": "",            # app raíz
    "stock": "/stock",
    "cuentas": "/cuentas",   # identidad / SSO
    "asistente": "/asistente",
    "pedidos": "/pedidos",
}


def decode_path_info(wsgi_app):
    """Middleware WSGI que DECODIFICA el PATH_INFO si llega aún percent-encoded.

    Contexto: el dev server de werkzeug (local) entrega el PATH_INFO ya
    decodificado ('ANNABELLE NX CHARCOAL'), pero Passenger/Apache (producción)
    lo pasa tal cual viene en la URL ('ANNABELLE%20NX%20CHARCOAL'). Werkzeug
    asume — por WSGI/PEP-3333 — que el servidor ya lo decodificó y NO lo vuelve
    a decodificar, así que en prod toda ruta con espacios o caracteres en el
    path falla: la ref/id llega con %XX y no se encuentra. Afecta a
    /producto/<ref>, /materia-prima/<id>, /condiciones/<nombre>, etc.

    Este middleware normaliza el PATH_INFO una sola vez en el borde WSGI, de
    forma IDEMPOTENTE: si ya viene decodificado (sin '%') no toca nada. Envolver
    con él la app/compositor como capa MÁS EXTERNA (antes de enrutar): los
    prefijos del DispatcherMiddleware son ASCII, así que decodificar primero no
    altera el enrutado por sub-ruta.
    """
    def _app(environ, start_response):
        path = environ.get("PATH_INFO", "")
        if "%" in path:
            environ["PATH_INFO"] = unquote(path)
        return wsgi_app(environ, start_response)

    return _app


def nav_bases() -> dict:
    """Bases de URL de cada app de la suite, según dev (puertos) o prod (sub-rutas)."""
    if os.environ.get("ROLS_COMPOSED"):
        return dict(_PROD_BASES)
    return dict(_DEV_BASES)


def register_nav(app):
    """Inyecta `nav` (dict de bases por app) en el contexto de todas las plantillas.

    Las plantillas enlazan así, válido en dev y en prod:
        <a href="{{ nav.calc }}/inicio">Inicio</a>
        <a href="{{ nav.stock }}/">Consulta de stock</a>
        <a href="{{ nav.pedidos }}/">Pedidos</a>
    """
    @app.context_processor
    def _inject_nav():  # noqa: ANN202
        return {"nav": nav_bases()}

    return app


def ensure_shared_on_path():
    """Garantiza que shared/scripts está en sys.path (idempotente).

    Permite `import permisos`, `import lanas_inventario`, etc. desde cualquier
    app sin repetir el sys.path.insert. Llamarlo es seguro tantas veces como
    haga falta: si el path ya está, no hace nada.
    """
    p = str(SHARED_SCRIPTS)
    if p not in sys.path:
        sys.path.insert(0, p)


def register_shared(app, url_prefix: str = "/shared"):
    """Registra en `app` la ruta que sirve los assets comunes de shared/static/.

    Args:
        app: instancia Flask.
        url_prefix: prefijo de la URL (por defecto "/shared").

    Tras llamarlo, las plantillas pueden cargar p.ej.:
        <script src="/shared/sso-guard.js"></script>
        <link rel="stylesheet" href="/shared/lang-switcher/lang-switcher.css">
        <script src="/shared/chatbot/chatbot.js"></script>
    """
    static_dir = str(SHARED_STATIC)

    @app.route(f"{url_prefix}/<path:filename>", endpoint="rols_shared_static")
    def _rols_shared_static(filename):
        return send_from_directory(static_dir, filename)

    # Inyectar también `nav` (enlaces cruzados dev/prod) en todas las plantillas.
    register_nav(app)

    return app
