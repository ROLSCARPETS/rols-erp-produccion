"""Rols One — fuente unica de materias primas (lanas).

Cada entrada del JSON representa una VARIANTE calidad+proveedor:
una calidad concreta (titulo "65/2C" + tipo "pais normal") servida por un
proveedor concreto ("COBO"). La misma calidad puede tener varias variantes
(p.ej. AUSTRALIA 100 2/C la sirven COBO y FILMURO simultaneamente).

Cada variante tiene varios PARTIDOS (= LOTES en la jerga de produccion):
{partido, kg, coste_kg?, fecha_entrada?}. Es la unidad atomica de stock:
no se mezclan, cada uno mantiene su coste de entrada.

JSON en shared/data/lanas_inventario.json. Esquema (v2):
{
  "_meta": {...},
  "lanas": [
    {
      "id":          "65-2c__pais-normal__cobo",   # estable por variante
      "calidad_id":  "65-2c__pais-normal",         # agrupador (usado por el escandallo)
      "material":    "lana",
      "titulo":      "65/2C",
      "tipo":        "pais normal",
      "proveedor":   "COBO",
      "seccion":     "LANA 65 2/C",                # display, legacy
      "categoria":   "LA65",                       # display, legacy
      "nombre":      "65 2/C PAIS NORMAL",         # display, legacy
      "partidos": [
        {"partido": "3923C", "kg": 1662.0, "coste_kg": null, "fecha_entrada": null},
        ...
      ],
      "total_kg":       2211.0,
      "limite_kg":      700.0,
      "kg_a_pedir":     2000.0,
      "pedido_hecho":   "3923C",                   # string legacy
      "pedidos":        [...],                     # historico estructurado
      "observaciones":  "ENTRAN 1600 KG",
      "precio_2022":    null,
      "precio_2022b":   7.36,
      "precio_2025":    7.36,
      "precio_2026":    7.71
    },
    ...
  ],
  "basamentos": [...],
  "backings":   [...]
}

Vinculacion con el escandallo de productos: cada item del escandallo usa
`calidad_id` (sin proveedor). Al consumir, el operario elige proveedor y
partido concretos.
"""
from __future__ import annotations

import json
import math
import re
import threading
from datetime import datetime
from functools import lru_cache
from pathlib import Path

import os

import jsonstore  # BD SQLite transaccional (sustituye JSON+RLock; ver jsonstore.py)

import logging
_log = logging.getLogger("erp.lanas")


def _float_finito(valor) -> float:
    """float(valor) validando que sea un numero FINITO. NaN/Infinity pasan
    los guards de negocio (`NaN <= 0` es False) y solo reventaban al
    persistir (allow_nan=False en jsonstore) → 500 en vez de un 400 claro.
    Lanza ValueError para que el try/except del caller lo convierta en error."""
    v = float(valor)
    if not math.isfinite(v):
        raise ValueError("no finito")
    return v

# Ruta del JSON LEGACY: solo para la migración one-time a SQLite (se conserva de
# backup). En prod ROLS_DATA_DIR lo fija FUERA del docroot; en local shared/data.
DATA_PATH = Path(os.environ.get("ROLS_DATA_DIR") or Path(__file__).resolve().parent.parent / "data") / "lanas_inventario.json"
_lock = threading.RLock()  # (histórico; los `with jsonstore.store().tx():` ahora son transacciones)


# ---------------------------------------------------------------------------
# Identificador estable
# ---------------------------------------------------------------------------

def _slug(s: str) -> str:
    """Slug consistente con el resto de la app: minusculas, sin acentos,
    espacios -> guion."""
    import unicodedata
    if not s:
        return ""
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.lower().strip()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-")


def lana_id(item: dict) -> str:
    """ID estable de la variante. Si el JSON ya lo tiene precomputado
    (esquema v2), se devuelve tal cual; si no, se deriva de titulo+tipo+
    proveedor con la nueva convencion.

    Ej: '65-2c__pais-normal__cobo'.
    """
    if item.get("id"):
        return item["id"]
    titulo = item.get("titulo") or ""
    tipo = item.get("tipo") or ""
    proveedor = item.get("proveedor") or ""
    base = f"{_slug(titulo)}__{_slug(tipo)}" if titulo else _slug(tipo)
    return f"{base}__{_slug(proveedor)}"


def calidad_id(item: dict) -> str:
    """ID de calidad (sin proveedor) — agrupa variantes equivalentes.
    Lo usa el escandallo de productos para apuntar a una receta
    independiente del proveedor.

    Ej: '65-2c__pais-normal'.
    """
    if item.get("calidad_id"):
        return item["calidad_id"]
    titulo = item.get("titulo") or ""
    tipo = item.get("tipo") or ""
    return f"{_slug(titulo)}__{_slug(tipo)}" if titulo else _slug(tipo)


# ---------------------------------------------------------------------------
# Carga / persistencia con cache
# ---------------------------------------------------------------------------

_KEY = "lanas_inventario"


def _default() -> dict:
    return {"_meta": {"version_schema": 1}, "lanas": [],
            "basamentos": [], "backings": []}


def cargar() -> dict:
    """Carga el documento desde SQLite (migra el JSON legacy la 1ª vez)."""
    return jsonstore.store().load(_KEY, _default, DATA_PATH)


def invalidar_cache() -> None:
    # Ya no hay caché por proceso: SQLite se lee fresco. Se mantiene por compat.
    pass


def _guardar(data: dict) -> None:
    data.setdefault("_meta", {})
    data["_meta"]["actualizado_en"] = datetime.now().isoformat(timespec="seconds")
    jsonstore.store().save(_KEY, data)
    invalidar_cache()


# ---------------------------------------------------------------------------
# Lectura
# ---------------------------------------------------------------------------

def listar_lanas(con_id: bool = True) -> list[dict]:
    """Devuelve todas las lanas, con un campo `id` calculado para que el
    cliente pueda referenciarlas en PUT/PATCH."""
    lanas = list(cargar().get("lanas", []))
    if con_id:
        for l in lanas:
            l["id"] = lana_id(l)
    return lanas


def listar_basamentos() -> list[dict]:
    return list(cargar().get("basamentos", []))


def listar_backings() -> list[dict]:
    return list(cargar().get("backings", []))


def buscar_lana(lid: str) -> tuple[int, dict] | tuple[None, None]:
    """Localiza una variante por id (acepta tambien id_legacy de la era
    pre-unificacion). Devuelve (idx, dict) o (None, None)."""
    for i, l in enumerate(cargar().get("lanas", [])):
        if l.get("id") == lid or l.get("id_legacy") == lid or lana_id(l) == lid:
            return i, l
    return None, None


# ---------------------------------------------------------------------------
# Estadisticas para la cabecera de la UI
# ---------------------------------------------------------------------------

def _tiene_pedido_abierto(item: dict) -> bool:
    """Una variante esta 'en camino' si tiene al menos un pedido abierto
    en pedidos[].

    El campo legacy `pedido_hecho` ya NO cuenta: era ambiguo (a veces
    contenia ref de partido ya recibido, a veces nota de pedido en
    marcha, a veces basura). Para tener algo "en camino" hay que
    cursarlo formalmente desde la UI (boton "Hacer pedido").
    """
    for p in (item.get("pedidos") or []):
        if (p.get("estado") or "").lower() == "abierto":
            return True
    return False


def _estado_fila(item: dict) -> str:
    """Devuelve 'en-camino' | 'pedir' | 'bajo' | 'ok'.

    Prioridad: 'en-camino' siempre gana — una vez has cursado el pedido,
    la variante deja de aparecer como pendiente hasta que llega la
    mercancia (o se marca el pedido como recibido manualmente).

    Reglas si no hay pedido en camino:
    - pedir: total_kg <= limite_kg
    - bajo:  total_kg <= limite_kg * 1.3 (margen del 30%)
    - ok:    todo lo demas (o sin limite definido)
    """
    if _tiene_pedido_abierto(item):
        return "en-camino"
    try:
        total  = float(item.get("total_kg") or 0)
        limite = float(item.get("limite_kg") or 0)
    except (TypeError, ValueError):
        return "ok"
    if limite <= 0:
        return "ok"
    if total <= limite:
        return "pedir"
    if total <= limite * 1.3:
        return "bajo"
    return "ok"


def estadisticas() -> dict:
    """Resumen para la barra superior de la UI:
    n_pedir, n_bajo, n_ok, total_kg, valor_total_eur."""
    lanas = cargar().get("lanas", [])
    n_en_camino = n_pedir = n_bajo = n_ok = 0
    total_kg = 0.0
    valor = 0.0
    for l in lanas:
        e = _estado_fila(l)
        if   e == "en-camino": n_en_camino += 1
        elif e == "pedir":     n_pedir     += 1
        elif e == "bajo":      n_bajo      += 1
        else:                  n_ok        += 1
        try:
            t = float(l.get("total_kg") or 0)
            total_kg += t
            p = l.get("precio_2026") or l.get("precio_2025") or 0
            if isinstance(p, (int, float)):
                valor += t * float(p)
        except (TypeError, ValueError):
            pass
    return {
        "n_pedir":         n_pedir,
        "n_en_camino":     n_en_camino,
        "n_bajo":          n_bajo,
        "n_ok":            n_ok,
        "n_total":         len(lanas),
        "total_kg":        round(total_kg, 1),
        "valor_total_eur": round(valor, 2),
    }


# ---------------------------------------------------------------------------
# Escritura: campos editables desde la UI
#
# Solo se permiten cambios en:
#   - limite_kg, kg_a_pedir, pedido_hecho (planificacion)
#   - observaciones                       (texto libre)
#   - partidos                            (cuando entra mercancia/se consume)
#   - precio_2025, precio_2026            (precios actuales)
#
# Los campos identificadores (seccion, categoria, nombre, proveedor) NO se
# editan desde aqui: si cambian, mejor crear una entrada nueva.
# ---------------------------------------------------------------------------

CAMPOS_EDITABLES = {
    "limite_kg", "kg_a_pedir",
    "observaciones", "precio_2025", "precio_2026",
    # Precio tarifa actual (€/kg). Es el precio "oficial" que el
    # proveedor te ha indicado y por el que se sugiere el eur_kg al
    # generar un pedido nuevo. Distinto del coste_kg de un partido
    # concreto. Cuando se edita, fecha_tarifa_actual se auto-actualiza.
    "tarifa_actual_eur_kg",
}
# Nota: pedido_hecho ya no es editable. Era texto libre ambiguo (a veces
# ref de partido, a veces nota de pedido). Su funcion la cubre `pedidos[]`
# estructurado y `observaciones` para notas libres.


def actualizar_lana(lid: str, campo: str, valor) -> tuple[dict | None, str]:
    """Actualiza UN campo de una lana. Devuelve (item_actualizado, '') o
    (None, error)."""
    if campo not in CAMPOS_EDITABLES:
        return None, f"campo no editable: {campo!r}"
    with jsonstore.store().tx():
        data = cargar()
        for i, l in enumerate(data.get("lanas", [])):
            # Aceptar id actual, id_legacy o el derivado, igual que
            # buscar_lana (tras renombrar proveedor, el id viejo debe
            # seguir resolviendo tambien aqui).
            if l.get("id") == lid or l.get("id_legacy") == lid or lana_id(l) == lid:
                # Normalizar valor: numericos como float, strings tal cual
                if campo in ("limite_kg", "kg_a_pedir", "precio_2025", "precio_2026"):
                    if valor in (None, ""):
                        l[campo] = None
                    else:
                        try:
                            l[campo] = _float_finito(valor)
                        except (TypeError, ValueError):
                            return None, f"{campo} debe ser numerico"
                elif campo == "tarifa_actual_eur_kg":
                    # Numerico + actualiza fecha automaticamente
                    if valor in (None, ""):
                        l["tarifa_actual_eur_kg"] = None
                        l["tarifa_actual_fecha"] = None
                    else:
                        try:
                            l["tarifa_actual_eur_kg"] = _float_finito(valor)
                        except (TypeError, ValueError):
                            return None, "tarifa_actual_eur_kg debe ser numerico"
                        l["tarifa_actual_fecha"] = datetime.now().date().isoformat()
                else:
                    l[campo] = (valor or "").strip() if isinstance(valor, str) else valor
                # Recalcular total_kg si cambia partidos (no aplica aqui pero
                # lo dejamos preparado)
                _guardar(data)
                # No queremos exponer el id calculado dos veces — lo añadimos
                # al copiar al cliente
                out = dict(l)
                out["id"] = lid
                return out, ""
        return None, f"lana {lid!r} no existe"


def actualizar_partidos(lid: str, partidos: list[dict]) -> tuple[dict | None, str]:
    """Sustituye la lista completa de partidos. Recalcula total_kg automatic.

    Cada partido entrante: {partido: str, kg: number >= 0,
                            coste_kg?: number, fecha_entrada?: str}.

    Preserva los campos enriquecidos (coste_kg, fecha_entrada) de partidos
    existentes con el mismo `partido` cuando el cliente no los manda. Asi
    la UI de Compras puede seguir editando solo (partido, kg) sin perder
    trazabilidad.
    """
    if not isinstance(partidos, list):
        return None, "partidos debe ser una lista"
    with jsonstore.store().tx():
        data = cargar()
        for l in data.get("lanas", []):
            if l.get("id") != lid and l.get("id_legacy") != lid and lana_id(l) != lid:
                continue
            # Indexar partidos existentes por ref para preservar metadatos
            previos = {p.get("partido"): p for p in (l.get("partidos") or [])}
            limpios = []
            total = 0.0
            for p in partidos:
                if not isinstance(p, dict):
                    return None, "cada partido debe ser un objeto"
                pid = (p.get("partido") or "").strip()
                try:
                    kg = _float_finito(p.get("kg") or 0)
                except (TypeError, ValueError):
                    return None, "kg debe ser numerico"
                if kg < 0:
                    return None, "kg no puede ser negativo"
                if not pid and kg == 0:
                    continue
                # Coste y fecha: lo que mande el cliente, o lo previo si no.
                prev = previos.get(pid) or {}
                coste = p.get("coste_kg", prev.get("coste_kg"))
                if coste not in (None, ""):
                    try:
                        coste = _float_finito(coste)
                    except (TypeError, ValueError):
                        return None, "coste_kg debe ser numerico"
                else:
                    coste = None
                fecha = p.get("fecha_entrada", prev.get("fecha_entrada"))
                if isinstance(fecha, str):
                    fecha = fecha.strip() or None
                obs = p.get("observaciones", prev.get("observaciones"))
                if isinstance(obs, str):
                    obs = obs.strip()[:300] or None
                # kg_proveedor NO lo manda esta via (la edicion masiva solo
                # toca kg de almacen): preservarlo SIEMPRE — perderlo aqui
                # borraba en silencio los kg reservados en el proveedor.
                kg_prov_prev = prev.get("kg_proveedor")
                total_vivo = kg + float(kg_prov_prev or 0)
                # fecha_agotado con el MISMO criterio que el resto de vias:
                # consumido = sin stock vivo TOTAL (almacen + proveedor).
                fecha_agotado = prev.get("fecha_agotado")
                if total_vivo <= 0 and not fecha_agotado:
                    fecha_agotado = datetime.now().date().isoformat()
                elif total_vivo > 0:
                    fecha_agotado = None
                limpios.append({
                    "partido":       pid,
                    "kg":            round(kg, 2),
                    "kg_inicial":    prev.get("kg_inicial", round(kg, 2)),
                    "kg_proveedor":  kg_prov_prev,
                    "coste_kg":      coste,
                    "fecha_entrada": fecha,
                    "observaciones": obs,
                    # Preservar siempre los nuevos metadatos del partido
                    "estanteria":    prev.get("estanteria"),
                    "fecha_compra":  prev.get("fecha_compra"),
                    "fecha_agotado": fecha_agotado,
                })
                total += kg
            l["partidos"] = limpios
            l["total_kg"] = round(total, 2)
            _guardar(data)
            out = dict(l)
            out["id"] = lid
            return out, ""
        return None, f"lana {lid!r} no existe"


# ---------------------------------------------------------------------------
# Vista agrupada por CALIDAD (lo que ve la pestaña "Por lana")
# ---------------------------------------------------------------------------

def listar_calidades() -> list[dict]:
    """Agrupa las variantes por calidad_id. Cada calidad devuelve:
    {calidad_id, titulo, tipo, material, variantes:[...], partidos:[...],
     total_kg, coste_medio_kg, n_partidos_activos}.

    `partidos` une los partidos de todas las variantes anotando el
    proveedor en cada uno, util para la UI "Por lana" que muestra el
    inventario por receta sin importar el proveedor.
    """
    calidades: dict[str, dict] = {}
    for l in cargar().get("lanas", []):
        cid = calidad_id(l)
        if cid not in calidades:
            calidades[cid] = {
                "calidad_id":     cid,
                "titulo":         l.get("titulo") or "",
                "tipo":           l.get("tipo") or "",
                "material":       l.get("material") or "lana",
                # Clasificacion / material_felpa: empezamos vacio y
                # rellenamos con la primera variante que los tenga (mas
                # abajo). actualizar_clasificacion_calidad los pone en
                # todas las variantes a la vez, pero si una variante
                # nueva se añadio antes de que se setease la clasificacion
                # (o por una migracion vieja), podrian faltar en alguna.
                "clasificacion":  "",
                "material_felpa": "",
                "variantes":      [],
                "partidos":       [],
            }
        # Heredar clasificacion/material_felpa de cualquier variante que
        # los tenga: con que UNA los tenga, los mostramos.
        c_cl = calidades[cid]
        if not c_cl["clasificacion"] and l.get("clasificacion"):
            c_cl["clasificacion"] = l["clasificacion"]
        if not c_cl["material_felpa"] and l.get("material_felpa"):
            c_cl["material_felpa"] = l["material_felpa"]
        c = calidades[cid]
        # Variante = subconjunto operativo (proveedor + planificacion)
        c["variantes"].append({
            "id":           lana_id(l),
            "proveedor":    l.get("proveedor") or "",
            "total_kg":     l.get("total_kg") or 0,
            "limite_kg":    l.get("limite_kg") or 0,
            "kg_a_pedir":   l.get("kg_a_pedir") or 0,
            "estado":       _estado_fila(l),
        })
        # Partidos unidos (con proveedor en cada uno).
        # kg_proveedor: kg del partido que el proveedor todavia guarda en
        # su almacen (lo tiene reservado para nosotros, podemos pedir el
        # traslado cuando lo necesitemos). Si no esta definido, 0.
        for p in (l.get("partidos") or []):
            c["partidos"].append({
                "partido":        p.get("partido"),
                "kg":             p.get("kg") or 0,
                "kg_proveedor":   p.get("kg_proveedor") or 0,
                "coste_kg":       p.get("coste_kg"),
                "fecha_entrada":  p.get("fecha_entrada"),
                "proveedor":      l.get("proveedor") or "",
                "variante_id":    lana_id(l),
            })

    # Agregados por calidad
    for c in calidades.values():
        partidos_activos = [p for p in c["partidos"] if (p.get("kg") or 0) > 0]
        c["n_partidos_activos"] = len(partidos_activos)
        c["n_partidos_agotados"] = len(c["partidos"]) - len(partidos_activos)
        c["total_kg"] = round(sum(p["kg"] for p in partidos_activos), 2)
        # Sumas de planificacion a nivel calidad. Cada variante guarda su
        # propio limite_kg / kg_a_pedir; aqui los sumamos para que el
        # listado "Materias primas" pueda mostrar el total por calidad.
        c["limite_kg"]  = round(sum(float(v.get("limite_kg")  or 0) for v in c["variantes"]), 2)
        c["kg_a_pedir"] = round(sum(float(v.get("kg_a_pedir") or 0) for v in c["variantes"]), 2)
        # Coste medio ponderado (solo partidos con coste_kg conocido)
        con_coste = [p for p in partidos_activos if p.get("coste_kg") is not None]
        kg_con_coste = sum(p["kg"] for p in con_coste)
        if kg_con_coste > 0:
            valor = sum(p["kg"] * float(p["coste_kg"]) for p in con_coste)
            c["coste_medio_kg"] = round(valor / kg_con_coste, 4)
        else:
            c["coste_medio_kg"] = None

    return sorted(calidades.values(),
                  key=lambda c: (c["titulo"], c["tipo"]))


def calidad_por_id(cid: str) -> dict | None:
    """Devuelve UNA calidad agrupada por su id. None si no existe."""
    for c in listar_calidades():
        if c["calidad_id"] == cid:
            return c
    return None


# ---------------------------------------------------------------------------
# CRUD partido (= lote): operaciones atomicas con movimientos
# ---------------------------------------------------------------------------

def _movs():
    """Modulo de movimientos, importado lazy para que romper movs no
    bloquee operaciones de inventario."""
    try:
        import movimientos_inventario as mi
        return mi
    except Exception:
        return None


def agregar_partido(lid: str, partido_ref: str, kg, coste_kg=None,
                    fecha_entrada: str = "", usuario: str = "",
                    observaciones: str = "") -> tuple[dict | None, str]:
    """Anade un partido nuevo a una variante. Coste, fecha y observaciones
    son opcionales (entradas viejas las traen vacias)."""
    partido_ref = (partido_ref or "").strip()
    if not partido_ref:
        return None, "ref del partido es obligatoria"
    try:
        kg_f = float(kg)
        if not math.isfinite(kg_f):
            raise ValueError
    except (TypeError, ValueError):
        return None, "kg debe ser numerico"
    if kg_f < 0:
        return None, "kg no puede ser negativo"
    if coste_kg in (None, ""):
        coste_f = None
    else:
        try:
            coste_f = float(coste_kg)
        except (TypeError, ValueError):
            return None, "coste_kg debe ser numerico"
    fecha = (fecha_entrada or "").strip() or None
    obs = (observaciones or "").strip()[:300] or None

    with jsonstore.store().tx():
        data = cargar()
        idx, item = buscar_lana(lid)
        if idx is None:
            return None, f"variante {lid!r} no existe"
        partidos = item.setdefault("partidos", [])
        if any(p.get("partido") == partido_ref for p in partidos):
            return None, f"el partido {partido_ref!r} ya existe en esta variante"
        nuevo = {"partido": partido_ref, "kg": round(kg_f, 2),
                 "kg_inicial": round(kg_f, 2),
                 "coste_kg": coste_f, "fecha_entrada": fecha,
                 "observaciones": obs,
                 "estanteria": None,
                 "fecha_compra": None,
                 "fecha_agotado": None}
        partidos.append(nuevo)
        item["total_kg"] = round(sum(p.get("kg") or 0 for p in partidos), 2)
        _guardar(data)

    mi = _movs()
    if mi:
        try:
            mi.registrar(lana_id=lid, lote=partido_ref, tipo="entrada",
                         cantidad_kg=kg_f, saldo_anterior_kg=0,
                         saldo_nuevo_kg=kg_f, coste_kg=coste_f,
                         fecha_entrada=fecha or "", usuario=usuario)
        except Exception as _e:
            # El inventario YA se guardo; que el historico falle no debe
            # tumbar la operacion, pero el silencio total ocultaba la
            # divergencia inventario↔movimientos. Al menos, dejar log.
            _log.warning("inventario mutado pero movimiento NO registrado: %s", _e)
    return nuevo, ""


def actualizar_partido(lid: str, partido_ref: str, datos: dict,
                       usuario: str = "") -> tuple[dict | None, str]:
    """Edita un partido existente. Permite renombrar (ref nueva en
    datos['partido']), cambiar kg, coste_kg, fecha_entrada."""
    if not isinstance(datos, dict):
        return None, "datos debe ser un objeto"
    nueva_ref = (datos.get("partido") or partido_ref).strip()
    saldo_anterior = 0.0
    with jsonstore.store().tx():
        data = cargar()
        idx, item = buscar_lana(lid)
        if idx is None:
            return None, f"variante {lid!r} no existe"
        partidos = item.get("partidos") or []
        pi = next((i for i, p in enumerate(partidos)
                   if p.get("partido") == partido_ref), -1)
        if pi < 0:
            return None, f"partido {partido_ref!r} no existe"
        if nueva_ref != partido_ref:
            if any(j != pi and p.get("partido") == nueva_ref
                   for j, p in enumerate(partidos)):
                return None, f"ya existe otro partido con ref {nueva_ref!r}"
        prev = partidos[pi]
        saldo_anterior = float(prev.get("kg") or 0)
        try:
            kg_f = _float_finito(datos.get("kg", prev.get("kg") or 0))
        except (TypeError, ValueError):
            return None, "kg debe ser numerico"
        if kg_f < 0:
            return None, "kg no puede ser negativo"
        coste = datos.get("coste_kg", prev.get("coste_kg"))
        if coste in (None, ""):
            coste = None
        else:
            try:
                coste = _float_finito(coste)
            except (TypeError, ValueError):
                return None, "coste_kg debe ser numerico"
        fecha = datos.get("fecha_entrada", prev.get("fecha_entrada"))
        if isinstance(fecha, str):
            fecha = fecha.strip() or None
        obs = datos.get("observaciones", prev.get("observaciones"))
        if isinstance(obs, str):
            obs = obs.strip()[:300] or None
        estanteria = datos.get("estanteria", prev.get("estanteria"))
        if isinstance(estanteria, str):
            estanteria = estanteria.strip()[:40] or None
        fecha_compra = datos.get("fecha_compra", prev.get("fecha_compra"))
        if isinstance(fecha_compra, str):
            fecha_compra = fecha_compra.strip() or None
        # fecha_agotado se gestiona automaticamente con el criterio comun:
        # consumido = sin stock vivo TOTAL (almacen Rols + proveedor). Antes
        # solo miraba kg y marcaba "consumido" partidos que aun tenian kg
        # reservados en el proveedor (estado "en fabricacion").
        # kg_proveedor: kg del partido que el proveedor guarda en su
        # almacen (reservados para Rols pero aun no traidos). Sale 0 / None
        # por defecto. NO entra en `kg` (que es lo fisicamente disponible
        # para consumir aqui) — vive en su propio campo para no romper la
        # logica de consumo. Si el usuario no lo manda en `datos`, se
        # respeta el valor previo.
        kg_proveedor = datos.get("kg_proveedor", prev.get("kg_proveedor"))
        if kg_proveedor in (None, ""):
            kg_proveedor_f = None
        else:
            try:
                kg_proveedor_f = _float_finito(kg_proveedor)
            except (TypeError, ValueError):
                return None, "kg_proveedor debe ser numerico"
            if kg_proveedor_f < 0:
                return None, "kg_proveedor no puede ser negativo"
            kg_proveedor_f = round(kg_proveedor_f, 2)
        total_vivo = kg_f + float(kg_proveedor_f or 0)
        fecha_agotado = prev.get("fecha_agotado")
        if total_vivo <= 0 and not fecha_agotado:
            fecha_agotado = datetime.now().date().isoformat()
        elif total_vivo > 0:
            fecha_agotado = None
        partidos[pi] = {"partido": nueva_ref, "kg": round(kg_f, 2),
                        # kg_inicial NO se sobreescribe — es inmutable
                        # (refleja la cantidad con la que entro el partido).
                        "kg_inicial": prev.get("kg_inicial", round(kg_f, 2)),
                        "kg_proveedor": kg_proveedor_f,
                        "coste_kg": coste, "fecha_entrada": fecha,
                        "observaciones": obs, "estanteria": estanteria,
                        "fecha_compra": fecha_compra,
                        "fecha_agotado": fecha_agotado}
        item["total_kg"] = round(sum(p.get("kg") or 0 for p in partidos), 2)
        _guardar(data)
        partido_actualizado = partidos[pi]

    mi = _movs()
    if mi:
        try:
            mi.registrar(lana_id=lid, lote=nueva_ref, tipo="ajuste",
                         cantidad_kg=kg_f - saldo_anterior,
                         saldo_anterior_kg=saldo_anterior,
                         saldo_nuevo_kg=kg_f, coste_kg=coste,
                         fecha_entrada=fecha or "", usuario=usuario,
                         nota=f"renombrado desde {partido_ref!r}"
                              if nueva_ref != partido_ref else "")
        except Exception as _e:
            # El inventario YA se guardo; que el historico falle no debe
            # tumbar la operacion, pero el silencio total ocultaba la
            # divergencia inventario↔movimientos. Al menos, dejar log.
            _log.warning("inventario mutado pero movimiento NO registrado: %s", _e)
    return partido_actualizado, ""


def borrar_partido(lid: str, partido_ref: str, usuario: str = "") -> tuple[bool, str]:
    saldo_previo = 0.0
    coste_previo = None
    fecha_previa = ""
    with jsonstore.store().tx():
        data = cargar()
        idx, item = buscar_lana(lid)
        if idx is None:
            return False, f"variante {lid!r} no existe"
        partidos = item.get("partidos") or []
        pi = next((i for i, p in enumerate(partidos)
                   if p.get("partido") == partido_ref), -1)
        if pi < 0:
            return False, f"partido {partido_ref!r} no existe"
        saldo_previo = float(partidos[pi].get("kg") or 0)
        coste_previo = partidos[pi].get("coste_kg")
        fecha_previa = partidos[pi].get("fecha_entrada") or ""
        del partidos[pi]
        item["total_kg"] = round(sum(p.get("kg") or 0 for p in partidos), 2)
        _guardar(data)

    mi = _movs()
    if mi:
        try:
            mi.registrar(lana_id=lid, lote=partido_ref, tipo="borrado",
                         cantidad_kg=-saldo_previo, saldo_anterior_kg=saldo_previo,
                         saldo_nuevo_kg=0, coste_kg=coste_previo,
                         fecha_entrada=fecha_previa, usuario=usuario)
        except Exception as _e:
            # El inventario YA se guardo; que el historico falle no debe
            # tumbar la operacion, pero el silencio total ocultaba la
            # divergencia inventario↔movimientos. Al menos, dejar log.
            _log.warning("inventario mutado pero movimiento NO registrado: %s", _e)
    return True, ""


def consumir_partido(lid: str, partido_ref: str, kg, usuario: str = "",
                     nota: str = "") -> tuple[dict | None, str]:
    """Salida atomica de kg de un partido. No toca coste ni fecha."""
    try:
        kg_f = float(kg)
        if not math.isfinite(kg_f):
            raise ValueError
    except (TypeError, ValueError):
        return None, "Cantidad invalida"
    if kg_f <= 0:
        return None, "La cantidad a consumir debe ser > 0"
    nota = (nota or "").strip()
    if len(nota) > 200:
        return None, "Nota demasiado larga (max 200 chars)"
    with jsonstore.store().tx():
        data = cargar()
        idx, item = buscar_lana(lid)
        if idx is None:
            return None, f"variante {lid!r} no existe"
        partidos = item.get("partidos") or []
        pi = next((i for i, p in enumerate(partidos)
                   if p.get("partido") == partido_ref), -1)
        if pi < 0:
            return None, f"partido {partido_ref!r} no existe"
        saldo_anterior = float(partidos[pi].get("kg") or 0)
        if kg_f > saldo_anterior + 1e-6:
            return None, (f"Saldo insuficiente: pides {kg_f:g} kg "
                          f"pero el partido solo tiene {saldo_anterior:g} kg")
        nuevo_saldo = round(saldo_anterior - kg_f, 4)
        coste_actual = partidos[pi].get("coste_kg")
        fecha_actual = partidos[pi].get("fecha_entrada") or ""
        partidos[pi]["kg"] = nuevo_saldo
        # Auto-marcar fecha_agotado si NO queda stock vivo TOTAL (almacen +
        # proveedor): un partido con kg reservados en el proveedor no esta
        # consumido, esta "en fabricacion" (mismo criterio que el resto).
        total_vivo = nuevo_saldo + float(partidos[pi].get("kg_proveedor") or 0)
        if total_vivo <= 0 and not partidos[pi].get("fecha_agotado"):
            partidos[pi]["fecha_agotado"] = datetime.now().date().isoformat()
        item["total_kg"] = round(sum(p.get("kg") or 0 for p in partidos), 2)
        _guardar(data)
        partido_actualizado = dict(partidos[pi])

    mi = _movs()
    if mi:
        try:
            mi.registrar(lana_id=lid, lote=partido_ref, tipo="salida",
                         cantidad_kg=-kg_f, saldo_anterior_kg=saldo_anterior,
                         saldo_nuevo_kg=nuevo_saldo, coste_kg=coste_actual,
                         fecha_entrada=fecha_actual, usuario=usuario, nota=nota)
        except Exception as _e:
            # El inventario YA se guardo; que el historico falle no debe
            # tumbar la operacion, pero el silencio total ocultaba la
            # divergencia inventario↔movimientos. Al menos, dejar log.
            _log.warning("inventario mutado pero movimiento NO registrado: %s", _e)
    return partido_actualizado, ""


def trasladar_kg_partido(lid: str, partido_ref: str, kg,
                         direccion: str, usuario: str = "",
                         nota: str = "") -> tuple[dict | None, str]:
    """Mueve `kg` entre las dos ubicaciones de un mismo partido:

      - direccion == "a-proveedor": resta de `kg` (almacen Rols) y suma a
        `kg_proveedor` (almacen del proveedor). Util cuando el proveedor
        te guarda parte de lo que ya tiene hilado, en vez de mandartelo
        todo de golpe.
      - direccion == "a-rols": resta de `kg_proveedor` y suma a `kg`
        (lo traes a tu almacen).

    El total del partido (kg + kg_proveedor) no varia con el traslado,
    asi que NO se llama `total_kg` ni cambia el saldo del catalogo. Solo
    se reparte entre las dos ubicaciones.

    Registra un movimiento de tipo "traslado" en el historico con el signo
    desde el punto de vista del almacen Rols (negativo si sale a proveedor,
    positivo si entra desde proveedor) para que se vea claro en la lista
    de movimientos.
    """
    if direccion not in ("a-proveedor", "a-rols"):
        return None, "direccion debe ser 'a-proveedor' o 'a-rols'"
    try:
        kg_f = _float_finito(kg)
    except (TypeError, ValueError):
        return None, "kg debe ser numerico"
    if kg_f <= 0:
        return None, "kg debe ser > 0"
    kg_f = round(kg_f, 2)
    nota = (nota or "").strip()
    if len(nota) > 200:
        return None, "Nota demasiado larga (max 200 chars)"

    with jsonstore.store().tx():
        data = cargar()
        idx, item = buscar_lana(lid)
        if idx is None:
            return None, f"variante {lid!r} no existe"
        partidos = item.get("partidos") or []
        pi = next((i for i, p in enumerate(partidos)
                   if p.get("partido") == partido_ref), -1)
        if pi < 0:
            return None, f"partido {partido_ref!r} no existe"
        prev = partidos[pi]
        kg_rols_prev = float(prev.get("kg") or 0)
        kg_prov_prev = float(prev.get("kg_proveedor") or 0)
        if direccion == "a-proveedor":
            if kg_f > kg_rols_prev + 1e-6:
                return None, (f"No puedes mover {kg_f:g} kg al proveedor: "
                              f"el partido solo tiene {kg_rols_prev:g} kg "
                              f"en almacen Rols")
            kg_rols_new = round(kg_rols_prev - kg_f, 2)
            kg_prov_new = round(kg_prov_prev + kg_f, 2)
        else:  # a-rols
            if kg_f > kg_prov_prev + 1e-6:
                return None, (f"No puedes traer {kg_f:g} kg del proveedor: "
                              f"el partido solo tiene {kg_prov_prev:g} kg "
                              f"en almacen del proveedor")
            kg_rols_new = round(kg_rols_prev + kg_f, 2)
            kg_prov_new = round(kg_prov_prev - kg_f, 2)
        partidos[pi]["kg"] = kg_rols_new
        partidos[pi]["kg_proveedor"] = kg_prov_new
        # Si el partido se queda sin nada en ningun lado, marcamos
        # fecha_agotado. Si vuelve a tener algo, la limpiamos.
        total_actual = kg_rols_new + kg_prov_new
        if total_actual <= 0 and not partidos[pi].get("fecha_agotado"):
            partidos[pi]["fecha_agotado"] = datetime.now().date().isoformat()
        elif total_actual > 0:
            partidos[pi]["fecha_agotado"] = None
        item["total_kg"] = round(sum(p.get("kg") or 0 for p in partidos), 2)
        _guardar(data)
        partido_actualizado = dict(partidos[pi])

    # Registramos en el historico con el signo desde el almacen Rols:
    # negativo si sale del almacen, positivo si entra.
    delta_rols = kg_rols_new - kg_rols_prev
    coste_actual = prev.get("coste_kg")
    fecha_actual = prev.get("fecha_entrada") or ""
    nota_auto = ("→ almacen proveedor"
                 if direccion == "a-proveedor"
                 else "← almacen proveedor")
    nota_final = f"{nota_auto}" + (f" · {nota}" if nota else "")
    mi = _movs()
    if mi:
        try:
            mi.registrar(lana_id=lid, lote=partido_ref, tipo="traslado",
                         cantidad_kg=delta_rols,
                         saldo_anterior_kg=kg_rols_prev,
                         saldo_nuevo_kg=kg_rols_new,
                         coste_kg=coste_actual,
                         fecha_entrada=fecha_actual,
                         usuario=usuario, nota=nota_final)
        except Exception as _e:
            # El inventario YA se guardo; que el historico falle no debe
            # tumbar la operacion, pero el silencio total ocultaba la
            # divergencia inventario↔movimientos. Al menos, dejar log.
            _log.warning("inventario mutado pero movimiento NO registrado: %s", _e)
    return partido_actualizado, ""


# ---------------------------------------------------------------------------
# Pedidos: persistencia del historico estructurado
# ---------------------------------------------------------------------------

def _siguiente_ref_pedido(data: dict) -> str:
    """Devuelve la siguiente ref de pedido global, formato PED-YYYYMMDD-NNN.
    Cuenta sobre todos los pedidos existentes del dia para incrementar."""
    hoy = datetime.now().strftime("%Y%m%d")
    prefijo = f"PED-{hoy}-"
    n = 0
    for l in data.get("lanas", []):
        for ped in (l.get("pedidos") or []):
            ref = ped.get("ref") or ""
            if ref.startswith(prefijo):
                try:
                    n = max(n, int(ref.split("-")[-1]))
                except ValueError:
                    pass
    return f"{prefijo}{n+1:03d}"


def registrar_pedido(lineas: list[dict], usuario: str = "",
                     nota: str = "") -> tuple[dict | None, str]:
    """Persiste un pedido en lana.pedidos[] de cada variante implicada.

    `lineas`: [{variante_id, kg, eur_kg?}].
    Devuelve {ref, fecha, proveedores: {prov: [{variante_id, kg, eur_kg, importe}]}}.

    Las lineas se agrupan internamente por proveedor para que el caller
    pueda generar 1 PDF por proveedor. La ref del pedido es la misma para
    todas las variantes que entran en este registro (asi puedes localizar
    todas las lineas del mismo pedido si lo necesitas mas tarde).
    """
    if not isinstance(lineas, list) or not lineas:
        return None, "lineas vacia"
    nota = (nota or "").strip()[:300]

    # Pre-validar todas las lineas y resolver variantes
    resueltas: list[tuple[dict, dict, float, float | None, str]] = []
    with jsonstore.store().tx():
        data = cargar()
        for ln in lineas:
            vid = (ln.get("variante_id") or "").strip()
            if not vid:
                return None, "cada linea necesita variante_id"
            try:
                kg = _float_finito(ln.get("kg") or 0)
            except (TypeError, ValueError):
                return None, f"kg invalido para {vid!r}"
            if kg <= 0:
                return None, f"kg debe ser > 0 (variante {vid!r})"
            eur = ln.get("eur_kg")
            if eur in (None, ""):
                eur = None
            else:
                try:
                    eur = _float_finito(eur)
                except (TypeError, ValueError):
                    return None, f"eur_kg invalido para {vid!r}"
            # Partido (opcional): el proveedor a veces lo confirma al
            # cursar, otras llega con la mercancia. Acepta string libre.
            partido = (ln.get("partido") or "").strip()
            if len(partido) > 40:
                return None, f"partido demasiado largo (max 40 chars) en {vid!r}"
            # Encontrar la variante
            item = None
            for l in data.get("lanas", []):
                if l.get("id") == vid or l.get("id_legacy") == vid:
                    item = l
                    break
            if item is None:
                return None, f"variante {vid!r} no existe"
            resueltas.append((ln, item, kg, eur, partido))

        # Generar ref unica y timestamp
        ref = _siguiente_ref_pedido(data)
        fecha = datetime.now().isoformat(timespec="seconds")

        # Persistir en cada variante implicada
        proveedores: dict[str, list[dict]] = {}
        for _ln, item, kg, eur, partido in resueltas:
            prov = item.get("proveedor") or ""
            importe = (kg * eur) if eur is not None else None
            registro = {
                "ref":               ref,
                "fecha":             fecha,
                "kg":                kg,
                "eur_kg":            eur,
                "importe":           round(importe, 2) if importe is not None else None,
                "partido_previsto":  partido or None,
                "estado":            "abierto",
                "usuario":           usuario,
                "nota":              nota,
            }
            item.setdefault("pedidos", []).append(registro)
            proveedores.setdefault(prov, []).append({
                "variante_id":      item.get("id"),
                "titulo":           item.get("titulo"),
                "tipo":             item.get("tipo"),
                "proveedor":        prov,
                "kg":               kg,
                "eur_kg":           eur,
                "importe":          registro["importe"],
                "partido_previsto": partido or None,
            })
        _guardar(data)

    return {"ref": ref, "fecha": fecha, "proveedores": proveedores}, ""


def _es_slug_valido(s: str) -> bool:
    """Valido si es un slug: a-z, 0-9 y guion. Sin espacios ni acentos.
    Lo usamos como salvaguarda generica para clasificacion / material /
    titulo — el catalogo (catalogo_materias) ya garantiza esto, pero
    asi tampoco aceptamos basura si alguien llama al endpoint a mano."""
    if not s:
        return False
    return bool(re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", s))


# Magic value: la unica clasificacion que activa el select "Material"
# en la UI. Lo mantenemos como constante por si el codigo necesita
# detectarlo (p.ej. para limpiar material_felpa cuando se cambia a
# basamentos / otros).
CLASIF_MATERIA_FELPA = "materia-felpa"


def actualizar_clasificacion_calidad(calidad_id: str, clasificacion: str,
                                     material_felpa: str | None = None
                                     ) -> tuple[dict | None, str]:
    """Asigna la clasificacion (y opcionalmente material_felpa) a TODAS
    las variantes de una calidad. Se mantiene consistente entre ellas:
    una calidad solo tiene una clasificacion.

    Los valores validos los gestiona el catalogo editable
    (catalogo_materias.json). Aqui solo validamos que sean slugs
    (a-z 0-9 guion) — no comprobamos contra una whitelist hardcoded
    para que los nuevos valores que el usuario anada al catalogo
    funcionen sin tener que tocar codigo.
    """
    clasificacion = (clasificacion or "").strip().lower()
    if not _es_slug_valido(clasificacion):
        return None, f"clasificacion invalida: {clasificacion!r}"
    if clasificacion == CLASIF_MATERIA_FELPA:
        material_felpa = (material_felpa or "").strip().lower() or None
        if material_felpa and not _es_slug_valido(material_felpa):
            return None, f"material_felpa invalido: {material_felpa!r}"
    else:
        # Solo aplica a felpa — los demas no llevan material
        material_felpa = None
    with jsonstore.store().tx():
        data = cargar()
        variantes = [v for v in data.get("lanas", [])
                     if v.get("calidad_id") == calidad_id]
        if not variantes:
            return None, f"calidad {calidad_id!r} no existe"
        for v in variantes:
            v["clasificacion"] = clasificacion
            v["material_felpa"] = material_felpa
        _guardar(data)
        return {
            "calidad_id":     calidad_id,
            "clasificacion":  clasificacion,
            "material_felpa": material_felpa,
            "n_variantes":    len(variantes),
        }, ""


def actualizar_titulo_calidad(calidad_id: str, titulo_nuevo: str
                              ) -> tuple[dict | None, str]:
    """Renombra el campo `titulo` en TODAS las variantes de una calidad.

    El id estable (`id` y `calidad_id`) NO cambia — esos se calcularon
    al crear la calidad y se guardan literalmente en el JSON, asi que
    cambiar el titulo afecta solo al display ("65/2C pais normal" →
    "100/2C pais normal"). Las referencias desde el escandallo de
    productos siguen funcionando porque van contra `calidad_id`.

    Devuelve {n_variantes_modificadas} o un error.
    """
    titulo_nuevo = (titulo_nuevo or "").strip()
    if len(titulo_nuevo) > 80:
        return None, "titulo demasiado largo (max 80)"
    # Sentinels de la UI ('__nuevo__', '__gestionar__'): jamas son un titulo
    # real. Defensa en profundidad — un bug del select llego a renombrar
    # una calidad a "__gestionar__".
    if titulo_nuevo.startswith("__") and titulo_nuevo.endswith("__"):
        return None, f"titulo invalido: {titulo_nuevo!r}"
    with jsonstore.store().tx():
        data = cargar()
        variantes = [v for v in data.get("lanas", [])
                     if v.get("calidad_id") == calidad_id]
        if not variantes:
            return None, f"calidad {calidad_id!r} no existe"
        for v in variantes:
            v["titulo"] = titulo_nuevo
            # Recomponer "nombre" display si existia (p.ej. "100 2/C PAIS NORMAL")
            # Solo si el campo existia, no lo creamos.
            if "nombre" in v:
                tipo = (v.get("tipo") or "").strip()
                v["nombre"] = f"{titulo_nuevo} {tipo}".strip().upper() or v.get("nombre")
        _guardar(data)
        return {
            "calidad_id":  calidad_id,
            "titulo":      titulo_nuevo,
            "n_variantes": len(variantes),
        }, ""


def actualizar_tipo_calidad(calidad_id: str, tipo_nuevo: str
                            ) -> tuple[dict | None, str]:
    """Renombra el campo `tipo` (nombre comercial de la calidad: "australia",
    "pais normal", "extra 80/20"...) en TODAS las variantes.

    Mismo principio que actualizar_titulo_calidad: el `calidad_id` y el
    `id` de cada variante NO cambian — solo se actualiza el display.
    Las referencias desde el escandallo de productos (que van por
    calidad_id) siguen funcionando.
    """
    tipo_nuevo = (tipo_nuevo or "").strip()
    if not tipo_nuevo:
        return None, "el nombre de la calidad no puede estar vacio"
    if len(tipo_nuevo) > 100:
        return None, "nombre demasiado largo (max 100)"
    with jsonstore.store().tx():
        data = cargar()
        variantes = [v for v in data.get("lanas", [])
                     if v.get("calidad_id") == calidad_id]
        if not variantes:
            return None, f"calidad {calidad_id!r} no existe"
        for v in variantes:
            v["tipo"] = tipo_nuevo
            # Recomponer "nombre" display si existia
            if "nombre" in v:
                titulo = (v.get("titulo") or "").strip()
                v["nombre"] = f"{titulo} {tipo_nuevo}".strip().upper() or v.get("nombre")
        _guardar(data)
        return {
            "calidad_id":  calidad_id,
            "tipo":        tipo_nuevo,
            "n_variantes": len(variantes),
        }, ""


def renombrar_proveedor_en_variantes(alias_viejo: str,
                                     alias_nuevo: str) -> int:
    """Renombra el campo `proveedor` en todas las variantes que usaban
    `alias_viejo`. Devuelve el numero de variantes actualizadas.

    Lo invoca proveedores.py cuando el usuario cambia el alias de un
    proveedor (cascada: las variantes guardan el alias literal en su
    campo `proveedor` por convencion historica).

    Vive en lanas_inventario.py — no en proveedores.py — para que use
    el `_lock` correcto, la escritura atomica (`_guardar` con
    `tmp.replace`) y la invalidacion de cache. Antes estaba en
    proveedores.py leyendo/escribiendo el JSON directamente sin lock,
    lo que era una bomba de tiempo si concurria con cualquier escritura
    de inventario.
    """
    n = 0
    with jsonstore.store().tx():
        data = cargar()
        for v in data.get("lanas", []):
            if (v.get("proveedor") or "").upper() == (alias_viejo or "").upper():
                v["proveedor"] = alias_nuevo
                # Recalcular el id de la variante para que sea coherente con
                # el nuevo alias. Guardamos el id viejo en id_legacy para
                # que buscar_lana siga resolviendo referencias antiguas
                # (escandallos, links guardados, movimientos historicos).
                cid = v.get("calidad_id") or ""
                prov_slug = _slug(alias_nuevo)
                nuevo_id = f"{cid}__{prov_slug}" if cid else _slug(f"{v.get('titulo','')} {v.get('tipo','')}") + f"__{prov_slug}"
                # No acunar ids DUPLICADOS: si otra variante ya tiene ese id
                # (misma calidad con un proveedor de texto libre homonimo),
                # conservamos el id actual — buscar_lana caeria siempre en
                # la primera y las ediciones irian a la variante equivocada.
                colision = any(o is not v and (o.get("id") == nuevo_id)
                               for o in data.get("lanas", []))
                if not colision:
                    if v.get("id"):
                        v.setdefault("id_legacy", v["id"])
                    v["id"] = nuevo_id
                n += 1
        if n:
            _guardar(data)
    return n


def variantes_con_proveedor(alias: str) -> list[dict]:
    """Devuelve la lista (resumida) de variantes cuyo `proveedor` coincide
    (case-insensitive) con `alias`. Util para que proveedores.py pueda
    chequear si un proveedor esta en uso antes de borrarlo, SIN abrir el
    JSON a mano. La cache de lanas_inventario garantiza consistencia."""
    items = []
    for v in cargar().get("lanas", []):
        if (v.get("proveedor") or "").upper() == (alias or "").upper():
            items.append({
                "id":         v.get("id"),
                "calidad_id": v.get("calidad_id") or "",
                "titulo":     v.get("titulo") or "",
                "tipo":       v.get("tipo") or "",
            })
    return items


def actualizar_planificacion_calidad(calidad_id: str, campo: str,
                                     valor) -> tuple[dict | None, str]:
    """Actualiza limite_kg o kg_a_pedir A NIVEL DE CALIDAD repartiendo
    el valor entre todas las variantes de esa calidad.

    Si hay 1 variante: se asigna entero.
    Si hay varias y todas tienen ya un valor previo > 0: se reparte
      proporcionalmente al peso actual.
    Si hay varias pero ninguna tiene valor: se reparte a partes iguales.

    Asi el usuario edita un solo numero "global" y la suma cuadra con
    lo que ve en la ficha, sin tocar las variantes manualmente.
    """
    if campo not in ("limite_kg", "kg_a_pedir"):
        return None, f"campo no editable: {campo!r}"
    try:
        nuevo = _float_finito(valor or 0)
    except (TypeError, ValueError):
        return None, f"{campo} debe ser numerico"
    if nuevo < 0:
        return None, f"{campo} no puede ser negativo"

    with jsonstore.store().tx():
        data = cargar()
        variantes = [l for l in data.get("lanas", [])
                     if l.get("calidad_id") == calidad_id]
        if not variantes:
            return None, f"calidad {calidad_id!r} no existe"
        if len(variantes) == 1:
            variantes[0][campo] = round(nuevo, 2)
        else:
            previos = [float(v.get(campo) or 0) for v in variantes]
            total_prev = sum(previos)
            if total_prev > 0:
                # Reparto proporcional al peso actual
                for v, prev in zip(variantes, previos):
                    v[campo] = round(nuevo * (prev / total_prev), 2)
            else:
                # Reparto a partes iguales
                cada = round(nuevo / len(variantes), 2)
                for v in variantes:
                    v[campo] = cada
        _guardar(data)
        return {
            "calidad_id": calidad_id,
            "campo":      campo,
            "total":      round(nuevo, 2),
            "reparto":    [{"id": v.get("id"), campo: v.get(campo)} for v in variantes],
        }, ""


def crear_calidad_placeholder(nombre: str, titulo: str = "",
                              material: str = "lana"
                              ) -> tuple[dict | None, str]:
    """Crea una calidad nueva con UNA variante placeholder (proveedor="").
    Pensado para el flujo "anadir nueva materia prima" donde el usuario
    solo introduce el nombre — la ficha resultante le pide rellenar
    proveedores, partidos, clasificacion, etc.

    Devuelve {calidad_id, variante_id} para que el caller pueda
    navegar a /materia-prima/<calidad_id>.
    """
    nombre = (nombre or "").strip()
    if not nombre:
        return None, "el nombre de la calidad es obligatorio"
    if len(nombre) > 100:
        return None, "nombre demasiado largo (max 100)"
    titulo = (titulo or "").strip()
    material = (material or "lana").strip()
    cid_calculado = (f"{_slug(titulo)}__{_slug(nombre)}"
                     if titulo else _slug(nombre))
    if not cid_calculado:
        return None, f"no puedo generar un id valido a partir de {nombre!r}"
    with jsonstore.store().tx():
        data = cargar()
        lanas = data.setdefault("lanas", [])
        # Comprobar que no existe ya una calidad con el mismo id
        for l in lanas:
            if l.get("calidad_id") == cid_calculado:
                return None, (f"ya existe una calidad con ese nombre "
                              f"({(titulo + ' ' + nombre).strip()}). Renombrala "
                              f"o usa un nombre distinto.")
        # Variante placeholder: proveedor vacio, sin partidos, sin
        # planificacion. El usuario lo rellena todo desde la ficha.
        vid = f"{cid_calculado}__"  # placeholder; al anadir el primer
                                     # proveedor se reemplazara la variante
        nueva = {
            "id":             vid,
            "calidad_id":     cid_calculado,
            "material":       material,
            "titulo":         titulo,
            "tipo":           nombre,
            "proveedor":      "",
            "clasificacion":  "",
            "material_felpa": "",
            "partidos":       [],
            "total_kg":       0,
            "limite_kg":      0,
            "kg_a_pedir":     0,
            "pedidos":        [],
            "observaciones":  "",
        }
        lanas.append(nueva)
        _guardar(data)
        return {"calidad_id": cid_calculado, "variante_id": vid}, ""


def anadir_proveedor_a_calidad(calidad_id: str, proveedor: str,
                               usuario: str = "") -> tuple[dict | None, str]:
    """Crea una variante nueva (sin partidos) para una calidad que ya
    existe, asociandola a un proveedor que aun no la suministra.

    Hereda titulo/tipo/material/seccion/categoria de una variante existente
    de la misma calidad. La planificacion (limite, kg_a_pedir, observaciones,
    precios) queda en blanco — el usuario la rellena en Compras si quiere.

    Devuelve (variante_nueva, '') o (None, error).
    """
    proveedor = (proveedor or "").strip()
    if not proveedor:
        return None, "el proveedor es obligatorio"
    if len(proveedor) > 80:
        return None, "proveedor demasiado largo"

    with jsonstore.store().tx():
        data = cargar()
        lanas = data.get("lanas") or []
        # Buscar la calidad: cualquier variante existente con ese calidad_id
        plantilla = None
        for l in lanas:
            if l.get("calidad_id") == calidad_id:
                plantilla = l
                break
        if not plantilla:
            return None, f"la calidad {calidad_id!r} no existe"

        # Verificar que no existe ya esa variante (mismo calidad+proveedor)
        prov_norm = proveedor.strip().upper()
        for l in lanas:
            if (l.get("calidad_id") == calidad_id and
                (l.get("proveedor") or "").strip().upper() == prov_norm):
                return None, f"la calidad ya tiene proveedor {proveedor!r}"

        # Para clasificacion / material_felpa cogemos la primera variante
        # de la calidad que los tenga (deberian ser iguales en todas, ya
        # que `actualizar_clasificacion_calidad` las setea en bloque). Si
        # ninguna tiene, se queda en blanco y el usuario lo asignara.
        clasif = ""
        material_felpa = ""
        for l in lanas:
            if l.get("calidad_id") != calidad_id:
                continue
            if not clasif and l.get("clasificacion"):
                clasif = l["clasificacion"]
            if not material_felpa and l.get("material_felpa"):
                material_felpa = l["material_felpa"]
            if clasif and material_felpa:
                break

        vid = f"{calidad_id}__{_slug(proveedor)}"
        nueva = {
            "id":          vid,
            "calidad_id":  calidad_id,
            "material":    plantilla.get("material") or "lana",
            "titulo":      plantilla.get("titulo") or "",
            "tipo":        plantilla.get("tipo") or "",
            "seccion":     plantilla.get("seccion") or "",
            "categoria":   plantilla.get("categoria") or "",
            "nombre":      plantilla.get("nombre") or "",
            "proveedor":   proveedor,
            "partidos":    [],
            "pedidos":     [],
            "total_kg":    0,
            "limite_kg":   0,
            "kg_a_pedir":  0,
            "pedido_hecho": "",
            "observaciones": "",
            # Heredamos la clasificacion de las variantes hermanas, para
            # que la calidad siga apareciendo en la tabla con su
            # clasificacion correcta aunque acabes de añadir el proveedor.
            "clasificacion":  clasif or None,
            "material_felpa": material_felpa or None,
            # Precios en blanco — el usuario los rellena al recibir
            # el primer partido o al cursar el primer pedido.
            "precio_2022":  None,
            "precio_2022b": None,
            "precio_2025":  None,
            "precio_2026":  None,
        }
        lanas.append(nueva)
        # Cleanup: si la calidad tenia una variante PLACEHOLDER
        # (proveedor=="" y sin partidos), la quitamos ahora que ya tiene
        # un proveedor real. Esto evita que la calidad se quede con
        # dos chips: el "(sin proveedor)" y el real.
        i = 0
        while i < len(lanas):
            l = lanas[i]
            if (l.get("calidad_id") == calidad_id
                    and not (l.get("proveedor") or "").strip()
                    and not (l.get("partidos") or [])):
                del lanas[i]
                continue
            i += 1
        _guardar(data)
        return nueva, ""


def quitar_proveedor_de_calidad(calidad_id: str, proveedor: str,
                                forzar: bool = False, usuario: str = ""
                                ) -> tuple[bool, str]:
    """Elimina la variante (calidad+proveedor) de la calidad indicada.

    Salvaguardas (saltables con forzar=True):
      - bloqueado si la variante aun tiene partidos con kg > 0 o
        kg_proveedor > 0 (perderia el inventario fisico/reservado).
      - bloqueado si tiene pedidos abiertos (en camino). Anula los
        pedidos primero o marca recibido.
      - bloqueado si es la UNICA variante de la calidad — quitarla
        haria desaparecer la calidad entera del listado. Si quieres
        eso, borra los partidos primero y la variante saldra cuando
        no quede nada.

    Con forzar=True saltamos las dos primeras (perdida de stock
    asumida por el usuario). La de "ultima variante" sigue bloqueada
    para evitar perder la calidad por accidente.
    """
    proveedor_norm = (proveedor or "").strip().upper()
    if not proveedor_norm:
        return False, "el proveedor es obligatorio"
    with jsonstore.store().tx():
        data = cargar()
        lanas = data.get("lanas") or []
        # Buscar la variante objetivo
        idx_objetivo = -1
        n_variantes_calidad = 0
        for i, l in enumerate(lanas):
            if l.get("calidad_id") == calidad_id:
                n_variantes_calidad += 1
                if (l.get("proveedor") or "").strip().upper() == proveedor_norm:
                    idx_objetivo = i
        if idx_objetivo < 0:
            return False, f"no existe variante {proveedor!r} en la calidad {calidad_id!r}"
        if n_variantes_calidad <= 1:
            return False, ("es la unica variante de la calidad — quitarla "
                           "haria desaparecer la calidad del listado. "
                           "Borra primero los partidos y la variante "
                           "desaparecera sola al no tener stock.")
        variante = lanas[idx_objetivo]
        partidos = variante.get("partidos") or []
        kg_vivo = sum((float(p.get("kg") or 0) + float(p.get("kg_proveedor") or 0))
                      for p in partidos)
        pedidos_abiertos = sum(
            1 for p in (variante.get("pedidos") or [])
            if (p.get("estado") or "").lower() == "abierto"
        )
        if not forzar:
            if kg_vivo > 0:
                return False, (f"la variante tiene {kg_vivo:.2f} kg en partidos "
                               f"activos (Rols + proveedor). Vacialos antes o "
                               f"usa forzar=true.")
            if pedidos_abiertos > 0:
                return False, (f"la variante tiene {pedidos_abiertos} pedido(s) "
                               f"abiertos. Marcalos como recibidos o anulalos "
                               f"antes, o usa forzar=true.")
        # Eliminar
        del lanas[idx_objetivo]
        _guardar(data)
    return True, ""


def borrar_calidad(calidad_id: str, forzar: bool = False,
                   usuario: str = "") -> tuple[bool, str]:
    """Borra una calidad entera: elimina TODAS las variantes con ese
    calidad_id. Pensado para limpiar calidades placeholder (creadas con
    solo el nombre y aun sin partidos) o calidades obsoletas.

    Salvaguardas (saltables con forzar=True):
      - bloqueado si CUALQUIER variante tiene partido con kg > 0 o
        kg_proveedor > 0. Borraria stock fisico sin trazabilidad.
      - bloqueado si CUALQUIER variante tiene pedido abierto (en
        camino). Anula los pedidos primero.

    Devuelve (True, '') o (False, error). Si forzar=True, registra un
    movimiento de tipo 'borrado' por cada partido eliminado.
    """
    with jsonstore.store().tx():
        data = cargar()
        lanas = data.setdefault("lanas", [])
        a_borrar = [i for i, l in enumerate(lanas)
                    if l.get("calidad_id") == calidad_id]
        if not a_borrar:
            return False, f"calidad {calidad_id!r} no existe"
        # Comprobar salvaguardas
        kg_vivo_total = 0.0
        pedidos_abiertos_total = 0
        for i in a_borrar:
            v = lanas[i]
            for p in (v.get("partidos") or []):
                kg_vivo_total += (float(p.get("kg") or 0)
                                  + float(p.get("kg_proveedor") or 0))
            for ped in (v.get("pedidos") or []):
                if (ped.get("estado") or "").lower() == "abierto":
                    pedidos_abiertos_total += 1
        if not forzar:
            if kg_vivo_total > 0:
                return False, (f"la calidad tiene {kg_vivo_total:.2f} kg en "
                               f"partidos activos (Rols + proveedor). Vacialos "
                               f"antes o usa forzar=true.")
            if pedidos_abiertos_total > 0:
                return False, (f"la calidad tiene {pedidos_abiertos_total} "
                               f"pedido(s) en camino. Marcalos como recibidos "
                               f"o anulalos antes.")
        # Registrar movimientos de borrado por partido (si se fuerza)
        movs_pendientes = []
        if forzar:
            for i in a_borrar:
                v = lanas[i]
                vid = v.get("id")
                for p in (v.get("partidos") or []):
                    kg = float(p.get("kg") or 0)
                    if kg > 0:
                        movs_pendientes.append({
                            "vid": vid,
                            "lote": p.get("partido") or "",
                            "kg": kg,
                            "coste_kg": p.get("coste_kg"),
                            "fecha_entrada": p.get("fecha_entrada") or "",
                        })
        # Borrar de mayor a menor indice para no descuadrar la lista
        for i in sorted(a_borrar, reverse=True):
            del lanas[i]
        _guardar(data)

    # Movimientos de auditoria (fuera del lock)
    if movs_pendientes:
        mi = _movs()
        if mi:
            for m in movs_pendientes:
                try:
                    mi.registrar(lana_id=m["vid"], lote=m["lote"],
                                 tipo="borrado", cantidad_kg=-m["kg"],
                                 saldo_anterior_kg=m["kg"], saldo_nuevo_kg=0,
                                 coste_kg=m["coste_kg"],
                                 fecha_entrada=m["fecha_entrada"],
                                 usuario=usuario,
                                 nota="borrado por borrar_calidad")
                except Exception as _e:
                    _log.warning("inventario mutado pero movimiento NO registrado: %s", _e)
    return True, ""


def actualizar_pedido(variante_id: str, ref_pedido: str,
                      campo: str, valor) -> tuple[dict | None, str]:
    """Actualiza un campo editable de un pedido concreto. Por ahora solo
    fecha_estimada_llegada (string ISO YYYY-MM-DD o vacio para limpiar)."""
    CAMPOS_OK = {"fecha_estimada_llegada", "partido_previsto"}
    if campo not in CAMPOS_OK:
        return None, f"campo no editable: {campo!r}"
    if isinstance(valor, str):
        valor = valor.strip() or None
    elif valor in (None, ""):
        valor = None
    with jsonstore.store().tx():
        data = cargar()
        idx, item = buscar_lana(variante_id)
        if idx is None:
            return None, f"variante {variante_id!r} no existe"
        target = None
        for p in (item.get("pedidos") or []):
            if p.get("ref") == ref_pedido:
                target = p
                break
        if not target:
            return None, f"pedido {ref_pedido!r} no encontrado en variante {variante_id!r}"
        target[campo] = valor
        _guardar(data)
        return {"variante_id": variante_id, "ref_pedido": ref_pedido,
                "campo": campo, "valor": valor}, ""


def _cambiar_estado_pedido(variante_id: str, ref_pedido: str,
                           estado_nuevo: str, usuario: str,
                           motivo: str = "") -> tuple[dict | None, str]:
    """Helper interno comun para marcar 'recibido' o 'anulado'. Pone el
    pedido en el estado nuevo + timestamp y limpia pedido_hecho legacy
    si la variante queda sin pedidos abiertos.

    Si ref_pedido es vacio, afecta a TODOS los pedidos abiertos de la
    variante (uso normal: la mercancia llega y cierras todo).
    """
    n_cerrados = 0
    campo_fecha = "fecha_recibido" if estado_nuevo == "recibido" else "fecha_anulado"
    campo_user = "recibido_por"   if estado_nuevo == "recibido" else "anulado_por"
    with jsonstore.store().tx():
        data = cargar()
        idx, item = buscar_lana(variante_id)
        if idx is None:
            return None, f"variante {variante_id!r} no existe"
        ahora = datetime.now().isoformat(timespec="seconds")
        for p in (item.get("pedidos") or []):
            if (p.get("estado") or "").lower() != "abierto":
                continue
            if ref_pedido and p.get("ref") != ref_pedido:
                continue
            p["estado"] = estado_nuevo
            p[campo_fecha] = ahora
            if usuario:
                p[campo_user] = usuario
            if motivo and estado_nuevo == "anulado":
                p["motivo_anulacion"] = motivo
            n_cerrados += 1
        # Sin coincidencias: salir SIN guardar (antes se commiteaba igual
        # la limpieza legacy aunque la llamada devolviera error).
        if n_cerrados == 0:
            return None, ("no habia pedidos abiertos para marcar como "
                          f"{estado_nuevo}"
                          + (f" (ref {ref_pedido!r})" if ref_pedido else ""))
        # Si ya no hay pedidos abiertos, limpiar la nota legacy
        sigue_abierto = any(
            (p.get("estado") or "").lower() == "abierto"
            for p in (item.get("pedidos") or [])
        )
        if not sigue_abierto and item.get("pedido_hecho"):
            item["pedido_hecho_legacy"] = item["pedido_hecho"]
            item["pedido_hecho"] = ""
        _guardar(data)
    return {
        "variante_id": variante_id,
        "ref_pedido":  ref_pedido or None,
        "n_cerrados":  n_cerrados,
        "estado":      estado_nuevo,
    }, ""


def marcar_pedido_recibido(variante_id: str, ref_pedido: str = "",
                           usuario: str = "",
                           kg_a_rols=None) -> tuple[dict | None, str]:
    """Marca pedidos abiertos como 'recibido' Y CREA UN PARTIDO FISICO
    en la variante por cada pedido cerrado, con los datos del pedido.

    Parametros:
      kg_a_rols: opcional, cuantos kg del pedido llegan al almacen Rols
                 (el resto se queda en almacen proveedor → kg_proveedor).
                 Si None (default), TODO va al almacen Rols (comportamiento
                 historico). Si se pasa N, el partido se crea con
                 kg=N y kg_proveedor=(pedido.kg - N).
                 Solo aplica cuando ref_pedido esta especificado (con
                 ref_pedido="" cerramos TODOS los abiertos y no tiene
                 sentido el split por uno solo).

    El nuevo partido lleva:
      - partido:        partido_previsto del pedido (si lo tenia y no es
                        un placeholder tipo 'TBC' / 'PENDIENTE'). Si no,
                        la ref del pedido (PED-...).
      - kg:             min(kg_a_rols, pedido.kg) — lo que llega aqui
      - kg_proveedor:   pedido.kg - kg (lo que se queda en proveedor)
      - kg_inicial:     pedido.kg (snapshot inmutable del total)
      - coste_kg:       pedido.eur_kg
      - fecha_compra:   pedido.fecha (cuando se curso el pedido)
      - fecha_entrada:  hoy (cuando llega al almacen)
      - observaciones:  "desde pedido <ref>"

    Si ref_pedido es vacio, cierra TODOS los pedidos abiertos de la
    variante y materializa cada uno como un partido fisico distinto
    (en este caso kg_a_rols se ignora — todo va a Rols).

    Hace TODO en una sola transaccion (cambio de estado + creacion
    del partido) para no materializar pedidos viejos que ya estaban
    en estado 'recibido' antes de esta funcionalidad.
    """
    PLACEHOLDERS = {"", "tbc", "pendiente", "por confirmar", "?"}
    partidos_creados = []
    n_cerrados = 0
    fecha_hoy = datetime.now().date().isoformat()
    ahora = datetime.now().isoformat(timespec="seconds")

    # Normalizar kg_a_rols
    if kg_a_rols is not None:
        try:
            kg_a_rols = _float_finito(kg_a_rols)
        except (TypeError, ValueError):
            return None, "kg_a_rols debe ser numerico"
        if kg_a_rols < 0:
            return None, "kg_a_rols no puede ser negativo"
        # Solo tiene sentido split cuando se especifica UN pedido concreto
        if not ref_pedido:
            return None, ("kg_a_rols requiere ref_pedido especifica "
                          "(no se puede splittear varios pedidos a la vez)")

    with jsonstore.store().tx():
        data = cargar()
        idx, item = buscar_lana(variante_id)
        if idx is None:
            return None, f"variante {variante_id!r} no existe"
        partidos = item.setdefault("partidos", [])
        # Iterar pedidos en estado 'abierto' (ojo: solo los abiertos —
        # los que ya estuvieran en 'recibido' antes no los tocamos).
        for ped in (item.get("pedidos") or []):
            if (ped.get("estado") or "").lower() != "abierto":
                continue
            if ref_pedido and ped.get("ref") != ref_pedido:
                continue
            # 1) Cambio de estado del pedido
            ped["estado"] = "recibido"
            ped["fecha_recibido"] = ahora
            if usuario:
                ped["recibido_por"] = usuario
            ped["ya_materializado"] = True
            n_cerrados += 1
            # 2) Crear partido fisico con los datos del pedido
            pp = (ped.get("partido_previsto") or "").strip()
            if pp.lower() in PLACEHOLDERS:
                pp = ""
            nombre_partido = pp or ped.get("ref") or "SIN-REF"
            # Evitar colision con partidos existentes
            existentes = {p.get("partido") for p in partidos}
            if nombre_partido in existentes:
                nombre_partido = f"{nombre_partido} ({ped.get('ref') or 'PED'})"
            kg_total = float(ped.get("kg") or 0)
            # Reparto Rols / proveedor segun kg_a_rols
            if kg_a_rols is not None:
                kg_rols = min(kg_a_rols, kg_total)
                kg_prov = max(0.0, kg_total - kg_rols)
            else:
                kg_rols = kg_total
                kg_prov = 0.0
            fecha_pedido = (ped.get("fecha") or "")[:10]  # ISO date
            obs = f"desde pedido {ped.get('ref') or ''}".strip()
            if kg_prov > 0:
                obs += f" · {kg_prov:.0f} kg quedan en proveedor".rstrip(" 0").rstrip(".")
            nuevo_partido = {
                "partido":        nombre_partido,
                "kg":             round(kg_rols, 2),
                "kg_inicial":     round(kg_total, 2),
                "kg_proveedor":   round(kg_prov, 2),
                "coste_kg":       ped.get("eur_kg"),
                "fecha_compra":   fecha_pedido or None,
                "fecha_entrada":  fecha_hoy,
                "fecha_agotado":  None,
                "estanteria":     None,
                "observaciones":  obs,
            }
            partidos.append(nuevo_partido)
            partidos_creados.append({
                "ref_pedido":   ped.get("ref"),
                "partido":      nombre_partido,
                "kg":           kg_rols,
                "kg_proveedor": kg_prov,
                "fecha_compra": fecha_pedido or None,
            })
        # Sin coincidencias: salir SIN guardar (antes se commiteaba igual
        # la limpieza legacy + recalculo aunque la llamada devolviera error).
        if n_cerrados == 0:
            return None, ("no habia pedidos abiertos para marcar como recibido"
                          + (f" (ref {ref_pedido!r})" if ref_pedido else ""))
        # Si ya no quedan pedidos abiertos, limpiar la nota legacy
        sigue_abierto = any(
            (p.get("estado") or "").lower() == "abierto"
            for p in (item.get("pedidos") or [])
        )
        if not sigue_abierto and item.get("pedido_hecho"):
            item["pedido_hecho_legacy"] = item["pedido_hecho"]
            item["pedido_hecho"] = ""
        item["total_kg"] = round(sum(p.get("kg") or 0 for p in partidos), 2)
        _guardar(data)

    # Registrar movimiento de entrada por cada partido creado
    mi = _movs()
    if mi:
        for pc in partidos_creados:
            try:
                mi.registrar(lana_id=variante_id, lote=pc["partido"],
                             tipo="entrada", cantidad_kg=pc["kg"],
                             saldo_anterior_kg=0, saldo_nuevo_kg=pc["kg"],
                             coste_kg=None, fecha_entrada=fecha_hoy,
                             usuario=usuario,
                             nota=f"recibido pedido {pc['ref_pedido'] or ''}".strip())
            except Exception as _e:
                _log.warning("inventario mutado pero movimiento NO registrado: %s", _e)

    return {
        "variante_id":      variante_id,
        "ref_pedido":       ref_pedido or None,
        "n_cerrados":       n_cerrados,
        "estado":           "recibido",
        "partidos_creados": partidos_creados,
    }, ""


def anular_pedido(variante_id: str, ref_pedido: str = "",
                  usuario: str = "", motivo: str = "") -> tuple[dict | None, str]:
    """Marca pedidos abiertos como 'anulado'. La variante vuelve a su
    estado natural (a pedir / bajo / ok) segun el stock real, porque
    deja de tener pedidos en estado 'abierto'."""
    return _cambiar_estado_pedido(variante_id, ref_pedido,
                                  estado_nuevo="anulado",
                                  usuario=usuario, motivo=motivo)


# ---------------------------------------------------------------------------
# CLI util para inspeccion
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys
    e = estadisticas()
    print(f"lanas_inventario.json @ {DATA_PATH}")
    print(f"  {e['n_total']} lanas totales — {e['n_pedir']} PEDIR · "
          f"{e['n_bajo']} bajo · {e['n_ok']} ok")
    print(f"  {e['total_kg']:,.0f} kg · valor estimado {e['valor_total_eur']:,.2f} €")
    if sys.argv[1:] and sys.argv[1] == "list":
        for l in listar_lanas():
            print(f"  [{_estado_fila(l):>5s}] {l['nombre']:<35s} "
                  f"{l['proveedor']:<10s} {l['total_kg']:>7.0f} kg")
