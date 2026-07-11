"""Rols One — gestion de proveedores de materias primas.

Cada proveedor tiene una ficha con datos basicos (razon social, CIF,
direccion), contacto (persona, email, telefono) y datos comerciales
(plazo de entrega, pedido minimo, condiciones de pago, portes).

El JSON vive en shared/data/proveedores.json. Estructura:
{
  "_meta": {...},
  "proveedores": [
    {
      "id":               "cobo",         # slug, estable, no editable
      "nombre":           "COBO",         # display, mayusculas
      "razon_social":     "Industrias Cobo S.L.",
      "cif":              "B-12345678",
      "direccion":        "C/ ... 12",
      "cp":               "08800",
      "ciudad":           "Sitges",
      "provincia":        "Barcelona",
      "pais":             "España",
      "contacto_persona":   "Juan García",
      "contacto_email":     "ventas@cobo.com",
      "contacto_telefono":  "+34 938 12 34 56",
      "plazo_entrega_dias": 28,
      "pedido_minimo_kg":   500,
      "pedido_minimo_eur":  5000,
      "condiciones_pago":  "30 días fecha factura",
      "portes":            "Franco a partir de 3.000 €",
      "activo":            true,
      "notas":             "",
      "creado_en":         "...",
      "actualizado_en":    "..."
    }
  ]
}

El `id` se deriva del nombre via slug y se conserva inmutable aunque
se renombre el proveedor (asi las variantes de lanas_inventario.json
que usan el nombre como referencia no se rompen — aunque la
referencia funcional es el nombre, no el id).
"""
from __future__ import annotations

import json
import re
import unicodedata
from datetime import datetime
from pathlib import Path
from threading import RLock

import os

# Datos de runtime: en prod ROLS_DATA_DIR los fija FUERA del docroot (persisten,
# los deploys no los pisan); en local cae a shared/data como siempre.
DATA_PATH = Path(os.environ.get("ROLS_DATA_DIR") or Path(__file__).resolve().parent.parent / "data") / "proveedores.json"
_lock = RLock()


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------

def _slug(s: str) -> str:
    if not s:
        return ""
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.lower().strip()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-")


def cargar() -> dict:
    _vacio = {"_meta": {"version_schema": 1}, "proveedores": []}
    if not DATA_PATH.exists():
        return _vacio
    try:
        return json.loads(DATA_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        import logging
        logging.getLogger("erp.store").error(
            "JSON corrupto/ilegible en %s (%s); se sirve vacío", DATA_PATH, e)
        return _vacio


def _guardar(data: dict) -> None:
    DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    data.setdefault("_meta", {})
    data["_meta"]["actualizado_en"] = datetime.now().isoformat(timespec="seconds")
    tmp = DATA_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(DATA_PATH)


# ---------------------------------------------------------------------------
# Lectura
# ---------------------------------------------------------------------------

def listar(incluir_inactivos: bool = True) -> list[dict]:
    """Lista de proveedores. Por defecto incluye inactivos."""
    provs = cargar().get("proveedores", [])
    if not incluir_inactivos:
        provs = [p for p in provs if p.get("activo", True)]
    return list(provs)


def por_id(prov_id: str) -> dict | None:
    """Busca por id (slug) o por nombre (case-insensitive)."""
    if not prov_id:
        return None
    prov_id_low = prov_id.strip().lower()
    for p in cargar().get("proveedores", []):
        if (p.get("id") or "").lower() == prov_id_low:
            return p
        if (p.get("nombre") or "").lower() == prov_id_low:
            return p
    return None


def por_nombre(nombre: str) -> dict | None:
    """Alias semantico: busca por nombre."""
    return por_id(nombre)


# ---------------------------------------------------------------------------
# Escritura
# ---------------------------------------------------------------------------

CAMPOS_EDITABLES = {
    "nombre", "alias", "razon_social", "cif",
    "direccion", "cp", "ciudad", "provincia", "pais",
    "contacto_persona", "contacto_email", "contacto_telefono",
    "plazo_entrega_dias", "pedido_minimo_kg", "pedido_minimo_eur",
    "condiciones_pago", "portes",
    "activo", "notas",
}


def crear(nombre: str) -> tuple[dict | None, str]:
    """Crea un proveedor solo con el nombre. El resto se rellena luego."""
    nombre = (nombre or "").strip()
    if not nombre:
        return None, "el nombre es obligatorio"
    if len(nombre) > 100:
        return None, "nombre demasiado largo (max 100)"
    pid = _slug(nombre)
    if not pid:
        return None, "el nombre debe tener caracteres alfanumericos"
    with _lock:
        data = cargar()
        provs = data.setdefault("proveedores", [])
        for p in provs:
            if p.get("id") == pid or (p.get("nombre") or "").lower() == nombre.lower():
                return None, f"ya existe un proveedor con nombre {nombre!r}"
        ahora = datetime.now().isoformat(timespec="seconds")
        nuevo = {
            "id":     pid,
            "nombre": nombre.upper(),
            # alias = display corto interno. Arranca igual al nombre y se
            # puede editar despues. Al cambiarlo, actualizamos en cascada
            # el campo `proveedor` de las variantes ligadas.
            "alias":  nombre.upper(),
            "activo": True,
            "creado_en":      ahora,
            "actualizado_en": ahora,
        }
        provs.append(nuevo)
        _guardar(data)
        return nuevo, ""


def actualizar(prov_id: str, datos: dict) -> tuple[dict | None, str]:
    """Actualiza los campos indicados. Solo los que vienen en `datos`.
    El campo `id` NO se puede cambiar."""
    if not isinstance(datos, dict):
        return None, "datos debe ser un objeto"
    desconocidos = set(datos) - CAMPOS_EDITABLES
    if desconocidos:
        return None, f"campos no editables: {sorted(desconocidos)}"
    with _lock:
        data = cargar()
        for p in data.get("proveedores", []):
            if (p.get("id") or "").lower() != prov_id.lower():
                continue
            # Si va a cambiar el alias, guardamos el valor anterior para
            # propagar la nueva referencia a las variantes despues.
            alias_previo = p.get("alias") or p.get("nombre")
            for k, v in datos.items():
                if k in ("nombre", "alias"):
                    v = (v or "").strip().upper()
                    if not v:
                        return None, f"{k} no puede quedar vacio"
                    # alias unico entre proveedores (case-insensitive)
                    if k == "alias":
                        for otro in data["proveedores"]:
                            if otro is p:
                                continue
                            if (otro.get("alias") or "").upper() == v:
                                return None, f"ya existe otro proveedor con alias {v!r}"
                elif k == "activo":
                    v = bool(v)
                elif k in ("plazo_entrega_dias", "pedido_minimo_kg", "pedido_minimo_eur"):
                    if v in (None, ""):
                        v = None
                    else:
                        try:
                            v = float(v) if k == "pedido_minimo_eur" else int(v)
                        except (TypeError, ValueError):
                            return None, f"{k} debe ser numerico"
                elif isinstance(v, str):
                    v = v.strip()
                p[k] = v
            p["actualizado_en"] = datetime.now().isoformat(timespec="seconds")
            _guardar(data)
            # Cascada: si cambio el alias, propagar a lanas_inventario.json
            # (el campo `proveedor` en cada variante guarda el alias por
            # convencion historica). Hace falta para que las variantes
            # sigan apareciendo como suministradas por este proveedor.
            alias_nuevo = p.get("alias") or p.get("nombre")
            if alias_nuevo and alias_previo and alias_nuevo != alias_previo:
                _propagar_alias_a_inventario(alias_previo, alias_nuevo)
            return p, ""
        return None, f"proveedor {prov_id!r} no existe"


def _propagar_alias_a_inventario(alias_viejo: str, alias_nuevo: str) -> int:
    """Renombra el campo `proveedor` en todas las variantes de
    lanas_inventario.json que usaban `alias_viejo`. Devuelve el numero
    de variantes actualizadas.

    Thin wrapper que delega en lanas_inventario.renombrar_proveedor_en_variantes,
    para que la mutacion del JSON de inventario pase por su propio lock
    + escritura atomica + invalidacion de cache. Antes esta funcion
    leia/escribia el JSON con read_text/write_text saltandose todo eso
    — bomba de tiempo bajo concurrencia.
    """
    try:
        import sys
        sys.path.insert(0, str(Path(__file__).parent))
        import lanas_inventario as _li
        return _li.renombrar_proveedor_en_variantes(alias_viejo, alias_nuevo)
    except Exception:
        # Si por algun motivo el modulo de inventario no esta disponible,
        # no se renombra la cascada. La ficha del proveedor si se
        # actualiza, pero las variantes seguiran apuntando al alias
        # viejo. Devolvemos 0 para que el caller sepa que no se hizo nada.
        return 0


def borrar(prov_id: str) -> tuple[bool, str]:
    """Borra un proveedor. Si tiene variantes asociadas en lanas_inventario,
    no se borra (riesgo de perder histórico).

    La comprobacion "esta en uso" se delega tambien a lanas_inventario
    (variantes_con_proveedor) para que pase por la API correcta en lugar
    de leer el JSON directamente.
    """
    with _lock:
        data = cargar()
        provs = data.get("proveedores", [])
        idx = next((i for i, p in enumerate(provs)
                    if (p.get("id") or "").lower() == prov_id.lower()), -1)
        if idx < 0:
            return False, f"proveedor {prov_id!r} no existe"
        nombre = provs[idx].get("nombre") or ""
        # Comprobar que no esta usado por ninguna variante
        try:
            import sys
            sys.path.insert(0, str(Path(__file__).parent))
            import lanas_inventario as _li
            en_uso = _li.variantes_con_proveedor(nombre)
            if en_uso:
                return False, (f"el proveedor esta vinculado a {len(en_uso)} "
                               f"variantes; desactivalo en lugar de borrarlo")
        except Exception:
            # Si falla la comprobacion, mejor NO borrar (fail-safe)
            return False, ("no se ha podido comprobar si el proveedor esta "
                           "en uso por algun partido; intentalo de nuevo")
        del provs[idx]
        _guardar(data)
        return True, ""


# ---------------------------------------------------------------------------
# Migracion inicial: extraer proveedores unicos de lanas_inventario
# ---------------------------------------------------------------------------

def migrar_desde_inventario() -> int:
    """Crea un registro vacio para cada proveedor presente en
    lanas_inventario.json que no exista todavia. Devuelve el numero
    de proveedores nuevos creados."""
    inv_path = DATA_PATH.parent / "lanas_inventario.json"
    if not inv_path.exists():
        return 0
    inv = json.loads(inv_path.read_text(encoding="utf-8"))
    nombres = sorted({(v.get("proveedor") or "").strip()
                      for v in inv.get("lanas", [])
                      if (v.get("proveedor") or "").strip()})
    n = 0
    for nombre in nombres:
        if por_id(nombre) is None:
            _, err = crear(nombre)
            if not err:
                n += 1
    return n


# ---------------------------------------------------------------------------
# KPIs derivados (calculados, no se guardan)
# ---------------------------------------------------------------------------

def kpis_proveedor(prov_id: str) -> dict:
    """Calcula KPIs en vivo desde lanas_inventario.json:
    - n_calidades: nº de variantes distintas que suministra
    - stock_total_kg: suma de kg en stock de todas sus variantes
    - n_pedidos_abiertos: cuantos pedidos con estado='abierto'
    - n_pedidos_total: total de pedidos historicos (cualquier estado)
    """
    p = por_id(prov_id)
    if not p:
        return {"error": "proveedor no existe"}
    nombre = (p.get("nombre") or "").upper()
    inv_path = DATA_PATH.parent / "lanas_inventario.json"
    if not inv_path.exists():
        return {"n_calidades": 0, "stock_total_kg": 0,
                "n_pedidos_abiertos": 0, "n_pedidos_total": 0}
    inv = json.loads(inv_path.read_text(encoding="utf-8"))
    variantes = [v for v in inv.get("lanas", [])
                 if (v.get("proveedor") or "").upper() == nombre]
    stock = sum(float(v.get("total_kg") or 0) for v in variantes)
    n_abiertos = 0
    n_total = 0
    for v in variantes:
        for ped in (v.get("pedidos") or []):
            n_total += 1
            if (ped.get("estado") or "").lower() == "abierto":
                n_abiertos += 1
    return {
        "n_calidades":         len(variantes),
        "stock_total_kg":      round(stock, 2),
        "n_pedidos_abiertos":  n_abiertos,
        "n_pedidos_total":     n_total,
    }


# ---------------------------------------------------------------------------
# CLI util
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys
    if not sys.argv[1:] or sys.argv[1] == "list":
        for p in listar():
            estado = "[A]" if p.get("activo", True) else "[-]"
            print(f"  {estado} {p['nombre']:<15s}  {p.get('contacto_email') or '-'}")
    elif sys.argv[1] == "migrar":
        n = migrar_desde_inventario()
        print(f"Creados {n} proveedores nuevos")
    elif sys.argv[1] == "kpis" and len(sys.argv) > 2:
        print(kpis_proveedor(sys.argv[2]))
    else:
        print("Uso: python proveedores.py [list | migrar | kpis <id>]")
