"""Rols One — Historico de movimientos de inventario.

Cada accion sobre un lote de materia prima (crear, editar, borrar)
deja un movimiento. Los movimientos son inmutables: una vez registrados
no se editan. Asi se puede auditar quien toco qué y cuando, y
reconstruir el saldo de un lote en cualquier punto del tiempo.

Tipos de movimiento:
- 'entrada': se crea un lote nuevo. cantidad_kg = cantidad inicial (positivo).
              saldo_anterior = 0; saldo_nuevo = cantidad inicial.
- 'ajuste' : se edita un lote existente. cantidad_kg = diferencia
              (puede ser positiva, negativa o cero si solo cambio
              coste/fecha). saldo_anterior y saldo_nuevo son los kg
              antes y despues del edit.
- 'salida' : se consume parte del lote (fabricacion, prueba, merma).
              cantidad_kg = -(kg consumidos). saldo_anterior > saldo_nuevo.
              Movimiento atomico: no toca coste ni fecha del lote.
- 'borrado': se borra un lote. cantidad_kg = -(saldo previo).
              saldo_anterior = saldo previo; saldo_nuevo = 0.

El JSON se guarda en shared/data/movimientos_inventario.json. Esquema:
{
  "_meta": { version_schema, creado_en, comentario },
  "movimientos": [
    {
      "id": "<uuid corto>",
      "timestamp": "2026-05-20T18:32:15",
      "lana_id": "65-2c__pais-normal",
      "lote": "L-2026-0042",
      "tipo": "entrada" | "ajuste" | "borrado",
      "cantidad_kg": 100.0,
      "saldo_anterior_kg": 0,
      "saldo_nuevo_kg": 100.0,
      "coste_kg": 5.20,
      "fecha_entrada": "2026-03-15",
      "usuario": "fernando",
      "nota": ""
    },
    ...
  ]
}
"""
from __future__ import annotations

import json
import threading
import secrets
from datetime import datetime
from functools import lru_cache
from pathlib import Path

import os

# Datos de runtime: en prod ROLS_DATA_DIR los fija FUERA del docroot (persisten,
# los deploys no los pisan); en local cae a shared/data como siempre.
DATA_PATH = Path(os.environ.get("ROLS_DATA_DIR") or Path(__file__).resolve().parent.parent / "data") / "movimientos_inventario.json"
_lock = threading.RLock()


@lru_cache(maxsize=1)
def _load_raw() -> dict:
    if not DATA_PATH.exists():
        return {"_meta": {"version_schema": 1}, "movimientos": []}
    return json.loads(DATA_PATH.read_text(encoding="utf-8"))


def invalidar_cache() -> None:
    _load_raw.cache_clear()


def cargar() -> dict:
    return _load_raw()


def _guardar(data: dict) -> None:
    DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = DATA_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(DATA_PATH)
    invalidar_cache()


# ---------------------------------------------------------------------------
# API publica
# ---------------------------------------------------------------------------

def registrar(
    lana_id: str, lote: str, tipo: str,
    cantidad_kg: float, saldo_anterior_kg: float, saldo_nuevo_kg: float,
    coste_kg: float | None = None,
    fecha_entrada: str = "",
    usuario: str = "",
    nota: str = "",
) -> dict:
    """Anade un movimiento al historico. Devuelve el movimiento creado.

    Se llama desde materias_primas.py despues de cada mutacion de lote.
    """
    # "traslado" = movimiento entre el almacen de Rols y el almacen del
    # proveedor (no afecta al saldo total del partido, solo a su reparto).
    if tipo not in ("entrada", "ajuste", "salida", "borrado", "traslado"):
        raise ValueError(f"tipo invalido: {tipo!r}")
    mov = {
        "id":                secrets.token_urlsafe(8),
        "timestamp":         datetime.now().isoformat(timespec="seconds"),
        "lana_id":           lana_id,
        "lote":              lote,
        "tipo":              tipo,
        "cantidad_kg":       round(float(cantidad_kg), 4),
        "saldo_anterior_kg": round(float(saldo_anterior_kg), 4),
        "saldo_nuevo_kg":    round(float(saldo_nuevo_kg), 4),
        "coste_kg":          round(float(coste_kg), 4) if coste_kg is not None else None,
        "fecha_entrada":     fecha_entrada or "",
        "usuario":           usuario or "",
        "nota":              nota or "",
    }
    with _lock:
        data = cargar()
        data.setdefault("movimientos", []).append(mov)
        _guardar(data)
    return mov


def listar(
    lana_id: str | None = None,
    lote: str | None = None,
    tipo: str | None = None,
    desde: str | None = None,
    hasta: str | None = None,
    limit: int | None = None,
) -> list[dict]:
    """Lista movimientos filtrados, ordenados por timestamp descendente
    (los mas recientes primero).

    desde / hasta: ISO date 'YYYY-MM-DD' o full ISO; comparacion lexica
    es suficiente porque el formato es estandar.
    """
    movs = list(cargar().get("movimientos", []))
    if lana_id:
        movs = [m for m in movs if m.get("lana_id") == lana_id]
    if lote:
        movs = [m for m in movs if m.get("lote") == lote]
    if tipo:
        movs = [m for m in movs if m.get("tipo") == tipo]
    if desde:
        movs = [m for m in movs if (m.get("timestamp") or "") >= desde]
    if hasta:
        # Si el usuario pasa 'YYYY-MM-DD', queremos incluir todo ese dia
        # asi que comparamos contra hasta + 'T23:59:59' para no cortar.
        hasta_full = hasta if "T" in hasta else hasta + "T23:59:59"
        movs = [m for m in movs if (m.get("timestamp") or "") <= hasta_full]
    movs.sort(key=lambda m: m.get("timestamp") or "", reverse=True)
    if limit and limit > 0:
        movs = movs[:limit]
    return movs
