"""Rols One — gestion de permisos por rol.

Mapping simple `(rol, permiso) -> bool`. Los permisos se almacenan en
shared/data/permisos.json para que tanto el asistente (que los edita)
como la calculadora (que los lee) compartan la misma fuente.

Esquema:
{
  "_meta": {...},
  "permisos_rol": {
    "admin":         { "compras": true,  ... },
    "comercial":     { "compras": true,  ... },
    "representante": { "compras": false, ... }
  }
}

Permisos definidos hoy:
- `compras`: ver/acceder a la seccion de Compras (tab y card de inicio).

Si la clave de un (rol, permiso) no existe, se usa el DEFAULT_PERMISOS.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from threading import RLock

import os

# Datos de runtime: en prod ROLS_DATA_DIR los fija FUERA del docroot (persisten,
# los deploys no los pisan); en local cae a shared/data como siempre.
DATA_PATH = Path(os.environ.get("ROLS_DATA_DIR") or Path(__file__).resolve().parent.parent / "data") / "permisos.json"
_lock = RLock()

ROLES = ("admin", "comercial", "representante")

# Whitelist de permisos validos + label legible para la UI.
# El orden de declaracion es el orden visual en la tabla.
PERMISOS_LABEL: dict[str, str] = {
    "calcular_presupuestos":         "Calcular presupuestos y descargar PDFs",
    "ver_presupuestos_todos":         "Ver presupuestos de todos los usuarios (si no, solo los suyos)",
    "ver_stock_activo":               "Ver Stock Rols activo (catalogo permanente)",
    "ver_productos_discontinuados":   "Ver productos discontinuados",
    "ver_colecciones_cliente":        "Ver colecciones cliente y productos personalizados",
    "editar_ficha_producto":          "Editar ficha de producto (Navision, escandallo, telar...)",
    "compras":                        "Gestion de materias primas, compras y proveedores",
    "acceso_transporte":              "Acceso a Calculo de transporte (cargo.rolscarpets.com)",
    "gestion_usuarios":               "Gestion de usuarios (crear, borrar, cambiar rol)",
}
PERMISOS = tuple(PERMISOS_LABEL.keys())

# Agrupacion visual de los permisos por PRODUCTO/seccion. Cada permiso vive en
# exactamente una seccion; la UI pinta una cabecera por seccion y debajo sus
# filas. Anadir un producto nuevo = anadir aqui su seccion con sus permisos.
SECCIONES: tuple[dict, ...] = (
    {
        "id": "one",
        "label": "Rols One",
        "sub": "Calculadora y presupuestos",
        "permisos": [
            "calcular_presupuestos",
            "ver_presupuestos_todos",
            "ver_stock_activo",
            "ver_productos_discontinuados",
            "ver_colecciones_cliente",
            "editar_ficha_producto",
            "compras",
        ],
    },
    {
        "id": "cargo",
        "label": "Rols Cargo",
        "sub": "Calculo de transporte (cargo.rolscarpets.com)",
        "permisos": ["acceso_transporte"],
    },
    {
        "id": "cuentas",
        "label": "Cuentas",
        "sub": "Identidad y accesos de Rols One",
        "permisos": ["gestion_usuarios"],
    },
)

# Permisos que el rol "admin" SIEMPRE tiene (no se pueden desactivar
# desde la UI). Evita que el ultimo admin se quede sin acceso a la
# gestion de usuarios. La UI muestra el checkbox bloqueado.
ADMIN_FIJOS: tuple[str, ...] = ("gestion_usuarios",)

# Defaults seguros. Reflejan el comportamiento previo a la migracion:
# admin todo; comercial casi todo (no gestion usuarios); representante
# solo lo basico (calcular + ver stock activo).
DEFAULT_PERMISOS: dict[str, dict[str, bool]] = {
    "admin": {
        "calcular_presupuestos":       True,
        "ver_presupuestos_todos":       True,
        "ver_stock_activo":             True,
        "ver_productos_discontinuados": True,
        "ver_colecciones_cliente":      True,
        "editar_ficha_producto":        True,
        "compras":                      True,
        "acceso_transporte":            True,
        "gestion_usuarios":             True,
    },
    "comercial": {
        "calcular_presupuestos":       True,
        "ver_presupuestos_todos":       False,
        "ver_stock_activo":             True,
        "ver_productos_discontinuados": True,
        "ver_colecciones_cliente":      True,
        "editar_ficha_producto":        True,
        "compras":                      True,
        "acceso_transporte":            True,
        "gestion_usuarios":             False,
    },
    "representante": {
        "calcular_presupuestos":       True,
        "ver_presupuestos_todos":       False,
        "ver_stock_activo":             True,
        "ver_productos_discontinuados": False,
        "ver_colecciones_cliente":      False,
        "editar_ficha_producto":        False,
        "compras":                      False,
        "acceso_transporte":            False,
        "gestion_usuarios":             False,
    },
}


def _cargar_raw() -> dict:
    if not DATA_PATH.exists():
        return {"_meta": {"version_schema": 1}, "permisos_rol": {}}
    return json.loads(DATA_PATH.read_text(encoding="utf-8"))


def _guardar(data: dict) -> None:
    DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    data.setdefault("_meta", {})
    data["_meta"]["actualizado_en"] = datetime.now().isoformat(timespec="seconds")
    tmp = DATA_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(DATA_PATH)


def matriz_completa() -> dict[str, dict[str, bool]]:
    """Devuelve la matriz {rol: {permiso: bool}} con todos los roles y
    permisos validos, rellenando con defaults los que no estan seteados."""
    raw = _cargar_raw().get("permisos_rol") or {}
    out: dict[str, dict[str, bool]] = {}
    for rol in ROLES:
        out[rol] = {}
        for perm in PERMISOS:
            valor = raw.get(rol, {}).get(perm)
            if valor is None:
                valor = DEFAULT_PERMISOS.get(rol, {}).get(perm, False)
            out[rol][perm] = bool(valor)
    return out


def permisos_de(rol: str) -> dict[str, bool]:
    """Permisos efectivos de un rol concreto."""
    return matriz_completa().get((rol or "").lower(), {})


def puede(rol: str, permiso: str) -> bool:
    """Helper: ¿el rol tiene el permiso indicado?"""
    return bool(permisos_de(rol).get(permiso, False))


def actualizar(rol: str, permiso: str, allowed: bool) -> tuple[bool, str]:
    """Setea un permiso concreto de un rol. Devuelve (ok, error)."""
    rol = (rol or "").lower()
    permiso = (permiso or "").lower()
    if rol not in ROLES:
        return False, f"rol invalido: {rol!r}"
    if permiso not in PERMISOS:
        return False, f"permiso invalido: {permiso!r}"
    with _lock:
        data = _cargar_raw()
        prol = data.setdefault("permisos_rol", {})
        prol.setdefault(rol, {})[permiso] = bool(allowed)
        _guardar(data)
        return True, ""


# ---------------------------------------------------------------------------
# CLI util
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys
    if not sys.argv[1:] or sys.argv[1] == "list":
        m = matriz_completa()
        print(f"{'rol':<15s} | {' | '.join(PERMISOS)}")
        print("-" * 50)
        for rol, perms in m.items():
            vals = " | ".join("yes" if perms[p] else "no" for p in PERMISOS)
            print(f"{rol:<15s} | {vals}")
    elif sys.argv[1] == "set" and len(sys.argv) == 5:
        rol, perm, val = sys.argv[2], sys.argv[3], sys.argv[4].lower() in ("1","true","yes")
        ok, err = actualizar(rol, perm, val)
        print("OK" if ok else f"ERR {err}")
    else:
        print("Uso: python permisos.py [list | set <rol> <permiso> <true|false>]")
