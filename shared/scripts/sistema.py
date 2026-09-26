"""Mantenimiento del ERP: copias de seguridad de la BD y registro de errores.

COPIAS. Todos los datos de produccion viven en un unico SQLite (`erp.db`, en
ROLS_DATA_DIR). Una vez al dia (lo dispara la propia app, ver app.py) se saca
una copia CONSISTENTE con la API de backup de SQLite —vale aunque haya gente
escribiendo, y con WAL—, se comprime y se guarda en ROLS_DATA_DIR/copias como
`erp-AAAA-MM-DD.db.gz`. Se conservan las ultimas `DIARIAS` y, de las mas
antiguas, la del lunes de las ultimas `SEMANALES` semanas. Las copias estan en
el mismo servidor: protegen de un borrado, una corrupcion o un cambio que sale
mal, no de perder el servidor — para eso se descargan desde el panel.
Los ficheros adjuntos de las muestras (ROLS_DATA_DIR/muestras_adjuntos) NO
entran en la copia diaria.

Restaurar una copia (a mano, con la app parada):
    gunzip -c erp-AAAA-MM-DD.db.gz > erp.db   (y borrar erp.db-wal / erp.db-shm)

ERRORES. Los errores no controlados (HTTP 500) quedan apuntados (los ultimos
`MAX_ERRORES`) en el documento `erp_sistema`, que tambien guarda a quien se
avisa por correo. Todo best-effort: nada de aqui puede tumbar una peticion.
"""
from __future__ import annotations

import gzip
import os
import re
import shutil
import sqlite3
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path

import jsonstore

DIARIAS = 14
SEMANALES = 8
MAX_ERRORES = 30
_KEY = "erp_sistema"
_PATRON = re.compile(r"^erp-(\d{4}-\d{2}-\d{2})\.db\.gz$")
_RE_EMAIL = re.compile(r"^[^@\s,;]+@[^@\s,;]+\.[^@\s,;]{2,}$")


# ---------------------------------------------------------------------------
# Copias de seguridad
# ---------------------------------------------------------------------------

def carpeta_copias() -> Path:
    return jsonstore._db_path().parent / "copias"


def _nombre(dia: date) -> str:
    return f"erp-{dia.isoformat()}.db.gz"


def listar_copias() -> list[dict]:
    """Las copias que hay, la mas reciente primero."""
    d = carpeta_copias()
    if not d.is_dir():
        return []
    out = []
    for f in d.iterdir():
        m = _PATRON.match(f.name)
        if m and f.is_file():
            st = f.stat()
            out.append({"nombre": f.name, "dia": m.group(1), "tamano": st.st_size,
                        "hecha_en": datetime.fromtimestamp(st.st_mtime).isoformat(timespec="seconds")})
    out.sort(key=lambda x: x["dia"], reverse=True)
    return out


def ruta_copia(nombre: str) -> Path | None:
    """Ruta de una copia por su nombre (solo nombres validos: nada de rutas)."""
    if not _PATRON.match(nombre or ""):
        return None
    p = carpeta_copias() / nombre
    return p if p.is_file() else None


def hacer_copia(dia: date | None = None) -> dict:
    """Copia consistente de la BD de hoy (o `dia`), comprimida. Si ya habia una
    de ese dia, se sustituye. Devuelve sus datos (como listar_copias)."""
    dia = dia or date.today()
    origen = jsonstore._db_path()
    destino_dir = carpeta_copias()
    destino_dir.mkdir(parents=True, exist_ok=True)
    fd, tmp_db = tempfile.mkstemp(prefix="erp-copia-", suffix=".db", dir=destino_dir)
    os.close(fd)
    tmp_gz = tmp_db + ".gz"
    try:
        # API de backup de SQLite: una foto coherente aunque haya escrituras
        src = sqlite3.connect(str(origen), timeout=30)
        dst = sqlite3.connect(tmp_db)
        try:
            src.backup(dst)
        finally:
            dst.close()
            src.close()
        with open(tmp_db, "rb") as fi, gzip.open(tmp_gz, "wb", compresslevel=6) as fo:
            shutil.copyfileobj(fi, fo)
        final = destino_dir / _nombre(dia)
        os.replace(tmp_gz, final)   # atomico: si dos procesos coinciden, gana uno entero
    finally:
        for t in (tmp_db, tmp_gz):
            try:
                os.remove(t)
            except OSError:
                pass
    rotar()
    return next(c for c in listar_copias() if c["nombre"] == _nombre(dia))


def rotar(hoy: date | None = None) -> list[str]:
    """Borra las copias que sobran: se quedan las ultimas DIARIAS y, de las
    anteriores, la de cada lunes de las ultimas SEMANALES semanas."""
    hoy = hoy or date.today()
    copias = listar_copias()
    quedan = {c["nombre"] for c in copias[:DIARIAS]}
    limite = hoy - timedelta(weeks=SEMANALES)
    for c in copias[DIARIAS:]:
        d = date.fromisoformat(c["dia"])
        if d.weekday() == 0 and d >= limite:
            quedan.add(c["nombre"])
    borradas = []
    for c in copias:
        if c["nombre"] not in quedan:
            try:
                (carpeta_copias() / c["nombre"]).unlink()
                borradas.append(c["nombre"])
            except OSError:
                pass
    return borradas


def copia_diaria_si_toca() -> dict | None:
    """La copia de hoy, si aun no esta hecha. None si ya habia."""
    if ruta_copia(_nombre(date.today())):
        return None
    return hacer_copia()


def verificar_copia(nombre: str) -> dict:
    """Abre una copia y cuenta lo que tiene (sin tocar la BD de verdad)."""
    p = ruta_copia(nombre)
    if not p:
        raise FileNotFoundError(nombre)
    fd, tmp = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        with gzip.open(p, "rb") as fi, open(tmp, "wb") as fo:
            shutil.copyfileobj(fi, fo)
        con = sqlite3.connect(tmp)
        try:
            integridad = con.execute("PRAGMA integrity_check").fetchone()[0]
            docs = {k: len(v) for k, v in con.execute("SELECT key, data FROM documents")}
        finally:
            con.close()
        return {"integridad": integridad, "documentos": docs}
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Errores de la aplicacion
# ---------------------------------------------------------------------------

def _default() -> dict:
    return {"alertas_email": [], "errores": []}


def cargar() -> dict:
    data = jsonstore.store().load(_KEY, _default)
    data.setdefault("alertas_email", [])
    data.setdefault("errores", [])
    return data


def alertas_email() -> list[str]:
    return list(cargar().get("alertas_email") or [])


def guardar_alertas_email(valor) -> tuple[list[str] | None, str]:
    """Valida y guarda a quien se avisa de los errores (lista o texto con comas)."""
    if isinstance(valor, str):
        valor = re.split(r"[,;\s]+", valor)
    if not isinstance(valor, list):
        return None, "los destinatarios deben ser una lista de e-mails"
    limpios = []
    for v in valor:
        v = str(v or "").strip().lower()
        if not v:
            continue
        if not _RE_EMAIL.match(v):
            return None, f"e-mail no válido: {v!r}"
        if v not in limpios:
            limpios.append(v)
    if len(limpios) > 5:
        return None, "como mucho 5 destinatarios"
    with jsonstore.store().tx():
        data = cargar()
        data["alertas_email"] = limpios
        jsonstore.store().save(_KEY, data)
    return limpios, ""


def registrar_error(metodo: str, ruta: str, usuario: str, tipo: str, mensaje: str,
                    traza: str, avisado: bool = False) -> None:
    """Apunta un error (los ultimos MAX_ERRORES). Nunca lanza."""
    try:
        with jsonstore.store().tx():
            data = cargar()
            data["errores"].append({
                "en": datetime.now().isoformat(timespec="seconds"), "metodo": metodo,
                "ruta": ruta[:200], "usuario": usuario[:120], "tipo": tipo[:120],
                "mensaje": mensaje[:500], "traza": traza[-4000:], "avisado": bool(avisado)})
            data["errores"] = data["errores"][-MAX_ERRORES:]
            jsonstore.store().save(_KEY, data)
    except Exception:
        pass


def errores_recientes(n: int = 10) -> list[dict]:
    return list(reversed((cargar().get("errores") or [])[-n:]))
