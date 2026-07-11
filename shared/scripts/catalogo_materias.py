"""Rols One — catalogo editable de clasificaciones y materiales.

Las opciones de los selects "Clasificacion de materia" y "Material (felpa)"
de la ficha de calidad vienen de aqui en vez de estar hardcoded en HTML.
Asi el usuario puede anadir nuevos valores desde la propia UI sin tocar
codigo (boton "+ Nuevo..." en cada select).

Esquema (shared/data/catalogo_materias.json):
{
  "_meta": {...},
  "clasificaciones":   [{"id": "materia-felpa", "label": "Materia felpa"}, ...],
  "materiales_felpa":  [{"id": "lana-hilada",  "label": "Lana hilada"}, ...]
}

Reglas:
- El `id` es un slug estable (a-z 0-9 guion). Se genera a partir del label
  la primera vez. Una vez asignado, NO cambia aunque el label se renombre
  (asi no rompe las referencias en lanas_inventario que guardan el id).
- Los labels son lo que ve el usuario en la UI. Pueden tener acentos,
  parentesis, etc.
- Eliminar una entrada solo se permite si NO esta en uso por ninguna
  calidad. La comprobacion la hace el endpoint, no este modulo.
"""
from __future__ import annotations

import json
import re
import threading
import unicodedata
from datetime import datetime
from pathlib import Path

import os

# Datos de runtime: en prod ROLS_DATA_DIR los fija FUERA del docroot (persisten,
# los deploys no los pisan); en local cae a shared/data como siempre.
import jsonstore  # BD SQLite transaccional (sustituye JSON+RLock)

# Ruta del JSON LEGACY: solo para la migración one-time a SQLite (queda de backup).
DATA_PATH = Path(os.environ.get("ROLS_DATA_DIR") or Path(__file__).resolve().parent.parent / "data") / "catalogo_materias.json"
_lock = threading.RLock()  # (histórico; los `with jsonstore.store().tx():` ahora son transacciones)
_KEY = "catalogo_materias"


def _slug(s: str) -> str:
    """Slug consistente: minusculas, sin acentos, espacios -> guion."""
    if not s:
        return ""
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.lower().strip()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-")


def _default_data() -> dict:
    """Catalogo inicial si el JSON no existe todavia.

    `titulos` aplica solo a calidades de tipo materia-felpa (donde el
    titulo es el grosor / numero de hilos: 65/2C = 65 lana 2 cabos, etc).
    Para basamentos y otros suele ir vacio."""
    return {
        "_meta": {"version": 1, "creado": datetime.now().isoformat(timespec="seconds")},
        "clasificaciones": [
            {"id": "materia-felpa", "label": "Materia felpa"},
            {"id": "basamentos",    "label": "Basamentos"},
            {"id": "otros",         "label": "Otros"},
        ],
        "materiales_felpa": [
            {"id": "lana-hilada", "label": "Lana hilada"},
            {"id": "lana-bruto",  "label": "Lana en bruto"},
            {"id": "pp",          "label": "Polipropileno (PP)"},
            {"id": "pes",         "label": "Poliéster (PES)"},
        ],
        "titulos": [
            {"id": "65-2c",  "label": "65/2C"},
            {"id": "80-2c",  "label": "80/2C"},
            {"id": "100-2c", "label": "100/2C"},
            {"id": "100-3c", "label": "100/3C"},
            {"id": "140-1c", "label": "140/1C"},
            {"id": "140-2c", "label": "140/2C"},
            {"id": "140-3c", "label": "140/3C"},
            {"id": "150-2c", "label": "150/2C"},
            {"id": "150-3c", "label": "150/3C"},
        ],
    }


def cargar() -> dict:
    """Carga el catálogo desde SQLite (migra el JSON legacy la 1ª vez; si no hay
    nada, usa los defaults)."""
    d = jsonstore.store().load(_KEY, _default_data, DATA_PATH)
    # Garantizar que las listas existen aunque el doc sea de una version
    # anterior (p.ej. v1 no tenia `titulos`)
    d.setdefault("clasificaciones", [])
    d.setdefault("materiales_felpa", [])
    if "titulos" not in d:
        # Migracion suave: si falta la lista, la creamos con los defaults
        # para no romper la UI nueva. El usuario puede borrarlos despues.
        d["titulos"] = _default_data()["titulos"]
        _guardar(d)
    return d


def _guardar(data: dict) -> None:
    jsonstore.store().save(_KEY, data)


# Mapa interno: tipo logico -> clave del JSON. Centralizado aqui para
# no repetir el if/else en cada funcion. Si se anade un nuevo tipo de
# catalogo (p.ej. "categoria"), basta con anadirlo aqui.
_TIPOS = {
    "clasificacion":  "clasificaciones",
    "material_felpa": "materiales_felpa",
    "titulo":         "titulos",
}


def _lista_de(tipo: str) -> list[dict]:
    key = _TIPOS.get(tipo)
    if not key:
        return []
    return list(cargar().get(key) or [])


def listar_clasificaciones() -> list[dict]:
    return _lista_de("clasificacion")


def listar_materiales_felpa() -> list[dict]:
    return _lista_de("material_felpa")


def listar_titulos() -> list[dict]:
    return _lista_de("titulo")


def labels_dict(tipo: str) -> dict[str, str]:
    """Mapa {id: label} para que la UI traduzca un id a su label."""
    return {it["id"]: it.get("label") or it["id"] for it in _lista_de(tipo)}


def anadir(tipo: str, label: str) -> tuple[dict | None, str]:
    """Anade una nueva entrada al catalogo de `tipo`.

    Devuelve (entrada_creada, "") o (None, error). Si ya existe una con
    el mismo id (slug), devuelve la existente sin duplicar (idempotente).
    """
    key = _TIPOS.get(tipo)
    if not key:
        return None, (f"tipo invalido: {tipo!r} "
                      f"(esperado {', '.join(repr(k) for k in _TIPOS)})")
    label = (label or "").strip()
    if not label:
        return None, "El label no puede estar vacio"
    if len(label) > 80:
        return None, "El label es demasiado largo (max 80 caracteres)"
    sid = _slug(label)
    if not sid:
        return None, f"No puedo generar un id valido a partir de {label!r}"
    with jsonstore.store().tx():
        data = cargar()
        lista = data.setdefault(key, [])
        # Idempotente: si ya existe (mismo id), devuelvo la existente
        for it in lista:
            if it.get("id") == sid:
                return it, ""
        nuevo = {"id": sid, "label": label}
        lista.append(nuevo)
        _guardar(data)
        return nuevo, ""


def quitar(tipo: str, id_: str) -> tuple[bool, str]:
    """Elimina una entrada del catalogo. NO comprueba si esta en uso —
    eso es responsabilidad del endpoint que llama (ver app.py)."""
    key = _TIPOS.get(tipo)
    if not key:
        return False, f"tipo invalido: {tipo!r}"
    with jsonstore.store().tx():
        data = cargar()
        lista = data.setdefault(key, [])
        idx = next((i for i, it in enumerate(lista) if it.get("id") == id_), -1)
        if idx < 0:
            return False, f"no existe {tipo!r} con id {id_!r}"
        del lista[idx]
        _guardar(data)
        return True, ""


if __name__ == "__main__":
    d = cargar()
    print("Clasificaciones:", [c["label"] for c in d.get("clasificaciones", [])])
    print("Materiales:",    [m["label"] for m in d.get("materiales_felpa", [])])
