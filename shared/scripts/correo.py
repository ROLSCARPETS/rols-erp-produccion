"""Envio de correo (SMTP) del ERP de Produccion.

Misma convencion que `notificar.py` de Rols One, para poder copiar la misma
configuracion al .env de este servidor (NUNCA al repo):

  ROLS_SMTP_HOST   servidor SMTP (p.ej. smtp.office365.com)
  ROLS_SMTP_PORT   587 por defecto (STARTTLS); 465 = SSL directo
  ROLS_SMTP_USER   usuario (el buzon que envia)
  ROLS_SMTP_PASS   contrasena (o contrasena de aplicacion)
  ROLS_SMTP_FROM   remitente visible; por defecto "Rols Produccion <usuario>"

Alternativa sin variables de entorno (mismo patron que erp_api_token.txt):
un fichero `correo.json` en ROLS_DATA_DIR con las claves host, port, user,
pass, from.

Sin configuracion, `configurado()` es False y `enviar()` devuelve
(False, "correo no configurado") sin lanzar: los avisos son best-effort.
"""
from __future__ import annotations

import json
import os
import smtplib
from email.message import EmailMessage
from email.utils import formataddr
from pathlib import Path

_REMITENTE_DEFECTO = "Rols Producción"


def _fichero_cfg() -> Path:
    base = os.environ.get("ROLS_DATA_DIR") or str(Path(__file__).resolve().parent.parent / "data")
    return Path(base) / "correo.json"


def _cfg() -> dict | None:
    host = (os.environ.get("ROLS_SMTP_HOST") or "").strip()
    origen = "entorno"
    port = os.environ.get("ROLS_SMTP_PORT")
    user = (os.environ.get("ROLS_SMTP_USER") or "").strip()
    password = os.environ.get("ROLS_SMTP_PASS") or ""
    de = (os.environ.get("ROLS_SMTP_FROM") or "").strip()
    if not host:
        f = _fichero_cfg()
        if not f.exists():
            return None
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        host = (d.get("host") or "").strip()
        if not host:
            return None
        origen = "fichero"
        port = d.get("port")
        user = (d.get("user") or "").strip()
        password = d.get("pass") or d.get("password") or ""
        de = (d.get("from") or "").strip()
    try:
        port_i = int(port or 587)
    except (TypeError, ValueError):
        port_i = 587
    if not de:
        de = formataddr((_REMITENTE_DEFECTO, user)) if user else f"{_REMITENTE_DEFECTO} <produccion@rolscarpets.com>"
    return {"host": host, "port": port_i, "user": user, "password": password,
            "de": de, "origen": origen}


def configurado() -> bool:
    return _cfg() is not None


def estado() -> dict:
    """Para la UI: si hay correo y desde donde sale, sin exponer secretos."""
    cfg = _cfg()
    if not cfg:
        return {"configurado": False, "remitente": None, "host": None, "origen": None}
    return {"configurado": True, "remitente": cfg["de"], "host": f"{cfg['host']}:{cfg['port']}",
            "origen": cfg["origen"]}


def enviar(para, asunto: str, texto: str, html: str | None = None,
           responder_a: str | None = None) -> tuple[bool, str]:
    """Envia un correo (sincrono). Devuelve (ok, error). Nunca lanza."""
    cfg = _cfg()
    if not cfg:
        return False, "correo no configurado"
    if isinstance(para, str):
        para = [para]
    para = [p.strip() for p in (para or []) if p and p.strip()]
    if not para:
        return False, "sin destinatario"
    try:
        msg = EmailMessage()
        msg["Subject"] = asunto
        msg["From"] = cfg["de"]
        msg["To"] = ", ".join(para)
        if responder_a:
            msg["Reply-To"] = responder_a
        msg.set_content(texto or "")
        if html:
            msg.add_alternative(html, subtype="html")
        if cfg["port"] == 465:
            with smtplib.SMTP_SSL(cfg["host"], cfg["port"], timeout=20) as s:
                if cfg["user"]:
                    s.login(cfg["user"], cfg["password"])
                s.send_message(msg)
        else:
            with smtplib.SMTP(cfg["host"], cfg["port"], timeout=20) as s:
                s.ehlo()
                try:
                    s.starttls()
                    s.ehlo()
                except smtplib.SMTPException:
                    pass  # servidor interno sin TLS
                if cfg["user"]:
                    s.login(cfg["user"], cfg["password"])
                s.send_message(msg)
        return True, ""
    except Exception as e:  # noqa: BLE001 — best-effort, el error va al historial
        return False, f"{type(e).__name__}: {e}"
