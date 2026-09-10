"""Envio de correo del ERP de Produccion (avisos de muestras).

Funciona igual que los avisos de Rols Muestras (muestras.rolscarpets.com):
por defecto entrega al MTA local de Plesk (localhost:25, sin credenciales),
que es quien reparte a los buzones de rolscarpets.com. No hace falta
configurar nada en el servidor. Si hiciera falta otro servidor, se acepta
cualquiera de las dos convenciones ya usadas en la suite (en el .env del
servidor, NUNCA en el repo):

  Rols One (notificar.py):   ROLS_SMTP_HOST / ROLS_SMTP_PORT / ROLS_SMTP_USER
                             ROLS_SMTP_PASS / ROLS_SMTP_FROM
  Rols Muestras:             SMTP_HOST / SMTP_PORT / SMTP_USER / SMTP_PASS

o un fichero `correo.json` en ROLS_DATA_DIR con host, port, user, pass, from.

Remitente por defecto: "Rols Producción <produccion@rolscarpets.com>"
(ROLS_SMTP_FROM lo cambia). En local (Windows) no hay MTA: sin configuracion
explicita `configurado()` es False y no se intenta nada.
"""
from __future__ import annotations

import json
import os
import smtplib
from email.message import EmailMessage
from pathlib import Path

REMITENTE_DEFECTO = "Rols Producción <produccion@rolscarpets.com>"


def _fichero_cfg() -> Path:
    base = os.environ.get("ROLS_DATA_DIR") or str(Path(__file__).resolve().parent.parent / "data")
    return Path(base) / "correo.json"


def _env(*claves) -> str:
    for k in claves:
        v = (os.environ.get(k) or "").strip()
        if v:
            return v
    return ""


def _cfg() -> dict | None:
    host = _env("ROLS_SMTP_HOST")
    if host:
        origen = "entorno (ROLS_SMTP_*)"
        port, user, password = _env("ROLS_SMTP_PORT"), _env("ROLS_SMTP_USER"), os.environ.get("ROLS_SMTP_PASS") or ""
    else:
        host = _env("SMTP_HOST")
        if host:
            origen = "entorno (SMTP_*, como Rols Muestras)"
            port, user, password = _env("SMTP_PORT"), _env("SMTP_USER"), os.environ.get("SMTP_PASS") or ""
        else:
            port = user = password = ""
            origen = ""
            f = _fichero_cfg()
            if f.exists():
                try:
                    d = json.loads(f.read_text(encoding="utf-8"))
                    host = (d.get("host") or "").strip()
                    if host:
                        origen = "fichero correo.json"
                        port = str(d.get("port") or "")
                        user = (d.get("user") or "").strip()
                        password = d.get("pass") or d.get("password") or ""
                except (OSError, ValueError, AttributeError):
                    host = ""
            if not host:
                if os.name == "nt":
                    return None   # local Windows: sin MTA, no se intenta
                host, port, origen = "localhost", "25", "MTA local de Plesk (como Rols Muestras)"
    try:
        port_i = int(port or (25 if host in ("localhost", "127.0.0.1") else 587))
    except (TypeError, ValueError):
        port_i = 25 if host in ("localhost", "127.0.0.1") else 587
    de = _env("ROLS_SMTP_FROM", "AVISOS_FROM") or REMITENTE_DEFECTO
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
            with smtplib.SMTP_SSL(cfg["host"], cfg["port"], timeout=25) as s:
                if cfg["user"]:
                    s.login(cfg["user"], cfg["password"])
                s.send_message(msg)
        else:
            with smtplib.SMTP(cfg["host"], cfg["port"], timeout=25) as s:
                s.ehlo()
                # TLS oportunista (igual que Rols Muestras): si el servidor lo
                # ofrece se usa; obligatorio con Microsoft 365.
                if s.has_extn("starttls"):
                    s.starttls()
                    s.ehlo()
                if cfg["user"]:
                    s.login(cfg["user"], cfg["password"])
                s.send_message(msg)
        return True, ""
    except Exception as e:  # noqa: BLE001 — best-effort, el error va al historial
        return False, f"{type(e).__name__}: {e}"
