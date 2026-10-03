"""SSO de Rols One para el ERP de Producción (produccion.rolscarpets.com).

Lo común a las apps satélite —lo que dice Cuentas, el usuario de pruebas en
local, las URLs de la suite— está en rols_sso.py, COPIA del de
rols-one/shared/kit (no se edita aquí: se reparte desde allí con
shared/kit/repartir.py, y tests/test_rols_sso_al_dia.py avisa si se queda
atrás). Se carga DENTRO de este módulo, así que todo se usa como sso.xxx y lo
que las pruebas cambien es lo que usa lo común.

Este ERP no tiene el secreto de la suite (ASISTENTE_SECRET_KEY), así que no lee
la cookie: le pregunta a Cuentas quién es la persona (whoami, caché de 60 s;
LEE_LA_COOKIE = False). Lo que puede hacer lo deciden los permisos `compras` y
`muestras_fabricadas` de ese whoami (app.py: _puede, _requiere,
_pagina_protegida). Si Cuentas dice que no, no se entra; si no contesta, vale
lo último que confirmó de esa sesión en este proceso, y si nunca lo hizo, no se
entra.

URLs: ROLS_ONE_URL / ROLS_CUENTAS_URL como en el resto de la suite, o las de
siempre aquí (ROLS_ONE_BASE / ROLS_CUENTAS_BASE); sirviendo en localhost, la
suite local; si no, la de producción.

En local (sin login, admin de pruebas): con ROLS_NO_AUTH=1, o sirviendo en
localhost (ROLS_NO_AUTH=0 para probar el login de verdad). Nunca en el
servidor: passenger_wsgi.py pone PASSENGER_APP_ENV.
"""
from __future__ import annotations

import os
from pathlib import Path

APP_KEY = "produccion"
NOMBRE_APP = "Rols Producción"
NOMBRE_CORTO = "Producción"
LEE_LA_COOKIE = False

# Lo común (ver arriba), cargado en este mismo módulo.
_KIT = Path(__file__).with_name("rols_sso.py")
exec(compile(_KIT.read_text(encoding="utf-8"), str(_KIT), "exec"), globals())


def rols_one_base() -> str:
    """URL base de Rols One (el inicio de la suite)."""
    propia = os.getenv("ROLS_ONE_URL") or os.getenv("ROLS_ONE_BASE")
    if propia:
        return propia.rstrip("/")
    return "http://localhost:5051" if _sirve_en_local() else "https://one.rolscarpets.com"  # noqa: F821


def cuentas_base() -> str:
    """URL base del identity provider (rols-cuentas)."""
    propia = os.getenv("ROLS_CUENTAS_URL") or os.getenv("ROLS_CUENTAS_BASE")
    if propia:
        return propia.rstrip("/")
    return "http://localhost:5054" if _sirve_en_local() else rols_one_base() + "/cuentas"  # noqa: F821


def cookie_name() -> str:
    """La cookie de sesión de la suite (la que se reenvía a Cuentas y a One)."""
    return (os.getenv("ASISTENTE_COOKIE_NAME") or os.getenv("ROLS_SESSION_COOKIE")
            or "rols_one_session")
