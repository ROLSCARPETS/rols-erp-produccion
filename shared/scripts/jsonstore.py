"""Almacén documental transaccional respaldado por SQLite.

Sustituye el patrón "JSON-file + threading.RLock + lru_cache" (que NO es seguro
entre PROCESOS: Passenger puede tener varios workers, cada uno con su lock y su
caché) por una única BD SQLite con transacciones reales:

  - `BEGIN IMMEDIATE` toma un lock de escritura que **serializa a los escritores
    entre procesos**, así que el ciclo load→mutate→save de cada módulo deja de
    perder escrituras (adiós al lost-update de stock).
  - La escritura de SQLite es atómica y durable → un corte a mitad no deja el
    dato corrupto (adiós al "un JSON corrupto tumba la app").
  - WAL: los lectores no bloquean al escritor ni entre sí.

Cada "documento" (el dict que antes era un fichero JSON) se guarda como una fila
`(key, data)` en la tabla `documents`. La lógica de negocio de cada módulo (todo
el manejo de dicts) NO cambia: solo cambian `cargar()`/`_guardar()` y los
`with _lock:` pasan a `with store().tx():`.

Uso típico en un módulo de datos:

    import jsonstore
    _KEY = "lanas_inventario"
    def _default(): return {"_meta": {"version_schema": 1}, "lanas": []}
    def cargar():   return jsonstore.store().load(_KEY, _default, _LEGACY_JSON_PATH)
    def _guardar(d): jsonstore.store().save(_KEY, d)
    # y cada `with _lock:` (load→mutate→save) -> `with jsonstore.store().tx():`

La BD vive en ROLS_DATA_DIR/erp.db (en prod, fuera del docroot) o en
shared/data/erp.db (local). La migración desde los JSON legacy es AUTOMÁTICA y no
destructiva: al primer `load` de una key sin fila, se importa el JSON si existe
(el fichero JSON se conserva como backup).
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path


# Cache COMPARTIDA entre peticiones (solo para las keys que la piden: hoy,
# el documento de muestras, que pesa varios MB). Cada documento lleva una
# `version` que sube en cada guardado; antes de reutilizar lo ya interpretado
# se mira (version, updated_at) en la BD, que cuesta microsegundos, asi que un
# guardado de OTRO proceso se nota en la siguiente lectura. Ademas caduca sola
# a los CACHE_TTL segundos, por si algo escribiera sin pasar por aqui.
# El objeto se COMPARTE entre peticiones del proceso: quien lo lee NO debe
# modificarlo (las funciones publicas de lectura devuelven copias).
CACHE_TTL = 120.0


def _db_path() -> Path:
    base = os.environ.get("ROLS_DATA_DIR")
    if not base:
        # shared/data (hermano de scripts), igual que el resto de módulos.
        base = str(Path(__file__).resolve().parent.parent / "data")
    return Path(base) / "erp.db"


class _Store:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Conexión y profundidad de transacción POR HILO (cada worker-thread
        # tiene la suya; SQLite serializa entre hilos y procesos por fichero).
        self._local = threading.local()
        self._cache: dict = {}          # key -> ((version, updated_at), dict, momento)
        self._cache_lock = threading.Lock()
        self._init_schema()

    def _conn(self) -> sqlite3.Connection:
        c = getattr(self._local, "conn", None)
        if c is None:
            # isolation_level=None → controlamos las transacciones a mano
            # (BEGIN IMMEDIATE / COMMIT) en tx().
            c = sqlite3.connect(str(self.path), timeout=30, isolation_level=None)
            c.execute("PRAGMA journal_mode=WAL")
            c.execute("PRAGMA busy_timeout=30000")   # espera al lock, no falla
            c.execute("PRAGMA synchronous=NORMAL")
            self._local.conn = c
        return c

    def _init_schema(self) -> None:
        c = self._conn()
        c.execute(
            "CREATE TABLE IF NOT EXISTS documents ("
            " key TEXT PRIMARY KEY, data TEXT NOT NULL, updated_at TEXT,"
            " version INTEGER NOT NULL DEFAULT 0)")
        # BDs de antes de la cache: se les anade la columna (idempotente; si
        # otro proceso la anade a la vez, el segundo ALTER falla y da igual).
        cols = {r[1] for r in c.execute("PRAGMA table_info(documents)")}
        if "version" not in cols:
            try:
                c.execute("ALTER TABLE documents ADD COLUMN version INTEGER NOT NULL DEFAULT 0")
            except sqlite3.OperationalError:
                pass

    def invalidar(self, key: str | None = None) -> None:
        """Olvida lo cacheado de `key` (o de todo)."""
        with self._cache_lock:
            if key is None:
                self._cache.clear()
            else:
                self._cache.pop(key, None)

    def _load_compartida(self, key: str):
        """Fuera de transaccion: el documento cacheado si sigue al dia, o
        recien leido (y cacheado). None si la key no existe (lo resuelve el
        camino normal, con su importacion legacy)."""
        c = self._conn()
        fila = c.execute("SELECT version, updated_at FROM documents WHERE key=?", (key,)).fetchone()
        if fila is None:
            return None
        ahora = time.monotonic()
        with self._cache_lock:
            ent = self._cache.get(key)
        if ent and ent[0] == (fila[0], fila[1]) and ahora - ent[2] < CACHE_TTL:
            return ent[1]
        # Datos y huella en la MISMA consulta: si otro proceso escribe entre
        # medias, lo que se cachea es coherente con su huella.
        fila = c.execute("SELECT data, version, updated_at FROM documents WHERE key=?", (key,)).fetchone()
        if fila is None:
            return None
        try:
            data = json.loads(fila[0])
        except (ValueError, TypeError):
            return None                 # que el camino normal lo registre
        with self._cache_lock:
            self._cache[key] = ((fila[1], fila[2]), data, ahora)
        return data

    @contextmanager
    def tx(self):
        """Transacción EXCLUSIVA reentrante. `BEGIN IMMEDIATE` serializa a los
        escritores entre procesos. Anidable (solo la más externa hace
        BEGIN/COMMIT): permite envolver un load→mutate→save completo, y que
        funciones anidadas (incluso de otro módulo) escriban en la misma
        transacción.

        Además, DENTRO de una transacción todas las `load()` de la misma key
        devuelven el MISMO objeto dict (identidad por transacción). Esto es
        imprescindible: el código de los módulos hace `data = cargar()` y luego
        llama a helpers (buscar_lana, ...) que vuelven a `cargar()`; muta el item
        que devuelve el helper y guarda `data`. Solo funciona si ambas cargas son
        el mismo objeto (antes lo garantizaba el lru_cache por proceso)."""
        c = self._conn()
        depth = getattr(self._local, "depth", 0)
        if depth == 0:
            c.execute("BEGIN IMMEDIATE")
            self._local.tx_docs = {}      # caché de identidad de esta transacción
        self._local.depth = depth + 1
        try:
            yield
        except BaseException:
            self._local.depth = depth
            if depth == 0:
                self._local.tx_docs = None
                try:
                    c.execute("ROLLBACK")
                except sqlite3.Error:
                    pass
            raise
        else:
            self._local.depth = depth
            if depth == 0:
                try:
                    c.execute("COMMIT")
                except BaseException:
                    # Si el COMMIT falla (disco lleno, I/O...), dejar la
                    # conexion y el hilo LIMPIOS: sin esto, tx_docs quedaba
                    # poblado para siempre y todas las load() posteriores del
                    # hilo servian el dict en memoria en vez de leer la BD.
                    try:
                        c.execute("ROLLBACK")
                    except sqlite3.Error:
                        pass
                    raise
                finally:
                    self._local.tx_docs = None

    def en_transaccion(self) -> bool:
        """True si este hilo tiene una transaccion abierta (load→mutate→save)."""
        return getattr(self._local, "depth", 0) > 0

    def load(self, key: str, default_factory, legacy_json=None, compartida: bool = False) -> dict:
        """Devuelve el documento `key` (dict). Dentro de una transacción,
        devuelve SIEMPRE el mismo objeto (para load→mutate→save), leido de la
        BD con el cerrojo tomado. Fuera de una transacción lee fresco de la BD,
        salvo con `compartida=True`: entonces reutiliza lo ya interpretado
        mientras su version siga siendo la de la BD (ver CACHE_TTL) y el
        objeto devuelto es COMPARTIDO: no se debe modificar. Si no hay fila y
        hay un JSON legacy, lo importa una vez."""
        docs = getattr(self._local, "tx_docs", None)
        if docs is not None and key in docs:
            return docs[key]
        if compartida and docs is None:
            ya = self._load_compartida(key)
            if ya is not None:
                return ya
        c = self._conn()
        row = c.execute("SELECT data FROM documents WHERE key=?", (key,)).fetchone()
        data = None
        if row is not None:
            try:
                data = json.loads(row[0])
            except (ValueError, TypeError):
                import logging
                logging.getLogger("erp.store").error(
                    "documento %r ilegible en la BD; se usa el default", key)
                data = default_factory()
        elif legacy_json:
            # No hay fila: migración one-time desde el JSON legacy. Con
            # INSERT-si-no-existe: si otro worker migró (y quizá el usuario ya
            # escribió encima) entre nuestro SELECT y este punto, NO pisamos
            # su fila — releemos la que ganó.
            p = Path(legacy_json)
            if p.exists():
                try:
                    d = json.loads(p.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    d = None
                if isinstance(d, dict):
                    if self._save_if_absent(key, d):
                        data = d
                    else:
                        row = c.execute(
                            "SELECT data FROM documents WHERE key=?",
                            (key,)).fetchone()
                        if row is not None:
                            try:
                                data = json.loads(row[0])
                            except (ValueError, TypeError):
                                data = d
                        else:
                            data = d
        if data is None:
            data = default_factory()
        if docs is not None:
            docs[key] = data
        return data

    def _save_if_absent(self, key: str, data: dict) -> bool:
        """Inserta el documento solo si la key NO existe (para la migración
        legacy). Devuelve True si esta llamada insertó la fila."""
        blob = json.dumps(data, ensure_ascii=False, allow_nan=False)
        now = datetime.now().isoformat(timespec="seconds")
        c = self._conn()
        with self.tx():
            cur = c.execute(
                "INSERT INTO documents(key, data, updated_at, version) VALUES(?,?,?,1) "
                "ON CONFLICT(key) DO NOTHING",
                (key, blob, now))
            return cur.rowcount > 0

    def save(self, key: str, data: dict) -> None:
        """Escribe el documento `key`. Dentro de una transacción (reentrante):
        si ya hay una abierta (load→mutate→save del módulo) se une a ella; si no,
        abre una propia."""
        docs = getattr(self._local, "tx_docs", None)
        # allow_nan=False: si algún kg/coste quedó como NaN/Infinity, esto LANZA
        # en vez de escribir un dato corrupto (defensa central; la mutación falla
        # limpia y no se persiste basura). Los módulos validan además en la
        # entrada con math.isfinite para dar un error claro al usuario.
        blob = json.dumps(data, ensure_ascii=False, allow_nan=False)
        now = datetime.now().isoformat(timespec="seconds")
        c = self._conn()
        with self.tx():
            c.execute(
                "INSERT INTO documents(key, data, updated_at, version) VALUES(?,?,?,1) "
                "ON CONFLICT(key) DO UPDATE SET data=excluded.data, "
                "updated_at=excluded.updated_at, version=documents.version+1",
                (key, blob, now))
        # lo cacheado de esta key ya no vale (la version acaba de subir)
        self.invalidar(key)
        # Mantener la identidad en la transacción (si save se llama dentro de una).
        docs2 = getattr(self._local, "tx_docs", None)
        if docs2 is not None:
            docs2[key] = data
        elif docs is not None:
            docs[key] = data


_singleton = None
_singleton_lock = threading.Lock()


def store() -> _Store:
    """Instancia única del almacén (una BD, conexiones por hilo)."""
    global _singleton
    if _singleton is None:
        with _singleton_lock:
            if _singleton is None:
                _singleton = _Store(_db_path())
    return _singleton
