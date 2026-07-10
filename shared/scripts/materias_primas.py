"""Rols One — API de materias primas.

Wrapper sobre `lanas_inventario.py`, que es la fuente unica desde la
migracion al modelo unificado (mayo 2026).

Conceptos:
- CALIDAD = (titulo, tipo). Ej. "65/2C" + "pais normal".
- VARIANTE = (calidad, proveedor). Ej. "65/2C pais normal por COBO".
- PARTIDO = LOTE de una variante. Ej. partido "3923C" de la variante COBO.

Este modulo expone "lanas" como calidades agrupadas (la unidad que tiene
sentido para una receta de producto: el escandallo apunta a una calidad
sin importar quien la sirve). Las funciones de lote (agregar_lote, etc.)
necesitan el proveedor cuando hay multi-proveedor para una calidad.

Compatible con el escandallo: `lana_id` en el escandallo de productos es
la `calidad_id` de este modulo.
"""
from __future__ import annotations

import re
import unicodedata
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))

import lanas_inventario as _li


# ---------------------------------------------------------------------------
# Slug compartido (idem que lanas_inventario)
# ---------------------------------------------------------------------------

def _slug(s: str) -> str:
    if not s:
        return ""
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.lower().strip()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-")


def id_lana(titulo: str, tipo: str) -> str:
    """Devuelve el calidad_id canonico (sin proveedor)."""
    titulo = (titulo or "").strip()
    tipo = (tipo or "").strip()
    return f"{_slug(titulo)}__{_slug(tipo)}" if titulo else _slug(tipo)


# ---------------------------------------------------------------------------
# Lectura: lanas = CALIDADES agrupadas
# ---------------------------------------------------------------------------

def _expandir_calidad_a_lana(c: dict) -> dict:
    """Convierte una calidad agrupada en el formato que la UI espera
    (con `lotes` en lugar de `partidos`, anotando proveedor)."""
    lotes = []
    for p in c.get("partidos", []):
        lotes.append({
            "lote":                   p.get("partido"),
            "cantidad_disponible_kg": p.get("kg") or 0,
            # Kg que el proveedor guarda para nosotros (reservados, fuera
            # del almacen Rols). Si el usuario no los ha registrado, 0.
            "kg_proveedor":           p.get("kg_proveedor") or 0,
            "coste_kg":               p.get("coste_kg"),
            "fecha_entrada":          p.get("fecha_entrada"),
            "proveedor":              p.get("proveedor") or "",
            "variante_id":            p.get("variante_id"),
        })
    return {
        "id":             c["calidad_id"],
        "material":       c.get("material") or "lana",
        "titulo":         c.get("titulo") or "",
        "tipo":           c.get("tipo") or "",
        # Clasificacion y material_felpa son a nivel calidad — se setean
        # desde la ficha y los necesitamos en la tabla de "Materias primas"
        # para renderizar las columnas Clasificacion y Material y para
        # alimentar los selects de filtro.
        "clasificacion":  c.get("clasificacion") or "",
        "material_felpa": c.get("material_felpa") or "",
        "variantes":      c.get("variantes") or [],
        "lotes":          lotes,
        "total_kg":       c.get("total_kg") or 0,
        # Sumas de planificacion a nivel calidad (suma de las variantes)
        # — necesarias para mostrar columnas "Cantidad min. seguridad" y
        # "Cantidad reposicion" en el listado de Materias primas.
        "limite_kg":      c.get("limite_kg")  or 0,
        "kg_a_pedir":     c.get("kg_a_pedir") or 0,
        "coste_medio_kg": c.get("coste_medio_kg"),
    }


def listar_lanas() -> list[dict]:
    """Lista de CALIDADES. Cada una incluye sus variantes y lotes.

    Una calidad sin variantes activas no aparece (no hay datos). Si en el
    futuro hace falta una "lista maestra de calidades posibles", se podra
    leer de un fichero aparte; por ahora la lista viene de los datos.

    Tambien sintetiza una calidad "Lana en crudo" a partir de los
    contenedores de lana_cruda.json — para que aparezca en los listados
    estandar (Materias primas, Todos los partidos, Movimientos,
    Proveedores) sin duplicar los datos.
    """
    _li.invalidar_cache()
    reales = [_expandir_calidad_a_lana(c) for c in _li.listar_calidades()]
    sinteticas = _sintetizar_calidades_crudo()
    return reales + sinteticas


def lana_por_id(lana_id: str) -> dict | None:
    """Busca una CALIDAD por su id (calidad_id). Incluye la calidad
    sintetica 'Lana en crudo' si se pide por su id."""
    if not lana_id:
        return None
    lid = lana_id.strip()
    # Calidad sintetica de lana en crudo
    if lid == _CRUDO_CALIDAD_ID:
        sint = _sintetizar_calidades_crudo()
        return sint[0] if sint else None
    c = _li.calidad_por_id(lid)
    return _expandir_calidad_a_lana(c) if c else None


# ---------------------------------------------------------------------------
# Proyeccion de lana en crudo como calidad sintetica
# ---------------------------------------------------------------------------
# Los contenedores de lana cruda viven en lana_cruda.json (modulo aparte)
# pero conceptualmente forman una calidad mas: "Lana en crudo · genérica"
# con N variantes (una por proveedor de origen) y los contenedores como
# partidos. Sintetizamos esa estructura aqui para que aparezca en los
# listados estandar sin tener que migrar la data ni tocar el modelo de
# lanas_inventario. La fuente sigue siendo lana_cruda.json y el tab
# "Lana en crudo" sigue siendo el lugar canonico para crear/editar
# contenedores y ejecutar ordenes de hilado.

_CRUDO_CALIDAD_ID = "lana-en-crudo__generica"
_CRUDO_TITULO = "Lana en crudo"
_CRUDO_TIPO = "genérica"


def _sintetizar_calidades_crudo() -> list[dict]:
    """Construye la lista de calidades sinteticas a partir de los
    contenedores de lana_cruda.json. Devuelve una sola calidad
    (siempre la misma id) con N variantes — una por proveedor_origen.

    Si no hay contenedores, devuelve lista vacia.
    """
    try:
        import lana_cruda as _lc
        _lc.invalidar_cache()
        contenedores = _lc.listar_contenedores(incluir_agotados=True)
    except Exception:
        return []
    if not contenedores:
        return []

    # Agrupar contenedores por proveedor_origen
    por_prov: dict[str, list[dict]] = {}
    for c in contenedores:
        prov = (c.get("proveedor_origen") or "").strip() or "Desconocido"
        por_prov.setdefault(prov, []).append(c)

    variantes = []
    partidos_global = []
    total_kg = 0.0
    coste_total = 0.0
    kg_con_coste = 0.0

    for prov, conts in por_prov.items():
        prov_slug = _slug(prov)
        variante_id = f"{_CRUDO_CALIDAD_ID}__{prov_slug}"
        partidos_var = []
        kg_v = 0.0
        for c in conts:
            kg = float(c.get("kg_actual") or 0)
            coste = c.get("coste_kg")
            p = {
                "partido":       c.get("ref") or c.get("id"),
                "kg":            kg,
                "kg_proveedor":  0,
                "kg_inicial":    float(c.get("kg_inicial") or 0),
                "coste_kg":      float(coste) if coste is not None else None,
                "fecha_entrada": c.get("fecha_compra") or c.get("fecha_creacion", "")[:10],
                "fecha_compra":  c.get("fecha_compra"),
                "fecha_llegada_hilador": c.get("fecha_llegada_hilador"),
                "fecha_agotado": None,
                "estanteria":    None,
                "observaciones": c.get("observaciones") or "",
                "hilador_actual": c.get("hilador_actual") or "",
                "contenedor_id": c.get("id"),
                "proveedor":     prov,
                "variante_id":   variante_id,
            }
            partidos_var.append(p)
            partidos_global.append(p)
            kg_v += kg
            total_kg += kg
            if coste is not None:
                coste_total += kg * float(coste)
                kg_con_coste += kg

        variantes.append({
            "id":             variante_id,
            "proveedor":      prov,
            "total_kg":       round(kg_v, 2),
            "limite_kg":      0,
            "kg_a_pedir":     0,
            "estado":         "ok",
            # Marca para que la UI sepa que esto es lana en crudo
            "es_crudo":       True,
        })

    coste_medio = (coste_total / kg_con_coste) if kg_con_coste > 0 else None

    calidad_sint = {
        "id":             _CRUDO_CALIDAD_ID,
        "material":       "lana cruda",
        "titulo":         _CRUDO_TITULO,
        "tipo":           _CRUDO_TIPO,
        "clasificacion":  "materia-felpa",
        "material_felpa": "lana-bruto",
        "variantes":      variantes,
        "lotes":          [_partido_a_lote(p) for p in partidos_global],
        "total_kg":       round(total_kg, 2),
        "limite_kg":      0,
        "kg_a_pedir":     0,
        "coste_medio_kg": round(coste_medio, 4) if coste_medio is not None else None,
        # Marca de proyeccion — la UI puede usarla para deshabilitar
        # acciones que no aplican (editar nombre, generar pedido al
        # proveedor en el sentido tradicional, etc.) y para redirigir
        # al tab "Lana en crudo".
        "es_crudo":       True,
    }
    return [calidad_sint]


def _partido_a_lote(p: dict) -> dict:
    """Convierte un partido sintetico al formato 'lote' que la UI espera
    en _expandir_calidad_a_lana (con cantidad_disponible_kg, etc.)."""
    return {
        "lote":                   p.get("partido"),
        "cantidad_disponible_kg": p.get("kg") or 0,
        "kg_proveedor":           0,
        "coste_kg":               p.get("coste_kg"),
        "fecha_entrada":          p.get("fecha_entrada"),
        "proveedor":              p.get("proveedor") or "",
        "variante_id":            p.get("variante_id"),
    }


# ---------------------------------------------------------------------------
# Escritura de la calidad en si — DEPRECADO
#
# Crear/editar/borrar CALIDADES desde este endpoint no tiene sentido en
# el modelo unificado, porque una calidad existe solo si tiene al menos
# una variante (proveedor). Devolvemos errores claros para que la UI
# vieja no falle silenciosamente; las llamadas seran reemplazadas por
# operaciones a nivel de VARIANTE (entrada de mercancia de un nuevo
# proveedor genera la calidad).
# ---------------------------------------------------------------------------

def crear_lana(titulo: str, tipo: str, material: str = "lana") -> tuple[dict | None, str]:
    """Crea una calidad placeholder (sin proveedor todavia). El usuario
    completara la ficha despues (proveedores, partidos, clasificacion).

    Wrapper de lanas_inventario.crear_calidad_placeholder. El nombre
    (tipo) es lo unico obligatorio; titulo es opcional. La calidad se
    devuelve en formato de la API (con 'lotes' en lugar de 'partidos').
    """
    nueva, err = _li.crear_calidad_placeholder(tipo, titulo=titulo,
                                                material=material)
    if err:
        return None, err
    return nueva, ""  # {calidad_id, variante_id}


def actualizar_lana(lana_id: str, titulo: str, tipo: str,
                    material: str = "lana") -> tuple[dict | None, str]:
    return None, ("Renombrar calidad no soportado: editar nombre desde la "
                  "variante en Compras, o crear nueva calidad y migrar partidos.")


def borrar_lana(lana_id: str, forzar: bool = False,
                usuario: str = "") -> tuple[bool, str]:
    """Borra una calidad entera (todas sus variantes y partidos).

    Wrapper de lanas_inventario.borrar_calidad. Por defecto bloquea si
    hay kg vivos o pedidos abiertos; con `forzar=True` se borra de todas
    formas y se registran movimientos tipo 'borrado' para auditoria.
    """
    return _li.borrar_calidad(lana_id, forzar=forzar, usuario=usuario)


# ---------------------------------------------------------------------------
# Lotes (partidos) — operan sobre una VARIANTE concreta
#
# Para identificar la variante: o pasas `proveedor` explicito, o si la
# calidad solo tiene una variante se resuelve automaticamente.
# ---------------------------------------------------------------------------

def _resolver_variante_id(calidad_id: str, proveedor: str = "") -> tuple[str | None, str]:
    """Devuelve (variante_id, ''), o (None, error) si ambiguo o no existe."""
    c = _li.calidad_por_id(calidad_id)
    if not c:
        return None, f"calidad {calidad_id!r} no existe"
    variantes = c.get("variantes") or []
    if proveedor:
        prov = proveedor.strip().upper()
        for v in variantes:
            if (v.get("proveedor") or "").upper() == prov:
                return v["id"], ""
        return None, f"calidad {calidad_id!r} no tiene proveedor {proveedor!r}"
    if len(variantes) == 1:
        return variantes[0]["id"], ""
    nombres = [v.get("proveedor") for v in variantes]
    return None, (f"la calidad {calidad_id!r} tiene varios proveedores "
                  f"({', '.join(nombres)}); indica `proveedor` en la peticion")


def agregar_lote(lana_id: str, lote_ref: str, cantidad_kg, coste_kg,
                 fecha_entrada: str, usuario: str = "",
                 proveedor: str = "") -> tuple[dict | None, str]:
    """Anade un partido (lote) a la variante correspondiente. `lana_id`
    es la calidad_id; `proveedor` desambigua si hay multi-proveedor."""
    if not lote_ref or not fecha_entrada:
        return None, "Lote, cantidad, coste y fecha son obligatorios"
    vid, err = _resolver_variante_id(lana_id, proveedor)
    if err:
        return None, err
    nuevo, err = _li.agregar_partido(
        vid, partido_ref=lote_ref, kg=cantidad_kg,
        coste_kg=coste_kg, fecha_entrada=fecha_entrada,
        usuario=usuario,
    )
    if err:
        return None, err
    return {
        "lote":                   nuevo["partido"],
        "cantidad_disponible_kg": nuevo["kg"],
        "coste_kg":               nuevo["coste_kg"],
        "fecha_entrada":          nuevo["fecha_entrada"],
    }, ""


def actualizar_lote(lana_id: str, lote_ref_actual: str,
                    lote_ref_nuevo: str = None, cantidad_kg=None, coste_kg=None,
                    fecha_entrada: str = None, usuario: str = "",
                    proveedor: str = "",
                    observaciones: str = None,
                    estanteria: str = None,
                    fecha_compra: str = None,
                    kg_proveedor=None) -> tuple[dict | None, str]:
    """Actualiza un partido. Cualquier parametro a None se OMITE del payload
    (lanas_inventario.actualizar_partido preserva el valor previo si la key
    no existe en el dict). Asi se permite editar solo observaciones sin
    tocar kg/coste/fecha, por ejemplo.

    `kg_proveedor` es la parte del partido que el proveedor sigue guardando
    en su almacen (reservada para Rols). Vive aparte de `cantidad_kg` para
    no romper la logica de consumo que solo opera sobre lo que tenemos
    fisicamente."""
    vid, err = _resolver_variante_id(lana_id, proveedor)
    if err:
        return None, err
    datos: dict = {}
    if lote_ref_nuevo is not None: datos["partido"]       = lote_ref_nuevo
    if cantidad_kg    is not None: datos["kg"]            = cantidad_kg
    if kg_proveedor   is not None: datos["kg_proveedor"]  = kg_proveedor
    if coste_kg       is not None: datos["coste_kg"]      = coste_kg
    if fecha_entrada  is not None: datos["fecha_entrada"] = fecha_entrada
    if observaciones  is not None: datos["observaciones"] = observaciones
    if estanteria     is not None: datos["estanteria"]    = estanteria
    if fecha_compra   is not None: datos["fecha_compra"]  = fecha_compra
    actualizado, err = _li.actualizar_partido(vid, lote_ref_actual, datos,
                                              usuario=usuario)
    if err:
        return None, err
    return {
        "lote":                   actualizado["partido"],
        "cantidad_disponible_kg": actualizado["kg"],
        "kg_proveedor":           actualizado.get("kg_proveedor") or 0,
        "coste_kg":               actualizado["coste_kg"],
        "fecha_entrada":          actualizado["fecha_entrada"],
        "observaciones":          actualizado.get("observaciones"),
    }, ""


def borrar_lote(lana_id: str, lote_ref: str, usuario: str = "",
                proveedor: str = "") -> tuple[bool, str]:
    vid, err = _resolver_variante_id(lana_id, proveedor)
    if err:
        return False, err
    return _li.borrar_partido(vid, lote_ref, usuario=usuario)


def consumir_lote(lana_id: str, lote_ref: str, kg, usuario: str = "",
                  nota: str = "", proveedor: str = "") -> tuple[dict | None, str]:
    """Consume kg de un partido. Si hay varios proveedores con un partido
    de la misma ref, hay que indicar proveedor."""
    vid, err = _resolver_variante_id(lana_id, proveedor)
    if err:
        return None, err
    actualizado, err = _li.consumir_partido(vid, lote_ref, kg=kg,
                                            usuario=usuario, nota=nota)
    if err:
        return None, err
    return {
        "lote":                   actualizado["partido"],
        "cantidad_disponible_kg": actualizado["kg"],
        "coste_kg":               actualizado["coste_kg"],
        "fecha_entrada":          actualizado["fecha_entrada"],
    }, ""


def trasladar_lote(lana_id: str, lote_ref: str, kg, direccion: str,
                   usuario: str = "", nota: str = "",
                   proveedor: str = "") -> tuple[dict | None, str]:
    """Mueve kg entre el almacen Rols y el del proveedor para el mismo
    partido. `direccion` ∈ {"a-proveedor", "a-rols"}. El partido sigue
    siendo el mismo registro (mismo nº lote), solo cambia el reparto
    entre `cantidad_disponible_kg` y `kg_proveedor`."""
    vid, err = _resolver_variante_id(lana_id, proveedor)
    if err:
        return None, err
    actualizado, err = _li.trasladar_kg_partido(
        vid, lote_ref, kg=kg, direccion=direccion,
        usuario=usuario, nota=nota,
    )
    if err:
        return None, err
    return {
        "lote":                   actualizado["partido"],
        "cantidad_disponible_kg": actualizado["kg"],
        "kg_proveedor":           actualizado.get("kg_proveedor") or 0,
        "coste_kg":               actualizado.get("coste_kg"),
        "fecha_entrada":          actualizado.get("fecha_entrada"),
    }, ""


# ---------------------------------------------------------------------------
# Vistas planas (compatibles con la UI actual)
# ---------------------------------------------------------------------------

def listar_lotes_global(incluir_agotados: bool = False) -> dict:
    """Listado plano de TODOS los partidos de TODAS las variantes con
    metadata. Compatible con la UI antigua de 'Todos los lotes'."""
    items: list[dict] = []
    total_kg = 0.0
    valor_total = 0.0
    calidades_con_stock: set[str] = set()
    _li.invalidar_cache()
    for v in _li.listar_lanas():
        for p in (v.get("partidos") or []):
            cant = float(p.get("kg") or 0)
            coste = float(p.get("coste_kg") or 0) if p.get("coste_kg") is not None else 0.0
            agotado = cant <= 0
            if agotado and not incluir_agotados:
                continue
            valor = cant * coste
            cid = v.get("calidad_id") or ""
            items.append({
                "lana_id":                cid,            # = calidad_id, compatible
                "variante_id":            v.get("id"),    # nuevo: especifica proveedor
                "material":               v.get("material") or "lana",
                "titulo":                 v.get("titulo"),
                "tipo":                   v.get("tipo"),
                "proveedor":              v.get("proveedor") or "",
                "titulo_completo":        f"{v.get('titulo','')} {v.get('tipo','')}".strip(),
                # Clasificacion / material_felpa: vienen de la calidad
                # (todas las variantes de una calidad comparten estos
                # campos). Los necesitamos para los filtros del tab
                # "Todos los partidos".
                "clasificacion":          v.get("clasificacion") or "",
                "material_felpa":         v.get("material_felpa") or "",
                "lote":                   p.get("partido"),
                "cantidad_disponible_kg": cant,
                "coste_kg":               p.get("coste_kg"),
                "fecha_entrada":          p.get("fecha_entrada"),
                "valor_eur":              round(valor, 2),
                "agotado":                agotado,
            })
            if not agotado:
                total_kg += cant
                valor_total += valor
                calidades_con_stock.add(cid)
    # Tambien proyectamos los contenedores de lana en crudo como partidos
    # (con clasificacion materia-felpa / material lana-bruto para que
    # encajen en los filtros del tab "Todos los partidos").
    for crudo_cal in _sintetizar_calidades_crudo():
        cid = crudo_cal.get("id") or ""
        for v in crudo_cal.get("variantes") or []:
            prov = v.get("proveedor") or ""
            vid = v.get("id")
            for lote in crudo_cal.get("lotes") or []:
                if (lote.get("variante_id") != vid):
                    continue
                cant = float(lote.get("cantidad_disponible_kg") or 0)
                agotado = cant <= 0
                if agotado and not incluir_agotados:
                    continue
                coste = float(lote.get("coste_kg") or 0) if lote.get("coste_kg") is not None else 0.0
                valor = cant * coste
                items.append({
                    "lana_id":                cid,
                    "variante_id":            vid,
                    "material":               "lana cruda",
                    "titulo":                 _CRUDO_TITULO,
                    "tipo":                   _CRUDO_TIPO,
                    "proveedor":              prov,
                    "titulo_completo":        f"{_CRUDO_TITULO} {_CRUDO_TIPO}".strip(),
                    "clasificacion":          "materia-felpa",
                    "material_felpa":         "lana-bruto",
                    "lote":                   lote.get("lote"),
                    "cantidad_disponible_kg": cant,
                    "coste_kg":               lote.get("coste_kg"),
                    "fecha_entrada":          lote.get("fecha_entrada"),
                    "valor_eur":              round(valor, 2),
                    "agotado":                agotado,
                    "es_crudo":               True,
                })
                if not agotado:
                    total_kg += cant
                    valor_total += valor
                    calidades_con_stock.add(cid)

    items.sort(key=lambda it: (it["titulo_completo"], it.get("proveedor") or "",
                               it.get("fecha_entrada") or ""))
    return {
        "lotes":   items,
        "totales": {
            "total_kg":             round(total_kg, 3),
            "valor_total_eur":      round(valor_total, 2),
            "n_lotes":              len(items),
            "n_lanas_con_stock":    len(calidades_con_stock),
        },
    }


def resumen_lana(lana_id: str) -> dict:
    """Resumen calculado de una calidad: total kg, coste medio
    ponderado, partidos activos y agotados."""
    c = _li.calidad_por_id(lana_id) or {}
    partidos = c.get("partidos", [])
    activos = [p for p in partidos if (p.get("kg") or 0) > 0]
    agotados = [p for p in partidos if (p.get("kg") or 0) <= 0]
    return {
        "total_kg":          c.get("total_kg") or 0,
        "coste_medio_kg":    c.get("coste_medio_kg"),
        "n_lotes_activos":   len(activos),
        "n_lotes_agotados":  len(agotados),
    }


# ---------------------------------------------------------------------------
# CLI util
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    lanas = listar_lanas()
    print(f"materias primas: {len(lanas)} calidades")
    for l in lanas[:5]:
        provs = ", ".join(v["proveedor"] for v in l["variantes"])
        print(f"  {l['id']:<40s}  {l['total_kg']:>7.0f} kg  proveedores: {provs}")
