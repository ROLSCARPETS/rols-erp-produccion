"""Rols One — lana en crudo (sin hilar).

Modelo paralelo a `lanas_inventario.py` pero para la lana que aun no
esta hilada. La lana en crudo vive siempre en el almacen de un hilador
(COBO, FILMURO…) y se "convierte" en una calidad hilada concreta
mediante una **orden de hilado**.

Conceptos:
- CONTENEDOR = unidad de trazabilidad de la lana cruda. Se compra
  por contenedor, con su €/kg, su fecha y su hilador destino.
- ORDEN DE HILADO = movimiento que consume kg de uno o varios
  contenedores y crea un PARTIDO en una calidad hilada (en
  `lanas_inventario.json`). Calcula el coste ponderado del partido
  combinando el coste del crudo + tarifa de hilado.

JSON en `shared/data/lana_cruda.json`. Esquema:
{
  "_meta": {...},
  "contenedores": [
    {
      "id": "cont-2026-001",                    # slug estable
      "ref": "CONT-2026-001",                   # display (lo pone el user)
      "hilador_actual": "COBO",                 # donde vive ahora
      "kg_inicial": 24000.0,
      "kg_actual":  18500.0,                    # restante sin hilar
      "coste_kg":   3.80,                       # €/kg crudo
      "fecha_compra":         "2026-04-15",
      "fecha_llegada_hilador":"2026-05-02",
      "proveedor_origen":     "ABC Wool Ltd",   # informativo
      "observaciones":        "",
      "fecha_creacion":       "..."
    }
  ],
  "movimientos_hilado": [
    {
      "id":                 "hil-...",
      "timestamp":          "...",
      "contenedores_origen":[{"contenedor_id":"...", "kg": 1000}, ...],
      "calidad_destino_id": "65-2c__pais-normal",
      "hilador":            "COBO",
      "variante_destino_id":"65-2c__pais-normal__cobo",
      "partido_creado":     "4923C",
      "kg_crudo_total":     1000.0,
      "kg_hilado":          970.0,
      "merma_kg":           30.0,
      "merma_pct":          3.0,
      "coste_crudo_eur":    3800.0,             # crudo_kg * crudo_€/kg ponderado
      "tarifa_hilado_eur_kg":1.20,
      "coste_hilado_eur":   1164.0,             # tarifa * kg_hilado
      "coste_total_eur":    4964.0,
      "coste_kg_partido":   5.12,
      "usuario":            "...",
      "nota":               ""
    }
  ]
}
"""
from __future__ import annotations

import json
import re
import secrets
import threading
import unicodedata
from datetime import datetime
from functools import lru_cache
from pathlib import Path

import os

# Datos de runtime: en prod ROLS_DATA_DIR los fija FUERA del docroot (persisten,
# los deploys no los pisan); en local cae a shared/data como siempre.
import jsonstore  # BD SQLite transaccional (sustituye JSON+RLock)

# Ruta del JSON LEGACY: solo para la migración one-time a SQLite (queda de backup).
DATA_PATH = Path(os.environ.get("ROLS_DATA_DIR") or Path(__file__).resolve().parent.parent / "data") / "lana_cruda.json"
_lock = threading.RLock()  # (histórico; los `with jsonstore.store().tx():` ahora son transacciones)
_KEY = "lana_cruda"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _slug(s: str) -> str:
    if not s:
        return ""
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.lower().strip()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-")


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _id_contenedor(ref: str) -> str:
    """Slug estable del contenedor. Si la ref viene vacia (no deberia),
    generamos un id aleatorio para no colisionar."""
    base = _slug(ref)
    return base or f"cont-{secrets.token_urlsafe(6).lower()}"


def _id_orden_hilado() -> str:
    return f"hil-{secrets.token_urlsafe(8).lower()}"


# ---------------------------------------------------------------------------
# Persistencia
# ---------------------------------------------------------------------------

def _default() -> dict:
    return {
        "_meta":               {"version_schema": 1},
        "contenedores":        [],
        "movimientos_hilado":  [],
    }


def invalidar_cache() -> None:
    pass  # SQLite se lee fresco; no-op por compat


def cargar() -> dict:
    return jsonstore.store().load(_KEY, _default, DATA_PATH)


def _guardar(data: dict) -> None:
    data.setdefault("_meta", {})
    data["_meta"]["actualizado_en"] = _now_iso()
    jsonstore.store().save(_KEY, data)


# ---------------------------------------------------------------------------
# Lazy import del modulo de lanas (evita ciclos en el bootstrap)
# ---------------------------------------------------------------------------

def _lanas_inv():
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import lanas_inventario as _li
    return _li


def _movs():
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import movimientos_inventario as _mi
    return _mi


# ---------------------------------------------------------------------------
# Lectura
# ---------------------------------------------------------------------------

def listar_contenedores(incluir_agotados: bool = True) -> list[dict]:
    """Lista de contenedores. Por defecto incluye agotados (kg_actual=0)
    porque el historial de compras tiene valor de auditoria."""
    items = list(cargar().get("contenedores") or [])
    if not incluir_agotados:
        items = [c for c in items if float(c.get("kg_actual") or 0) > 0]
    # Orden por fecha_compra desc (mas recientes arriba); fallback a id.
    items.sort(
        key=lambda c: (c.get("fecha_compra") or "", c.get("id") or ""),
        reverse=True,
    )
    return items


def contenedor_por_id(cid: str) -> dict | None:
    cid = (cid or "").strip()
    if not cid:
        return None
    for c in cargar().get("contenedores") or []:
        if c.get("id") == cid:
            return c
    return None


def listar_movimientos_hilado(contenedor_id: str | None = None,
                              variante_id: str | None = None,
                              limit: int | None = None) -> list[dict]:
    """Historico de ordenes de hilado, mas recientes primero."""
    movs = list(cargar().get("movimientos_hilado") or [])
    if contenedor_id:
        movs = [m for m in movs
                if any((o.get("contenedor_id") == contenedor_id)
                       for o in (m.get("contenedores_origen") or []))]
    if variante_id:
        movs = [m for m in movs if m.get("variante_destino_id") == variante_id]
    movs.sort(key=lambda m: m.get("timestamp") or "", reverse=True)
    if limit and limit > 0:
        movs = movs[:limit]
    return movs


def estadisticas() -> dict:
    """KPIs para la cabecera del tab "Lana en crudo":
    - kg_total: suma de kg_actual de todos los contenedores
    - kg_inicial_total: suma de kg_inicial (para % consumido)
    - n_contenedores_activos: con kg_actual > 0
    - por_hilador: {hilador: {kg, n_contenedores}}
    - valor_eur: kg_actual * coste_kg sumado
    """
    contenedores = listar_contenedores()
    kg_total = 0.0
    kg_inicial_total = 0.0
    valor_total = 0.0
    n_activos = 0
    por_hilador: dict[str, dict] = {}
    for c in contenedores:
        kg = float(c.get("kg_actual") or 0)
        kg_ini = float(c.get("kg_inicial") or 0)
        coste = float(c.get("coste_kg") or 0)
        # Si el contenedor todavia no tiene hilador asignado, lo agrupamos
        # bajo "Sin asignar" en los KPIs. El usuario lo decidira al hilar.
        hil = (c.get("hilador_actual") or "").strip() or "Sin asignar"
        kg_total += kg
        kg_inicial_total += kg_ini
        valor_total += kg * coste
        if kg > 0:
            n_activos += 1
        slot = por_hilador.setdefault(hil, {"kg": 0.0, "n_contenedores": 0})
        slot["kg"] += kg
        if kg > 0:
            slot["n_contenedores"] += 1
    return {
        "kg_total":              round(kg_total, 2),
        "kg_inicial_total":      round(kg_inicial_total, 2),
        "valor_eur":             round(valor_total, 2),
        "n_contenedores_total":  len(contenedores),
        "n_contenedores_activos": n_activos,
        "por_hilador":           {k: {"kg": round(v["kg"], 2),
                                       "n_contenedores": v["n_contenedores"]}
                                   for k, v in por_hilador.items()},
    }


# ---------------------------------------------------------------------------
# CRUD contenedores
# ---------------------------------------------------------------------------

def crear_contenedor(ref: str, hilador_actual: str, kg_inicial,
                     coste_kg, fecha_compra: str = "",
                     fecha_llegada_hilador: str = "",
                     proveedor_origen: str = "",
                     observaciones: str = "",
                     usuario: str = "") -> tuple[dict | None, str]:
    """Registra un contenedor nuevo de lana en crudo.

    El id se deriva de `ref` (slug). Si ya existe un contenedor con esa
    ref, se rechaza para evitar duplicados; el usuario debera usar otra
    ref o editar el existente.
    """
    ref = (ref or "").strip()
    if not ref:
        return None, "la ref del contenedor es obligatoria"
    if len(ref) > 80:
        return None, "ref demasiado larga (max 80)"
    # Hilador opcional: el contenedor puede existir sin asignarse a un
    # hilador concreto todavia (se decide al ejecutar la orden de hilado).
    hil = (hilador_actual or "").strip()
    try:
        kg_f = float(kg_inicial)
    except (TypeError, ValueError):
        return None, "kg_inicial debe ser numerico"
    if kg_f <= 0:
        return None, "kg_inicial debe ser > 0"
    try:
        coste_f = float(coste_kg)
    except (TypeError, ValueError):
        return None, "coste_kg debe ser numerico"
    if coste_f < 0:
        return None, "coste_kg no puede ser negativo"

    cid = _id_contenedor(ref)
    nuevo = {
        "id":                    cid,
        "ref":                   ref,
        "hilador_actual":        hil,
        "kg_inicial":            round(kg_f, 2),
        "kg_actual":             round(kg_f, 2),
        "coste_kg":              round(coste_f, 4),
        "fecha_compra":          (fecha_compra or "").strip() or None,
        "fecha_llegada_hilador": (fecha_llegada_hilador or "").strip() or None,
        "proveedor_origen":      (proveedor_origen or "").strip() or "",
        "observaciones":         (observaciones or "").strip()[:300] or "",
        "fecha_creacion":        _now_iso(),
        "creado_por":            usuario or "",
    }
    with jsonstore.store().tx():
        data = cargar()
        contenedores = data.setdefault("contenedores", [])
        if any(c.get("id") == cid or c.get("ref") == ref
               for c in contenedores):
            return None, f"ya existe un contenedor con ref {ref!r}"
        contenedores.append(nuevo)
        _guardar(data)
    return nuevo, ""


def actualizar_contenedor(cid: str, datos: dict,
                          usuario: str = "") -> tuple[dict | None, str]:
    """Edita campos editables de un contenedor. Campos permitidos:
    ref, hilador_actual, coste_kg, fecha_compra, fecha_llegada_hilador,
    proveedor_origen, observaciones.

    `kg_inicial` y `kg_actual` NO son editables aqui — se mueven solo
    via hilar() o via ajuste explicito (no implementado todavia).
    """
    if not isinstance(datos, dict):
        return None, "datos debe ser un objeto"
    EDITABLES = {"ref", "hilador_actual", "coste_kg", "fecha_compra",
                 "fecha_llegada_hilador", "proveedor_origen",
                 "observaciones"}
    with jsonstore.store().tx():
        data = cargar()
        contenedores = data.get("contenedores") or []
        idx = next((i for i, c in enumerate(contenedores)
                    if c.get("id") == cid), -1)
        if idx < 0:
            return None, f"contenedor {cid!r} no existe"
        c = contenedores[idx]
        for k, v in datos.items():
            if k not in EDITABLES:
                continue
            if k == "coste_kg":
                if v in (None, ""):
                    c["coste_kg"] = 0.0
                else:
                    try:
                        c["coste_kg"] = round(float(v), 4)
                    except (TypeError, ValueError):
                        return None, "coste_kg debe ser numerico"
            elif k == "ref":
                ref = (v or "").strip()
                if not ref:
                    return None, "la ref no puede quedar vacia"
                # Evitar colision con otros contenedores
                if any(j != idx and o.get("ref") == ref
                       for j, o in enumerate(contenedores)):
                    return None, f"ya existe otro contenedor con ref {ref!r}"
                c["ref"] = ref
            elif k in ("fecha_compra", "fecha_llegada_hilador"):
                c[k] = (v or "").strip() or None
            elif k == "observaciones":
                c[k] = (v or "").strip()[:300]
            else:
                c[k] = (v or "").strip() if isinstance(v, str) else v
        c["actualizado_en"] = _now_iso()
        if usuario:
            c["actualizado_por"] = usuario
        _guardar(data)
        return c, ""


def borrar_contenedor(cid: str, forzar: bool = False,
                      usuario: str = "") -> tuple[bool, str]:
    """Borra un contenedor entero. Bloqueado si kg_actual > 0 (es stock
    real); con forzar=True se borra de todos modos y se registra un
    movimiento de hilado tipo `borrado-contenedor` para auditoria.
    """
    with jsonstore.store().tx():
        data = cargar()
        contenedores = data.get("contenedores") or []
        idx = next((i for i, c in enumerate(contenedores)
                    if c.get("id") == cid), -1)
        if idx < 0:
            return False, f"contenedor {cid!r} no existe"
        c = contenedores[idx]
        kg = float(c.get("kg_actual") or 0)
        if kg > 0 and not forzar:
            return False, (f"el contenedor tiene {kg:.0f} kg sin hilar. "
                           f"Hilalo o usa forzar=true.")
        if forzar and kg > 0:
            # Auditoria: dejamos rastro del borrado en movimientos_hilado.
            data.setdefault("movimientos_hilado", []).append({
                "id":         _id_orden_hilado(),
                "timestamp":  _now_iso(),
                "tipo":       "borrado-contenedor",
                "contenedor_id":  cid,
                "ref":            c.get("ref"),
                "kg_borrados":    round(kg, 2),
                "coste_kg":       c.get("coste_kg"),
                "usuario":        usuario or "",
                "nota":           "borrado forzado de contenedor con stock",
            })
        del contenedores[idx]
        _guardar(data)
        return True, ""


# ---------------------------------------------------------------------------
# Flujo de hilado en 2 pasos: APARTAR (kg crudo) y CERRAR (kg hilado real)
#
# 1. apartar_para_hilar() — al decidir hilar, apartas X kg de uno o varios
#    contenedores y declaras la calidad+hilador destino. La orden queda en
#    estado "pendiente"; los kg de crudo se descuentan ya (estan
#    reservados / fisicamente en el hilador hilandose). Aun NO se crea el
#    partido en lanas_inventario porque no sabes cuantos kg hilados van a
#    salir ni la tarifa exacta.
#
# 2. cerrar_orden_hilado() — cuando recibes el partido y el hilador
#    factura, introduces kg_hilado reales + tarifa €/kg + ref del partido.
#    Se calcula el coste ponderado y se crea el partido en la calidad
#    hilada. La orden pasa a estado "recibido".
# ---------------------------------------------------------------------------

def apartar_para_hilar(contenedores_consumo: list[dict],
                       calidad_destino_id: str,
                       hilador: str,
                       partido_ref: str = "",
                       fecha_orden: str = "",
                       usuario: str = "",
                       nota: str = "") -> tuple[dict | None, str]:
    """Aparta kg de crudo para hilar. Crea una orden en estado
    'pendiente'. NO crea aun el partido en lanas_inventario — eso espera
    a cerrar_orden_hilado() cuando lleguen los kg_hilado reales.

    Parametros:
    - contenedores_consumo: [{"contenedor_id": str, "kg": float}, ...]
    - calidad_destino_id: id de la calidad hilada destino.
    - hilador: el proveedor que hara el hilado.
    - partido_ref: opcional — la ref del partido nuevo se puede dejar
      vacia y rellenarse al cerrar la orden (cuando el hilador la asigne).
    - fecha_orden: fecha en que se aparta (default: hoy).

    Atomicidad: dentro del lock se hacen las dos cosas (descontar kg +
    crear orden). Si la calidad destino no existe, rollback de los kg.
    """
    # Validar
    if not isinstance(contenedores_consumo, list) or not contenedores_consumo:
        return None, "indica al menos un contenedor a consumir"
    calidad_destino_id = (calidad_destino_id or "").strip()
    if not calidad_destino_id:
        return None, "calidad_destino_id es obligatorio"
    hilador = (hilador or "").strip()
    if not hilador:
        return None, "hilador es obligatorio"

    # Normalizar consumos
    consumos_norm: list[dict] = []
    for it in contenedores_consumo:
        cid_ = (it.get("contenedor_id") or "").strip()
        try:
            kg_c = float(it.get("kg") or 0)
        except (TypeError, ValueError):
            return None, f"kg consumidos de {cid_!r} debe ser numerico"
        if not cid_ or kg_c <= 0:
            return None, "cada consumo necesita contenedor_id y kg > 0"
        consumos_norm.append({"contenedor_id": cid_, "kg": kg_c})
    kg_crudo_total = sum(it["kg"] for it in consumos_norm)

    # Verificar saldo + descontar + crear orden
    coste_crudo_eur = 0.0
    snapshots_prev: dict[str, float] = {}
    with jsonstore.store().tx():
        data = cargar()
        contenedores = data.get("contenedores") or []
        cid_to_idx = {c.get("id"): i for i, c in enumerate(contenedores)}
        for it in consumos_norm:
            cid_ = it["contenedor_id"]
            if cid_ not in cid_to_idx:
                return None, f"contenedor {cid_!r} no existe"
            c = contenedores[cid_to_idx[cid_]]
            kg_disp = float(c.get("kg_actual") or 0)
            if it["kg"] > kg_disp + 0.001:
                return None, (f"contenedor {c.get('ref')}: pides {it['kg']} kg "
                              f"pero solo tiene {kg_disp:.2f} kg disponibles")
            coste_crudo_eur += it["kg"] * float(c.get("coste_kg") or 0)
            snapshots_prev[cid_] = kg_disp

        # Resolver variante destino (la creamos si no existe)
        variante_id, err = _resolver_o_crear_variante_destino(
            calidad_destino_id, hilador, usuario=usuario)
        if err:
            return None, err

        # Descontar kg de cada contenedor
        for it in consumos_norm:
            c = contenedores[cid_to_idx[it["contenedor_id"]]]
            c["kg_actual"] = round(float(c["kg_actual"]) - it["kg"], 2)

        orden = {
            "id":                   _id_orden_hilado(),
            "timestamp":            _now_iso(),
            "estado":               "pendiente",
            "fecha_orden":          (fecha_orden or "").strip() or _now_iso()[:10],
            "contenedores_origen":  consumos_norm,
            "calidad_destino_id":   calidad_destino_id,
            "hilador":              hilador,
            "variante_destino_id":  variante_id,
            "partido_creado":       (partido_ref or "").strip(),
            "kg_crudo_total":       round(kg_crudo_total, 2),
            "coste_crudo_eur":      round(coste_crudo_eur, 2),
            # Campos que se rellenan al cerrar la orden:
            "kg_hilado":            None,
            "merma_kg":             None,
            "merma_pct":            None,
            "tarifa_hilado_eur_kg": None,
            "coste_hilado_eur":     None,
            "coste_total_eur":      None,
            "coste_kg_partido":     None,
            "fecha_recibido":       None,
            "usuario":              usuario or "",
            "nota":                 (nota or "").strip(),
        }
        data.setdefault("movimientos_hilado", []).append(orden)
        _guardar(data)
    return orden, ""


def cerrar_orden_hilado(orden_id: str, kg_hilado, tarifa_hilado_eur_kg,
                        partido_ref: str = "",
                        fecha_recibido: str = "",
                        usuario: str = "") -> tuple[dict | None, str]:
    """Cierra una orden pendiente: registra los kg_hilado reales que
    salieron, la tarifa €/kg final, y crea el partido en la calidad
    hilada via lanas_inventario.agregar_partido.

    El coste_kg del partido se calcula como:
        (coste_crudo_eur + kg_hilado * tarifa_hilado_eur_kg) / kg_hilado

    Parametros:
    - orden_id: id de la orden pendiente.
    - kg_hilado: kg reales que produjo el hilado (<= kg_crudo_total;
      la diferencia es merma).
    - tarifa_hilado_eur_kg: €/kg final que cobra el hilador.
    - partido_ref: ref del partido. Si la orden ya tenia una preasignada,
      este parametro puede ir vacio y se usa la guardada; si tampoco
      habia, este es obligatorio aqui.
    - fecha_recibido: fecha en que llego el partido (default: hoy).
    """
    # Validar
    try:
        kg_hilado_f = float(kg_hilado)
    except (TypeError, ValueError):
        return None, "kg_hilado debe ser numerico"
    if kg_hilado_f <= 0:
        return None, "kg_hilado debe ser > 0"
    try:
        tarifa_f = float(tarifa_hilado_eur_kg or 0)
    except (TypeError, ValueError):
        return None, "tarifa_hilado_eur_kg debe ser numerico"
    if tarifa_f < 0:
        return None, "tarifa_hilado_eur_kg no puede ser negativa"

    with jsonstore.store().tx():
        data = cargar()
        movs = data.get("movimientos_hilado") or []
        idx = next((i for i, m in enumerate(movs) if m.get("id") == orden_id), -1)
        if idx < 0:
            return None, f"orden {orden_id!r} no existe"
        orden = movs[idx]
        if orden.get("estado") != "pendiente":
            return None, (f"la orden {orden_id!r} no esta pendiente "
                          f"(estado actual: {orden.get('estado')!r})")
        kg_crudo = float(orden.get("kg_crudo_total") or 0)
        if kg_hilado_f > kg_crudo + 0.001:
            return None, (f"kg_hilado ({kg_hilado_f}) no puede ser mayor que "
                          f"el crudo apartado ({kg_crudo})")
        # Partido ref: usar el del cierre, o el preasignado
        partido_ref = (partido_ref or "").strip() or (orden.get("partido_creado") or "").strip()
        if not partido_ref:
            return None, "partido_ref es obligatorio (no se preasigno al apartar)"

        # Calcular cifras
        coste_crudo_eur = float(orden.get("coste_crudo_eur") or 0)
        coste_hilado_eur = round(kg_hilado_f * tarifa_f, 2)
        coste_total_eur = round(coste_crudo_eur + coste_hilado_eur, 2)
        coste_kg_partido = round(coste_total_eur / kg_hilado_f, 4) if kg_hilado_f else None
        merma_kg = round(kg_crudo - kg_hilado_f, 2)
        merma_pct = round((merma_kg / kg_crudo) * 100, 2) if kg_crudo else 0.0

        # Actualizar orden
        orden["estado"] = "recibido"
        orden["kg_hilado"] = round(kg_hilado_f, 2)
        orden["merma_kg"] = merma_kg
        orden["merma_pct"] = merma_pct
        orden["tarifa_hilado_eur_kg"] = round(tarifa_f, 4)
        orden["coste_hilado_eur"] = coste_hilado_eur
        orden["coste_total_eur"] = coste_total_eur
        orden["coste_kg_partido"] = coste_kg_partido
        orden["fecha_recibido"] = (fecha_recibido or "").strip() or _now_iso()[:10]
        orden["partido_creado"] = partido_ref
        if usuario:
            orden["cerrado_por"] = usuario
        _guardar(data)

    # Crear el partido en lanas_inventario (fuera del lock)
    li = _lanas_inv()
    refs_origen = ", ".join(
        (contenedor_por_id(c["contenedor_id"]) or {}).get("ref") or c["contenedor_id"]
        for c in (orden.get("contenedores_origen") or [])
    )
    obs_partido = (f"Hilado de {refs_origen}" +
                   (f" — merma {merma_pct:.1f}%" if merma_pct else ""))
    _, err_part = li.agregar_partido(
        orden["variante_destino_id"], partido_ref=partido_ref,
        kg=kg_hilado_f, coste_kg=coste_kg_partido,
        fecha_entrada=orden["fecha_recibido"], usuario=usuario,
        observaciones=obs_partido,
    )
    if err_part:
        # Revertir el estado de la orden (los kg ya estan descontados
        # del crudo desde el apartado — eso se mantiene).
        with jsonstore.store().tx():
            data = cargar()
            movs = data.get("movimientos_hilado") or []
            idx = next((i for i, m in enumerate(movs) if m.get("id") == orden_id), -1)
            if idx >= 0:
                o = movs[idx]
                o["estado"] = "pendiente"
                for k in ("kg_hilado", "merma_kg", "merma_pct",
                          "tarifa_hilado_eur_kg", "coste_hilado_eur",
                          "coste_total_eur", "coste_kg_partido",
                          "fecha_recibido"):
                    o[k] = None
                _guardar(data)
        return None, f"no se pudo crear el partido hilado: {err_part}"
    return orden, ""


def anular_orden_hilado(orden_id: str, motivo: str = "",
                        usuario: str = "") -> tuple[dict | None, str]:
    """Anula una orden pendiente y devuelve los kg al(los) contenedor(es)
    de origen. Solo aplica a ordenes en estado 'pendiente'."""
    motivo = (motivo or "").strip()
    with jsonstore.store().tx():
        data = cargar()
        movs = data.get("movimientos_hilado") or []
        idx = next((i for i, m in enumerate(movs) if m.get("id") == orden_id), -1)
        if idx < 0:
            return None, f"orden {orden_id!r} no existe"
        orden = movs[idx]
        if orden.get("estado") != "pendiente":
            return None, f"solo se pueden anular ordenes pendientes ({orden.get('estado')!r})"
        # Devolver kg a los contenedores
        contenedores = data.get("contenedores") or []
        cid_to_idx = {c.get("id"): i for i, c in enumerate(contenedores)}
        for it in (orden.get("contenedores_origen") or []):
            ci = cid_to_idx.get(it.get("contenedor_id"))
            if ci is None:
                continue   # contenedor ya borrado; no podemos devolver, dejamos rastro
            contenedores[ci]["kg_actual"] = round(
                float(contenedores[ci]["kg_actual"]) + float(it.get("kg") or 0), 2)
        orden["estado"] = "anulado"
        orden["motivo_anulacion"] = motivo or "anulada por usuario"
        orden["fecha_anulado"] = _now_iso()[:10]
        if usuario:
            orden["anulado_por"] = usuario
        _guardar(data)
        return orden, ""


def _resolver_o_crear_variante_destino(calidad_id: str, hilador: str,
                                       usuario: str = "") -> tuple[str | None, str]:
    """Devuelve el variante_id (calidad+hilador). Si no existe la
    variante, la crea via lanas_inventario.anadir_proveedor_a_calidad.
    Si la calidad no existe en absoluto, devuelve error (no la creamos
    automaticamente — el usuario tiene que tenerla definida con su
    titulo/tipo desde Materias primas).
    """
    li = _lanas_inv()
    li.invalidar_cache()
    cal = li.calidad_por_id(calidad_id)
    if not cal:
        return None, (f"la calidad {calidad_id!r} no existe. Creala primero "
                      f"en Materias primas (con su titulo y nombre).")
    hil_norm = hilador.strip().upper()
    for v in cal.get("variantes") or []:
        if (v.get("proveedor") or "").strip().upper() == hil_norm:
            return v.get("id"), ""
    # No existe variante con ese hilador → la creamos
    nueva, err = li.anadir_proveedor_a_calidad(calidad_id, hilador,
                                                usuario=usuario)
    if err:
        return None, f"no se pudo crear la variante {calidad_id}+{hilador}: {err}"
    return nueva.get("id"), ""


# ---------------------------------------------------------------------------
# CLI de inspeccion
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    s = estadisticas()
    print(f"Lana en crudo: {s['kg_total']:.0f} kg en "
          f"{s['n_contenedores_activos']} contenedores activos.")
    for hil, info in s["por_hilador"].items():
        print(f"  {hil:10s}  {info['kg']:>8.0f} kg  ({info['n_contenedores']} cont.)")
