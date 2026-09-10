"""Envio de correo del ERP de Produccion (avisos de muestras).

Sin configurar nada en el servidor se intenta, en este orden:
  1. el MTA local de Plesk (127.0.0.1:25, sin credenciales) — lo mismo que hace
     Rols Muestras (muestras.rolscarpets.com) con su avisos_stock.py;
  2. envio directo a Microsoft 365 (el MX de rolscarpets.com, puerto 25 con
     STARTTLS) — vale para buzones DEL DOMINIO, que son los de los avisos, y
     el IP del servidor esta en el SPF del dominio.

Si hay configuracion explicita se usa solo esa (en el .env del servidor,
NUNCA en el repo), con cualquiera de las dos convenciones de la suite:
  Rols One (notificar.py):  ROLS_SMTP_HOST / ROLS_SMTP_PORT / ROLS_SMTP_USER
                            ROLS_SMTP_PASS / ROLS_SMTP_FROM
  Rols Muestras:            SMTP_HOST / SMTP_PORT / SMTP_USER / SMTP_PASS
o un fichero `correo.json` en ROLS_DATA_DIR (host, port, user, pass, from).

Remitente por defecto: "Rols Producción <produccion@rolscarpets.com>"
(ROLS_SMTP_FROM lo cambia). En local (Windows) no hay MTA: sin configuracion
explicita `configurado()` es False y no se intenta nada. `ULTIMO` guarda por
que ruta salio el ultimo envio (lo ensena la pestana Analisis).
"""
from __future__ import annotations

import json
import os
import smtplib
from email.message import EmailMessage
from pathlib import Path

REMITENTE_DEFECTO = "Rols Producción <produccion@rolscarpets.com>"
# MX de rolscarpets.com (Microsoft 365). Override: ROLS_SMTP_DIRECTSEND_HOST.
DIRECTSEND_HOST_DEFECTO = "rolscarpets-com.mail.protection.outlook.com"

ULTIMO: dict = {"via": None, "ok": None, "error": "", "cuando": None}


def _fichero_cfg() -> Path:
    base = os.environ.get("ROLS_DATA_DIR") or str(Path(__file__).resolve().parent.parent / "data")
    return Path(base) / "correo.json"


def _env(*claves) -> str:
    for k in claves:
        v = (os.environ.get(k) or "").strip()
        if v:
            return v
    return ""


def _remitente() -> str:
    return _env("ROLS_SMTP_FROM", "AVISOS_FROM") or REMITENTE_DEFECTO


def _puerto(port, host: str) -> int:
    try:
        return int(port)
    except (TypeError, ValueError):
        return 25 if host in ("localhost", "127.0.0.1") or host.endswith("mail.protection.outlook.com") else 587


def _cfg_explicita() -> dict | None:
    """Ruta configurada a mano (entorno o fichero) o None."""
    host = _env("ROLS_SMTP_HOST")
    if host:
        return {"host": host, "port": _puerto(_env("ROLS_SMTP_PORT"), host),
                "user": _env("ROLS_SMTP_USER"), "password": os.environ.get("ROLS_SMTP_PASS") or "",
                "de": _remitente(), "origen": "entorno (ROLS_SMTP_*)"}
    host = _env("SMTP_HOST")
    if host:
        return {"host": host, "port": _puerto(_env("SMTP_PORT"), host),
                "user": _env("SMTP_USER"), "password": os.environ.get("SMTP_PASS") or "",
                "de": _remitente(), "origen": "entorno (SMTP_*, como Rols Muestras)"}
    f = _fichero_cfg()
    if f.exists():
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
            host = (d.get("host") or "").strip()
            if host:
                return {"host": host, "port": _puerto(d.get("port"), host),
                        "user": (d.get("user") or "").strip(),
                        "password": d.get("pass") or d.get("password") or "",
                        "de": (d.get("from") or "").strip() or _remitente(),
                        "origen": "fichero correo.json"}
        except (OSError, ValueError, AttributeError):
            pass
    return None


def _cfg() -> dict | None:
    """Ruta principal: la explicita, o el MTA local de Plesk (solo POSIX)."""
    c = _cfg_explicita()
    if c:
        return c
    if os.name == "nt":
        return None   # local Windows: sin MTA, no se intenta
    return {"host": "127.0.0.1", "port": 25, "user": "", "password": "",
            "de": _remitente(), "origen": "MTA local de Plesk (127.0.0.1:25)"}


def _rutas() -> list[dict]:
    """Rutas a probar en orden. Con configuracion explicita, solo esa."""
    c = _cfg()
    if not c:
        return []
    rutas = [c]
    if c.get("origen", "").startswith("MTA local"):
        host = _env("ROLS_SMTP_DIRECTSEND_HOST") or DIRECTSEND_HOST_DEFECTO
        rutas.append({"host": host, "port": 25, "user": "", "password": "", "de": c["de"],
                      "origen": f"Microsoft 365 direct send ({host}:25)"})
    return rutas


def configurado() -> bool:
    return bool(_rutas())


def estado() -> dict:
    """Para la UI: rutas disponibles y ultimo envio, sin exponer secretos."""
    rutas = _rutas()
    if not rutas:
        return {"configurado": False, "remitente": None, "host": None, "origen": None,
                "rutas": [], "ultimo": dict(ULTIMO)}
    c = rutas[0]
    return {"configurado": True, "remitente": c["de"], "host": f"{c['host']}:{c['port']}",
            "origen": c["origen"],
            "rutas": [f"{r['origen']}" for r in rutas], "ultimo": dict(ULTIMO)}


def _enviar_por(ruta: dict, msg: EmailMessage) -> None:
    if ruta["port"] == 465:
        with smtplib.SMTP_SSL(ruta["host"], ruta["port"], timeout=25) as s:
            if ruta["user"]:
                s.login(ruta["user"], ruta["password"])
            s.send_message(msg)
        return
    with smtplib.SMTP(ruta["host"], ruta["port"], timeout=25) as s:
        s.ehlo()
        # TLS oportunista (igual que Rols Muestras): si el servidor lo ofrece
        # se usa; obligatorio con Microsoft 365.
        if s.has_extn("starttls"):
            s.starttls()
            s.ehlo()
        if ruta["user"]:
            s.login(ruta["user"], ruta["password"])
        s.send_message(msg)


def enviar(para, asunto: str, texto: str, html: str | None = None,
           responder_a: str | None = None) -> tuple[bool, str]:
    """Envia un correo (sincrono) probando las rutas en orden. Devuelve
    (ok, error); el error junta el fallo de cada ruta. Nunca lanza."""
    from datetime import datetime
    rutas = _rutas()
    if not rutas:
        return False, "correo no configurado"
    if isinstance(para, str):
        para = [para]
    para = [p.strip() for p in (para or []) if p and p.strip()]
    if not para:
        return False, "sin destinatario"
    errores = []
    for ruta in rutas:
        try:
            msg = EmailMessage()
            msg["Subject"] = asunto
            msg["From"] = ruta["de"]
            msg["To"] = ", ".join(para)
            if responder_a:
                msg["Reply-To"] = responder_a
            msg.set_content(texto or "")
            if html:
                msg.add_alternative(html, subtype="html")
            _enviar_por(ruta, msg)
            ULTIMO.update({"via": ruta["origen"], "ok": True, "error": "",
                           "cuando": datetime.now().isoformat(timespec="seconds")})
            return True, ""
        except Exception as e:  # noqa: BLE001 — se prueba la siguiente ruta
            errores.append(f"{ruta['origen']}: {type(e).__name__}: {e}")
    err = " | ".join(errores)
    ULTIMO.update({"via": None, "ok": False, "error": err[:300],
                   "cuando": datetime.now().isoformat(timespec="seconds")})
    return False, err
