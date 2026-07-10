"""ERP Produccion Rols — modulo de COMPRAS / Materias primas.

App Flask autonoma extraida de Rols One (rols-calculadora). Cubre el
subsistema de COMPRAS: inventario de lanas (materias primas), proveedores,
lana cruda, partidos y pedidos de compra a proveedor (Kanban tipo compras)
y movimientos de inventario.

NO incluye la calculadora de presupuestos ni las fichas de
producto/escandallo: eso permanece en Rols One. El escandallo (que apunta a
las calidades de lana por `calidad_id`) se conectara por API mas adelante.

Estructura autonoma (no depende del arbol de Rols One):
  app.py             ← este archivo (solo rutas de Compras)
  shared/scripts/    ← modulos de datos (lanas_inventario, proveedores, ...)
  shared/data/       ← JSON seed; en produccion el runtime va a ROLS_DATA_DIR
  shared/static/     ← assets comunes servidos en /shared/ (sso-guard, lang-switcher)
  templates/, static/← UI de Compras
"""
from __future__ import annotations

import logging
import json
import os
import secrets
import sys
import time
from datetime import datetime
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
# Los modulos de datos viven en shared/scripts y localizan sus JSON en
# shared/data (parent.parent/data) o en ROLS_DATA_DIR si esta definido.
sys.path.insert(0, str(APP_DIR / "shared" / "scripts"))

from flask import Flask, render_template, request, jsonify, Response  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logging.getLogger("werkzeug").setLevel(logging.WARNING)
log = logging.getLogger("compras")

app = Flask(__name__)
app.config["TEMPLATES_AUTO_RELOAD"] = True
app.jinja_env.auto_reload = True

# --- Recursos compartidos (shared/static servido en /shared/ + nav) ---
import rols_shared  # noqa: E402
rols_shared.register_shared(app)

LOAD_TIME = time.time()


@app.route("/health")
def health():
    """Healthcheck del despliegue (Passenger/Plesk). No requiere login.
    El campo `version` sirve para verificar que un deploy ha surtido efecto."""
    return {"status": "ok", "app": "erp-produccion-compras",
            "auto_deploy": "on", "version": "1.0"}


@app.before_request
def _track_request_start():
    request._t0 = time.monotonic()


@app.after_request
def _track_request_end(response):
    elapsed_ms = (time.monotonic() - getattr(request, "_t0", time.monotonic())) * 1000
    endpoint = request.endpoint or "?"
    if endpoint and endpoint.startswith("api_"):
        log.info("%s %s -> %d (%.0fms)",
                 request.method, request.path, response.status_code, elapsed_ms)
    return response


@app.route("/")
def index():
    """Raiz → modulo de Compras (materias primas)."""
    return render_template("materias_primas.html")


def _user_rol() -> str | None:
    """Rol del usuario segun el SSO (header 'X-Rols-User-Rol', puesto por
    sso-guard.js via window.__rolsUser.rol). Filtro de UX, no de seguridad."""
    return (request.headers.get("X-Rols-User-Rol") or "").strip().lower() or None


def _user_name() -> str | None:
    """Username del usuario segun el SSO (header 'X-Rols-User-Name')."""
    return (request.headers.get("X-Rols-User-Name") or "").strip().lower() or None


# ============================================================
# API v1 — consumo por Rols One (escandallo de producto)
# ============================================================
# Este ERP es la FUENTE ÚNICA de verdad de las lanas. El escandallo de producto
# (que vive en Rols One) las consume por HTTP en vez de tener su propia copia:
#   GET  /api/v1/lanas                       → lista de calidades
#   GET  /api/v1/lanas/<calidad_id>/lotes    → lotes de una calidad
#   POST /api/v1/consumir                    → fabricar: descuenta kg de lotes
# Autenticado con un token compartido (X-Rols-Api-Token) para no exponer el
# inventario/costes en abierto. El token sale de ROLS_ERP_API_TOKEN o de un
# fichero erp_api_token.txt en ROLS_DATA_DIR. Sin token → API v1 cerrada.

def _erp_api_token() -> str | None:
    tok = os.environ.get("ROLS_ERP_API_TOKEN")
    if tok and tok.strip():
        return tok.strip()
    try:
        base = os.environ.get("ROLS_DATA_DIR") or str(APP_DIR / "shared" / "data")
        tok = (Path(base) / "erp_api_token.txt").read_text(encoding="utf-8").strip()
        return tok or None
    except OSError:
        return None


def _requiere_api_token():
    """403 si la petición no trae un X-Rols-Api-Token válido. Fail-closed: si no
    hay token configurado en el servidor, la API v1 queda cerrada."""
    expected = _erp_api_token()
    got = (request.headers.get("X-Rols-Api-Token") or "").strip()
    if not expected or not got or not secrets.compare_digest(got, expected):
        return jsonify({"error": "no autorizado (API v1)"}), 401
    return None


@app.route("/api/v1/lanas")
def api_v1_lanas():
    """Lista de calidades de lana (misma forma que /api/materias-primas/lanas).
    `_source` marca la procedencia (útil para verificar que el consumidor usa
    el ERP y no un fallback local)."""
    bl = _requiere_api_token()
    if bl:
        return bl
    mp = _mp_module()
    return jsonify({"lanas": mp.listar_lanas(), "_source": "erp-produccion"})


@app.route("/api/v1/lanas/<path:calidad_id>/lotes")
def api_v1_lanas_lotes(calidad_id):
    """Lotes de una calidad (para elegir de dónde consumir al fabricar)."""
    bl = _requiere_api_token()
    if bl:
        return bl
    mp = _mp_module()
    lana = mp.lana_por_id(calidad_id)
    if not lana:
        return jsonify({"error": f"calidad {calidad_id!r} no existe"}), 404
    return jsonify({"lotes": lana.get("lotes", []), "resumen": mp.resumen_lana(calidad_id)})


@app.route("/api/v1/consumir", methods=["POST"])
def api_v1_consumir():
    """Fabricación: consume kg de los lotes indicados (fuente única de stock).

    Body: {"consumos":[{"lana_id","lote","kg","nota"?}], "usuario"?, "ref"?, "m2"?}
    Valida saldos antes de ejecutar; si algo falla en la pre-validación no toca
    nada. Devuelve el detalle por consumo y el coste total. Es la lógica de
    fabricar que antes vivía en Rols One (ahora la ejecuta el dueño del stock)."""
    bl = _requiere_api_token()
    if bl:
        return bl
    mp = _mp_module()
    data = request.get_json(force=True, silent=True) or {}
    consumos = data.get("consumos") or []
    if not isinstance(consumos, list) or not consumos:
        return jsonify({"error": "Falta lista 'consumos' con al menos un item"}), 400
    ref = (data.get("ref") or "").strip()
    try:
        m2 = float(data.get("m2") or 0)
    except (TypeError, ValueError):
        m2 = 0
    usuario = (data.get("usuario") or "").strip()
    nota_base = (f"fabricacion ref {ref}" if ref else "fabricacion") + (f" ({m2:g} m2)" if m2 else "")

    # Pre-validación: todos los lotes existen y tienen saldo suficiente.
    errores_pre = []
    for c in consumos:
        lana_id = (c.get("lana_id") or "").strip()
        lote = (c.get("lote") or "").strip()
        try:
            kg = float(c.get("kg") or 0)
        except (TypeError, ValueError):
            kg = -1
        if not lana_id or not lote or kg <= 0:
            errores_pre.append({"lana_id": lana_id, "lote": lote, "error": "datos invalidos"})
            continue
        lana = mp.lana_por_id(lana_id)
        if not lana:
            errores_pre.append({"lana_id": lana_id, "lote": lote, "error": f"lana {lana_id!r} no existe"})
            continue
        lote_obj = next((l for l in (lana.get("lotes") or []) if l.get("lote") == lote), None)
        if not lote_obj:
            errores_pre.append({"lana_id": lana_id, "lote": lote, "error": f"lote {lote!r} no existe en esa lana"})
            continue
        saldo = float(lote_obj.get("cantidad_disponible_kg") or 0)
        if kg > saldo + 1e-6:
            errores_pre.append({"lana_id": lana_id, "lote": lote,
                                "error": f"saldo insuficiente ({saldo:g} kg < {kg:g} kg)"})
    if errores_pre:
        return jsonify({"error": "Validacion fallida antes de fabricar", "detalle": errores_pre}), 400

    # Ejecutar consumos uno a uno.
    resultado = []
    coste_total = 0.0
    for c in consumos:
        lana_id = c.get("lana_id"); lote = c.get("lote"); kg = float(c.get("kg"))
        nota = (c.get("nota") or "").strip() or nota_base
        lote_act, err = mp.consumir_lote(lana_id, lote, kg=kg, usuario=usuario, nota=nota)
        if err:
            resultado.append({"lana_id": lana_id, "lote": lote, "kg": kg, "ok": False, "error": err})
            continue
        coste = float(lote_act.get("coste_kg") or 0)
        coste_total += kg * coste
        resultado.append({"lana_id": lana_id, "lote": lote, "kg": kg, "ok": True,
                          "coste_kg": coste, "saldo_restante_kg": lote_act.get("cantidad_disponible_kg")})
    ok_global = all(r["ok"] for r in resultado)
    return jsonify({"ok": ok_global, "m2": m2, "ref": ref,
                    "consumos": resultado, "coste_total_eur": round(coste_total, 2)}), (200 if ok_global else 207)


# ============================================================
# Rutas de Compras (extraidas de rols-calculadora/app.py)
# ============================================================
# ============================================================
# Proveedores
# ============================================================

def _proveedores_module():
    rols_shared.ensure_shared_on_path()
    import proveedores as _p
    return _p


@app.route("/api/proveedores", methods=["GET", "POST"])
def api_proveedores():
    """GET → lista de proveedores con KPIs derivados.
    POST {nombre} → crea uno nuevo (solo con nombre, resto se rellena
    luego desde la ficha)."""
    bl = _bloquear_representante()
    if bl:
        return bl
    pm = _proveedores_module()
    if request.method == "GET":
        incluir_inactivos = (request.args.get("incluir_inactivos") or "1").lower() in ("1", "true", "yes")
        provs = pm.listar(incluir_inactivos=incluir_inactivos)
        # Anotar con KPIs
        for p in provs:
            p["_kpis"] = pm.kpis_proveedor(p["id"])
        return jsonify({"proveedores": provs})
    body = request.get_json(force=True, silent=True) or {}
    nuevo, err = pm.crear(body.get("nombre"))
    if err:
        return jsonify({"error": err}), 400
    return jsonify({"proveedor": nuevo}), 201


@app.route("/proveedor/<prov_id>")
def proveedor_detalle(prov_id):
    """Pagina dedicada de un proveedor (ficha completa + pedidos abiertos).
    Sustituye la antigua expansion inline del tab Proveedores."""
    bl = _bloquear_representante()
    if bl:
        return bl
    return render_template("proveedor_detalle.html", prov_id=prov_id)


@app.route("/api/proveedor/<prov_id>", methods=["GET", "PUT", "DELETE"])
def api_proveedor(prov_id):
    bl = _bloquear_representante()
    if bl:
        return bl
    pm = _proveedores_module()
    if request.method == "GET":
        p = pm.por_id(prov_id)
        if not p:
            return jsonify({"error": f"proveedor {prov_id!r} no existe"}), 404
        return jsonify({"proveedor": p, "kpis": pm.kpis_proveedor(prov_id)})
    if request.method == "DELETE":
        ok, err = pm.borrar(prov_id)
        if not ok:
            code = 404 if "no existe" in err else 409
            return jsonify({"error": err}), code
        return jsonify({"ok": True})
    body = request.get_json(force=True, silent=True) or {}
    actualizado, err = pm.actualizar(prov_id, body)
    if err:
        code = 404 if "no existe" in err else 400
        return jsonify({"error": err}), code
    return jsonify({"proveedor": actualizado})


@app.route("/api/proveedor/<prov_id>/detalle")
def api_proveedor_detalle(prov_id):
    """Devuelve TODO lo necesario para pintar la ficha de un proveedor:
    - proveedor: datos basicos (alias, contacto, direccion, etc.)
    - kpis: numero de calidades, stock total, pedidos abiertos
    - variantes: lista de variantes (calidad + proveedor) con su stock
    - pedidos_abiertos: pedidos en estado 'abierto' (en camino), con
      la calidad, kg, eur_kg, ETA, partido_previsto, fecha del pedido
    - pedidos_recientes: ultimos 10 pedidos cerrados (recibido/anulado)
      para tener el historial reciente a la vista
    """
    bl = _bloquear_representante()
    if bl:
        return bl
    pm = _proveedores_module()
    li = _lanas_inv_module()
    p = pm.por_id(prov_id)
    if not p:
        return jsonify({"error": f"proveedor {prov_id!r} no existe"}), 404
    # Resolver el alias para matchear contra lanas_inventario (las variantes
    # guardan el alias del proveedor, no su id)
    alias = (p.get("alias") or p.get("nombre") or "").upper()
    variantes_resumen = []
    pedidos_abiertos = []
    pedidos_recientes = []
    for v in li.listar_lanas():
        if (v.get("proveedor") or "").upper() != alias:
            continue
        # Historico de precios: entradas de partidos con coste_kg definido.
        # Los que tengan fecha entran al orden cronologico y se calculan
        # deltas. Los que no tengan fecha (datos legacy) tambien se muestran
        # pero al final, sin delta (no podemos saber su orden temporal).
        partidos_con_precio = []
        for p in (v.get("partidos") or []):
            coste = p.get("coste_kg")
            if coste is None:
                continue
            try:
                coste_f = float(coste)
            except (TypeError, ValueError):
                continue
            fecha = p.get("fecha_entrada") or p.get("fecha_compra") or ""
            partidos_con_precio.append({
                "partido":     p.get("partido"),
                "fecha":       fecha[:10] if isinstance(fecha, str) and fecha else "",
                "fecha_iso":   fecha,
                "coste_kg":    coste_f,
                "kg_inicial":  float(p.get("kg_inicial") or p.get("kg") or 0),
            })
        # Orden cronologico ascendente para calcular deltas. Los sin fecha
        # se quedan al principio (los consideramos "mas antiguos / desconocidos").
        partidos_con_precio.sort(key=lambda x: x.get("fecha") or "")
        historico_precios = []
        coste_prev = None
        for ev in partidos_con_precio:
            delta = None
            delta_pct = None
            if coste_prev is not None and coste_prev > 0:
                delta = round(ev["coste_kg"] - coste_prev, 4)
                delta_pct = round((delta / coste_prev) * 100, 2)
            historico_precios.append({
                **ev,
                "delta_eur":     delta,
                "delta_pct":     delta_pct,
            })
            coste_prev = ev["coste_kg"]
        # Para la fila principal: orden desc (mas reciente arriba)
        historico_precios.reverse()
        precio_actual = historico_precios[0]["coste_kg"] if historico_precios else None
        fecha_actual = historico_precios[0]["fecha"]    if historico_precios else None
        delta_actual = historico_precios[0]["delta_eur"] if historico_precios else None
        delta_actual_pct = historico_precios[0]["delta_pct"] if historico_precios else None
        # Tarifa actual: precio oficial del proveedor con su fecha.
        # Si tarifa_actual_eur_kg esta vacio, fallback a precio_2026/2025
        # (sin fecha — son datos importados). El campo es editable
        # desde la propia tabla y al guardar se setea la fecha de hoy.
        tarifa_val = v.get("tarifa_actual_eur_kg")
        tarifa_fecha = v.get("tarifa_actual_fecha")
        tarifa_fuente = "manual"
        if tarifa_val in (None, ""):
            for k in ("precio_2026", "precio_2025"):
                if v.get(k) not in (None, ""):
                    try:
                        tarifa_val = float(v.get(k))
                        tarifa_fuente = k
                        tarifa_fecha = None
                        break
                    except (TypeError, ValueError):
                        pass
        variantes_resumen.append({
            "id":              v.get("id"),
            "calidad_id":      v.get("calidad_id") or "",
            "titulo":          v.get("titulo") or "",
            "tipo":            v.get("tipo") or "",
            "nombre":          v.get("nombre") or
                               (f"{v.get('titulo','')} {v.get('tipo','')}").strip().upper(),
            "total_kg":        float(v.get("total_kg") or 0),
            "limite_kg":       float(v.get("limite_kg") or 0),
            "kg_a_pedir":      float(v.get("kg_a_pedir") or 0),
            # Precios: precio actual + delta vs anterior + historico completo
            "precio_actual":      precio_actual,
            "fecha_precio_actual": fecha_actual,
            "delta_precio_eur":   delta_actual,
            "delta_precio_pct":   delta_actual_pct,
            "historico_precios":  historico_precios,
            # Tarifa oficial (editable). Si fuente != "manual" significa
            # que viene del campo legacy precio_2026/precio_2025 (sin fecha).
            "tarifa_eur_kg":     tarifa_val,
            "tarifa_fecha":      tarifa_fecha,
            "tarifa_fuente":     tarifa_fuente,
        })
        # Pedidos de esta variante
        for ped in (v.get("pedidos") or []):
            estado = (ped.get("estado") or "").lower()
            entry = {
                "ref":              ped.get("ref"),
                "fecha":            (ped.get("fecha") or "")[:10],
                "fecha_iso":        ped.get("fecha"),
                "kg":               float(ped.get("kg") or 0),
                "eur_kg":           ped.get("eur_kg"),
                "importe":          ped.get("importe"),
                "partido_previsto": ped.get("partido_previsto") or "",
                "fecha_estimada":   ped.get("fecha_estimada_llegada"),
                "fecha_recibido":   ped.get("fecha_recibido"),
                "fecha_anulado":    ped.get("fecha_anulado"),
                "motivo_anulacion": ped.get("motivo_anulacion"),
                "estado":           estado,
                "variante_id":      v.get("id"),
                "calidad_id":       v.get("calidad_id") or "",
                "calidad_nombre":   (f"{v.get('titulo','')} {v.get('tipo','')}").strip(),
                "nota":             ped.get("nota") or "",
            }
            if estado == "abierto":
                pedidos_abiertos.append(entry)
            elif estado in ("recibido", "anulado"):
                pedidos_recientes.append(entry)
    # Ordenar abiertos por fecha desc, recientes por fecha_recibido/anulado desc
    pedidos_abiertos.sort(key=lambda x: x.get("fecha_iso") or "", reverse=True)
    pedidos_recientes.sort(
        key=lambda x: (x.get("fecha_recibido") or x.get("fecha_anulado")
                       or x.get("fecha_iso") or ""),
        reverse=True,
    )
    return jsonify({
        "proveedor":         p,
        "kpis":              pm.kpis_proveedor(prov_id),
        "variantes":         variantes_resumen,
        "pedidos_abiertos":  pedidos_abiertos,
        "pedidos_recientes": pedidos_recientes[:10],  # solo los 10 mas recientes
    })


@app.route("/api/proveedores/migrar", methods=["POST"])
def api_proveedores_migrar():
    """Crea registros vacios para cada proveedor que aparece en
    lanas_inventario.json y que no tiene ficha aun. Idempotente."""
    bl = _bloquear_representante()
    if bl:
        return bl
    pm = _proveedores_module()
    n = pm.migrar_desde_inventario()
    return jsonify({"creados": n})


# ============================================================
# Ficha detalle de una materia prima (calidad)
# ============================================================

@app.route("/materia-prima/<calidad_id>")
def materia_prima_detalle_view(calidad_id):
    """Pagina de ficha de una materia prima (calidad). El JS la rellena
    via /api/materia-prima/<id>.

    Caso especial: la calidad sintetica 'lana-en-crudo__generica' no
    existe en lanas_inventario.json (es una proyeccion). Redirigimos al
    tab "Lana en crudo" del listado, que es donde se gestiona.
    """
    if calidad_id == "lana-en-crudo__generica":
        from flask import redirect
        return redirect("/materias-primas#lana-cruda")
    return render_template("materia_prima_detalle.html", calidad_id=calidad_id)


def _catalogo_module():
    rols_shared.ensure_shared_on_path()
    import catalogo_materias as _cat
    return _cat


def _sincronizar_catalogo_titulos() -> int:
    """Anade al catalogo los titulos que esten en uso en alguna calidad
    pero falten del catalogo. Idempotente. Devuelve el numero anadido.

    Lo llamamos al arranque y desde un endpoint explicito (POST
    /api/catalogos/materia/sync) — NO desde el GET para que GET sea
    puro (sin efectos secundarios). Asi un GET no autorizado no
    puede mutar el catalogo.
    """
    cat = _catalogo_module()
    li = _lanas_inv_module()
    labels_existentes = {(it.get("label") or "").strip()
                         for it in cat.listar_titulos()}
    titulos_en_uso = set()
    for v in li.listar_lanas():
        t = (v.get("titulo") or "").strip()
        if t:
            titulos_en_uso.add(t)
    n = 0
    for t in sorted(titulos_en_uso - labels_existentes):
        try:
            cat.anadir("titulo", t)
            n += 1
        except Exception:
            pass
    return n


@app.route("/api/catalogos/materia", methods=["GET"])
def api_catalogo_materia():
    """Devuelve el catalogo completo: clasificaciones, materiales (felpa)
    y titulos. Lo usan los selects de la ficha y los filtros del listado.

    GET puro: NO muta nada. La sincronizacion de titulos con los datos
    se hace al arrancar la app y se puede forzar manualmente con
    POST /api/catalogos/materia/sync.

    Respuesta: {clasificaciones: [...], materiales_felpa: [...], titulos: [...]}
    """
    cat = _catalogo_module()
    return jsonify({
        "clasificaciones":  cat.listar_clasificaciones(),
        "materiales_felpa": cat.listar_materiales_felpa(),
        "titulos":          cat.listar_titulos(),
    })


@app.route("/api/catalogos/materia/sync", methods=["POST"])
def api_catalogo_materia_sync():
    """Fuerza la sincronizacion del catalogo con los titulos en uso en
    los datos. Util si has importado datos a mano o has migrado de otro
    sistema. Devuelve {anadidos: N}.

    Requiere permiso de compras (no es publico)."""
    bl = _bloquear_representante()
    if bl:
        return bl
    n = _sincronizar_catalogo_titulos()
    return jsonify({"anadidos": n})


@app.route("/api/catalogos/materia/<tipo>", methods=["POST"])
def api_catalogo_materia_anadir(tipo):
    """Anade una nueva entrada al catalogo. `tipo` ∈ {'clasificacion',
    'material_felpa', 'titulo'}. Body: {label}.

    Idempotente: si ya existe una con el mismo slug, devuelve la
    existente sin duplicar.
    """
    bl = _bloquear_representante()
    if bl:
        return bl
    body = request.get_json(force=True, silent=True) or {}
    label = (body.get("label") or "").strip()
    cat = _catalogo_module()
    nuevo, err = cat.anadir(tipo, label)
    if err:
        return jsonify({"error": err}), 400
    return jsonify(nuevo)


# Mapa tipo -> (campo en variante, "matcher"). El matcher decide si una
# variante usa este id del catalogo. Para clasif/material es comparacion
# directa por slug; para titulo es comparacion por label (porque el
# campo `titulo` en la variante guarda el label, no el slug).
def _catalogo_en_uso(tipo: str, id_: str, label_opt: str = "") -> list[dict]:
    """Devuelve [{calidad_id, titulo, tipo, proveedor}, ...] de las
    variantes que usan este `id_` del catalogo `tipo`. Lista vacia si
    no esta en uso."""
    li = _lanas_inv_module()
    if tipo == "clasificacion":
        match = lambda v: (v.get("clasificacion") or "") == id_
    elif tipo == "material_felpa":
        match = lambda v: (v.get("material_felpa") or "") == id_
    elif tipo == "titulo":
        # El campo `titulo` guarda el label literal. Buscamos por label.
        match = lambda v: (v.get("titulo") or "") == label_opt
    else:
        return []
    en_uso = []
    for v in li.listar_lanas():
        if match(v):
            en_uso.append({
                "calidad_id": v.get("calidad_id") or v.get("id"),
                "titulo":     v.get("titulo") or "",
                "tipo":       v.get("tipo") or "",
                "proveedor":  v.get("proveedor") or "",
            })
    return en_uso


@app.route("/api/catalogos/materia/<tipo>/<id_>", methods=["DELETE"])
def api_catalogo_materia_quitar(tipo, id_):
    """Elimina una entrada del catalogo. Solo si NO esta en uso por
    ninguna calidad — si lo esta, devuelve 409 con la lista de
    calidades afectadas."""
    bl = _bloquear_representante()
    if bl:
        return bl
    if tipo not in ("clasificacion", "material_felpa", "titulo"):
        return jsonify({"error": f"tipo invalido: {tipo!r}"}), 400
    cat = _catalogo_module()
    # Para titulo necesitamos el label (porque las variantes guardan el
    # label, no el slug). Lo buscamos en el catalogo.
    label = ""
    if tipo == "titulo":
        for it in cat.listar_titulos():
            if it.get("id") == id_:
                label = it.get("label") or ""
                break
    en_uso = _catalogo_en_uso(tipo, id_, label)
    if en_uso:
        return jsonify({
            "error": f"No se puede eliminar: {len(en_uso)} calidad(es) lo usan",
            "en_uso": en_uso,
        }), 409
    ok, err = cat.quitar(tipo, id_)
    if not ok:
        return jsonify({"error": err}), 400
    return jsonify({"ok": True, "id": id_})


@app.route("/api/materia-prima/<calidad_id>/titulo", methods=["PUT"])
def api_materia_prima_titulo(calidad_id):
    """Renombra el `titulo` de TODAS las variantes de una calidad.

    El id estable (`calidad_id` y `id`) NO cambia — solo el display.
    Body: {titulo}.
    """
    bl = _bloquear_representante()
    if bl:
        return bl
    body = request.get_json(force=True, silent=True) or {}
    titulo = (body.get("titulo") or "").strip()
    li = _lanas_inv_module()
    out, err = li.actualizar_titulo_calidad(calidad_id, titulo)
    if err:
        return jsonify({"error": err}), 400
    return jsonify(out)


@app.route("/api/materia-prima/<calidad_id>/tipo", methods=["PUT"])
def api_materia_prima_tipo(calidad_id):
    """Renombra el `tipo` (nombre comercial: 'australia', 'pais normal'...)
    en TODAS las variantes de la calidad. Body: {tipo}.

    Igual que titulo, el id estable (`calidad_id` y `id`) NO cambia —
    solo cambia el display."""
    bl = _bloquear_representante()
    if bl:
        return bl
    body = request.get_json(force=True, silent=True) or {}
    tipo = (body.get("tipo") or "").strip()
    li = _lanas_inv_module()
    out, err = li.actualizar_tipo_calidad(calidad_id, tipo)
    if err:
        return jsonify({"error": err}), 400
    return jsonify(out)


@app.route("/api/materia-prima/<calidad_id>/clasificacion", methods=["PUT"])
def api_materia_prima_clasificacion(calidad_id):
    """Asigna clasificacion (+ material_felpa cuando aplica) a nivel
    de calidad. Body: {clasificacion, material_felpa?}."""
    bl = _bloquear_representante()
    if bl:
        return bl
    body = request.get_json(force=True, silent=True) or {}
    li = _lanas_inv_module()
    out, err = li.actualizar_clasificacion_calidad(
        calidad_id,
        body.get("clasificacion") or "",
        body.get("material_felpa") or None,
    )
    if err:
        return jsonify({"error": err}), 400
    return jsonify(out)


@app.route("/api/materia-prima/<calidad_id>/planificacion", methods=["PUT"])
def api_materia_prima_planificacion(calidad_id):
    """Edita limite_kg o kg_a_pedir a nivel de CALIDAD (la suma se
    reparte entre las variantes). Body: {campo, valor}."""
    bl = _bloquear_representante()
    if bl:
        return bl
    body = request.get_json(force=True, silent=True) or {}
    campo = (body.get("campo") or "").strip()
    valor = body.get("valor")
    if not campo:
        return jsonify({"error": "falta campo"}), 400
    li = _lanas_inv_module()
    out, err = li.actualizar_planificacion_calidad(calidad_id, campo, valor)
    if err:
        return jsonify({"error": err}), 400
    return jsonify(out)


@app.route("/api/materia-prima/<calidad_id>/proveedor", methods=["POST"])
def api_materia_prima_anadir_proveedor(calidad_id):
    """Crea una variante nueva (sin partidos) para esta calidad con el
    proveedor indicado. Body: {proveedor, usuario?}."""
    bl = _bloquear_representante()
    if bl:
        return bl
    body = request.get_json(force=True, silent=True) or {}
    prov = (body.get("proveedor") or "").strip()
    if not prov:
        return jsonify({"error": "falta proveedor"}), 400
    usuario = (body.get("usuario")
               or request.headers.get("X-Rols-User") or "").strip()
    li = _lanas_inv_module()
    nueva, err = li.anadir_proveedor_a_calidad(calidad_id, prov, usuario=usuario)
    if err:
        return jsonify({"error": err}), 400
    return jsonify({"variante": nueva}), 201


@app.route("/api/materia-prima/<calidad_id>/proveedor/<path:proveedor>",
           methods=["DELETE"])
def api_materia_prima_quitar_proveedor(calidad_id, proveedor):
    """Elimina la variante (calidad+proveedor) de la calidad.

    Query / body:
      forzar=1  → salta las salvaguardas (kg vivo, pedidos abiertos).
      usuario   → para auditoria.
    """
    bl = _bloquear_representante()
    if bl:
        return bl
    body = request.get_json(force=True, silent=True) or {}
    forzar = (str(body.get("forzar") or request.args.get("forzar") or "")
              .strip().lower() in ("1", "true", "yes"))
    usuario = (body.get("usuario")
               or request.args.get("usuario")
               or request.headers.get("X-Rols-User") or "").strip()
    li = _lanas_inv_module()
    ok, err = li.quitar_proveedor_de_calidad(
        calidad_id, proveedor, forzar=forzar, usuario=usuario)
    if not ok:
        return jsonify({"error": err}), 400
    return jsonify({"ok": True})


@app.route("/api/materia-prima/<calidad_id>", methods=["DELETE"])
def api_materia_prima_borrar(calidad_id):
    """Borra una calidad entera (todas sus variantes y partidos).

    Query / body:
      forzar=1  → salta las salvaguardas (kg vivo, pedidos abiertos).
      usuario   → para auditoria.

    Pensado para limpiar materias primas creadas por error o que ya no
    se usan. Si la calidad tiene kg vivos o pedidos abiertos, devuelve
    400 con un mensaje explicativo y la UI debe pedir confirmacion
    explicita antes de reintentar con `forzar=1`.
    """
    bl = _requiere("compras")
    if bl:
        return bl
    body = request.get_json(force=True, silent=True) or {}
    forzar = (str(body.get("forzar") or request.args.get("forzar") or "")
              .strip().lower() in ("1", "true", "yes"))
    usuario = (body.get("usuario")
               or request.args.get("usuario")
               or request.headers.get("X-Rols-User") or "").strip()
    li = _lanas_inv_module()
    ok, err = li.borrar_calidad(calidad_id, forzar=forzar, usuario=usuario)
    if not ok:
        return jsonify({"error": err}), 400
    return jsonify({"ok": True})


@app.route("/api/materia-prima/<calidad_id>")
def api_materia_prima_detalle(calidad_id):
    """Devuelve TODO lo necesario para pintar la ficha:
    - calidad: {calidad_id, titulo, tipo, variantes}
    - lotes:   union de partidos fisicos + pedidos abiertos (cada uno con
               estado_intrinseco activo/agotado y ubicacion en-almacen/en-camino)
    - precios: histórico cronologico [{fecha, eur_kg, partido, proveedor, origen}]
    - consumos: movimientos tipo salida de las variantes de esta calidad
    """
    bl = _bloquear_representante()
    if bl:
        return bl
    li = _lanas_inv_module()
    mi = _movs_module()
    li.invalidar_cache()
    mi.invalidar_cache()
    cal = li.calidad_por_id(calidad_id)
    if not cal:
        return jsonify({"error": f"calidad {calidad_id!r} no existe"}), 404

    # Variantes completas (con todos los campos del JSON, no solo el subset
    # que devuelve listar_calidades).
    all_lanas = li.listar_lanas()
    variantes_full = [v for v in all_lanas if v.get("calidad_id") == calidad_id]
    variante_ids = [v.get("id") for v in variantes_full]

    # ---- LOTES UNIFICADOS ----
    lotes = []
    historico_precios = []
    for v in variantes_full:
        prov = v.get("proveedor") or ""
        # Partidos fisicos
        for p in (v.get("partidos") or []):
            kg = float(p.get("kg") or 0)
            lotes.append({
                "tipo":               "fisico",
                "variante_id":        v.get("id"),
                "proveedor":          prov,
                "partido":            p.get("partido"),
                "kg":                 kg,
                # kg_proveedor: parte del partido que el proveedor sigue
                # guardando en su almacen (reservado para nosotros pero no
                # transportado todavia). Se considera stock disponible
                # porque podemos pedirlo en cualquier momento, pero vive
                # en su propio campo para que la UI lo muestre separado.
                "kg_proveedor":       float(p.get("kg_proveedor") or 0),
                "kg_inicial":         p.get("kg_inicial"),
                "coste_kg":           p.get("coste_kg"),
                "fecha_entrada":      p.get("fecha_entrada"),
                "fecha_compra":       p.get("fecha_compra"),
                "fecha_agotado":      p.get("fecha_agotado"),
                "estanteria":         p.get("estanteria"),
                "observaciones":      p.get("observaciones"),
                "estado_intrinseco":  "agotado" if (kg + float(p.get("kg_proveedor") or 0)) <= 0 else "activo",
                "ubicacion":          "en-almacen",
                "ref_pedido":         None,
                "fecha_estimada":     None,
            })
            if p.get("coste_kg") is not None:
                historico_precios.append({
                    "fecha":     p.get("fecha_entrada"),
                    "eur_kg":    float(p["coste_kg"]),
                    "partido":   p.get("partido"),
                    "proveedor": prov,
                    "origen":    "entrada partido",
                })
        # Pedidos abiertos como "lotes en camino"
        for ped in (v.get("pedidos") or []):
            if (ped.get("estado") or "").lower() != "abierto":
                continue
            # fecha del pedido (cuando se curso) → columna "Fecha compra"
            # de la tabla. Almacenado como ISO completo; recortamos al
            # YYYY-MM-DD para que la UI lo formatee bien.
            fecha_pedido_iso = (ped.get("fecha") or "")[:10] or None
            lotes.append({
                "tipo":               "pedido_abierto",
                "variante_id":        v.get("id"),
                "proveedor":          prov,
                "partido":            ped.get("partido_previsto") or "(sin confirmar)",
                "kg":                 float(ped.get("kg") or 0),
                "coste_kg":           ped.get("eur_kg"),
                "fecha_entrada":      None,            # aun no ha llegado
                "fecha_compra":       fecha_pedido_iso,  # cuando se curso el pedido
                "observaciones":      ped.get("nota"),
                "estado_intrinseco":  "activo",
                "ubicacion":          "en-camino",
                "ref_pedido":         ped.get("ref"),
                "fecha_estimada":     ped.get("fecha_estimada_llegada"),
            })
        # Pedidos recibidos también aportan al historico de precios
        for ped in (v.get("pedidos") or []):
            if (ped.get("estado") or "").lower() == "recibido" and ped.get("eur_kg") is not None:
                historico_precios.append({
                    "fecha":     ped.get("fecha_recibido") or ped.get("fecha"),
                    "eur_kg":    float(ped["eur_kg"]),
                    "partido":   ped.get("partido_previsto"),
                    "proveedor": prov,
                    "origen":    f"pedido {ped.get('ref') or ''}".strip(),
                })

    # Orden: en-camino primero (mas relevante), luego activos por fecha
    # DESCENDENTE (mas reciente arriba), luego agotados al final.
    #
    # La fecha que se usa para ordenar es la "mas reciente que aplica" al
    # partido:
    #   - en-almacen: fecha_entrada (cuando llego)
    #   - en-camino:  fecha_compra (cuando se curso el pedido)
    #   - fallback:   fecha_estimada (ETA)
    # Asi un pedido recien cursado y un partido recien recibido suben
    # arriba; lo viejo siempre se queda abajo.
    #
    # Antes habia un truco con [::-1] para conseguir orden descendente
    # con sort asc, pero invertir el string ISO no da orden cronologico
    # real (compara letra a letra). Ahora usamos el ordinal del date
    # negado: cuanto mas reciente sea la fecha, menor (mas negativo) es
    # el key, asi sort asc deja lo nuevo arriba.
    from datetime import datetime as _dt
    def _key_fecha_desc(l):
        fecha = (l.get("fecha_entrada")
                 or l.get("fecha_compra")
                 or l.get("fecha_estimada")
                 or "")
        if not fecha:
            return 0  # sin fecha → al final del subgrupo (key mas grande que cualquier negativo)
        try:
            return -_dt.strptime(fecha[:10], "%Y-%m-%d").toordinal()
        except (ValueError, TypeError):
            return 0
    orden_ubic = {"en-camino": 0, "en-almacen": 1}
    orden_est  = {"activo": 0, "agotado": 1}
    lotes.sort(key=lambda l: (
        orden_ubic.get(l["ubicacion"], 2),
        orden_est.get(l["estado_intrinseco"], 2),
        _key_fecha_desc(l),
    ))

    # Histórico precios: orden cronologico ascendente
    historico_precios.sort(key=lambda x: (x.get("fecha") or ""))

    # ---- MOVIMIENTOS DE CONSUMO ----
    # Filtramos movimientos cuya lana_id (variante_id en realidad) este
    # en variante_ids. Incluimos:
    #   - tipo "salida"  (consumo registrado por la calc al producir)
    #   - tipo "ajuste" (cualquier signo): tanto los negativos
    #     (correccion a la baja / merma) como los positivos (recuento,
    #     mercancia encontrada). El usuario quiere ver los dos juntos en
    #     "Historico de movimientos" para tener trazabilidad completa de
    #     por que el stock cambia.
    # Excluimos "entrada" (alta de partido nuevo) — esa ya aparece en
    # la tabla "Partidos" y en "Historico de precios".
    movs_all = mi.listar()
    consumos = []
    for m in movs_all:
        if m.get("lana_id") not in variante_ids:
            continue
        tipo = (m.get("tipo") or "").lower()
        cant = float(m.get("cantidad_kg") or 0)
        # tipos visibles en "historico de movimientos" de la ficha:
        #   - salida: consumo (negativo)
        #   - ajuste: reajuste manual (cualquier signo)
        # Excluimos "traslado" (mover kg Rols ↔ proveedor): no cambia
        # el saldo total del partido, solo reparte entre las dos
        # ubicaciones — ensuciaba el historico con movimientos que no
        # son ni consumo ni ajuste reales del inventario.
        if tipo == "salida" or tipo == "ajuste":
            # cant == 0: ajuste no-op (el usuario abrio el modal y solo
            # toco observaciones / fechas / etc). No lo mostramos para
            # no llenar la tabla de movimientos vacios.
            if tipo == "ajuste" and cant == 0:
                continue
            prov = next((v.get("proveedor") for v in variantes_full
                        if v.get("id") == m.get("lana_id")), "")
            consumos.append({**m, "proveedor": prov})
    # Orden cronologico descendente (mas reciente primero)
    consumos.sort(key=lambda x: (x.get("fecha") or ""), reverse=True)

    # Sumas a nivel calidad (las variantes guardan su propio valor)
    suma_limite = sum(float(v.get("limite_kg") or 0) for v in variantes_full)
    suma_pedir  = sum(float(v.get("kg_a_pedir") or 0) for v in variantes_full)
    # Clasificacion: coherente entre variantes de la misma calidad — tomamos
    # la de la primera (asumimos consistencia).
    primera = variantes_full[0] if variantes_full else {}
    return jsonify({
        "calidad": {
            "calidad_id":     cal["calidad_id"],
            "titulo":         cal["titulo"],
            "tipo":           cal["tipo"],
            "material":       cal["material"],
            "total_kg":       cal["total_kg"],
            "coste_medio_kg": cal["coste_medio_kg"],
            "limite_kg":      round(suma_limite, 2),
            "kg_a_pedir":     round(suma_pedir, 2),
            "clasificacion":  primera.get("clasificacion") or "",
            "material_felpa": primera.get("material_felpa") or "",
        },
        "variantes": variantes_full,
        "lotes":     lotes,
        "precios":   historico_precios,
        "consumos":  consumos[:200],   # limite generoso
    })


# ============================================================
# Materias primas (lanas, tintes, ...)
# ============================================================

# Importamos la API compartida bajo demanda para no acoplar el modulo
# en arranque (asi si shared no esta presente, calc sigue funcionando).
def _mp_module():
    rols_shared.ensure_shared_on_path()
    import materias_primas as _mp
    return _mp


@app.route("/materias-primas")
def materias_primas_view():
    """Pagina de gestion de materias primas (de momento solo lanas)."""
    return render_template("materias_primas.html")


@app.route("/api/materias-primas/lanas", methods=["GET", "POST"])
def api_lanas():
    """GET: lista de materias primas (todas las calidades).
    POST: crea una calidad placeholder con solo el nombre. El usuario
    rellena clasificacion / material / titulo / proveedores despues
    desde la ficha (/materia-prima/<calidad_id>).
    """
    bl = _requiere("compras")
    if bl: return bl
    mp = _mp_module()
    if request.method == "GET":
        return jsonify({"lanas": mp.listar_lanas()})
    data = request.get_json(force=True, silent=True) or {}
    nueva, err = mp.crear_lana(
        data.get("titulo") or "",
        data.get("tipo") or data.get("nombre") or "",
        data.get("material") or "lana",
    )
    if err:
        return jsonify({"error": err}), 400
    # nueva = {calidad_id, variante_id}
    return jsonify({"calidad_id": nueva["calidad_id"]}), 201



@app.route("/api/materias-primas/lanas/<lana_id>", methods=["PUT", "DELETE"])
def api_lanas_item(lana_id):
    bl = _requiere("compras")
    if bl: return bl
    mp = _mp_module()
    if request.method == "DELETE":
        ok, err = mp.borrar_lana(lana_id)
        if not ok:
            return jsonify({"error": err}), 404 if "no existe" in err else 400
        return jsonify({"ok": True})
    # PUT -> actualizar
    data = request.get_json(force=True, silent=True) or {}
    actualizada, err = mp.actualizar_lana(
        lana_id, data.get("titulo"), data.get("tipo"),
        data.get("material") or "lana",
    )
    if err:
        return jsonify({"error": err}), 400
    return jsonify({"lana": actualizada})


# ----- Lotes de cada lana -----

@app.route("/api/materias-primas/lanas/<lana_id>/lotes", methods=["GET", "POST"])
def api_lotes(lana_id):
    bl = _requiere("compras")
    if bl: return bl
    mp = _mp_module()
    if request.method == "GET":
        lana = mp.lana_por_id(lana_id)
        if not lana:
            return jsonify({"error": "Lana no existe"}), 404
        return jsonify({
            "lotes":   lana.get("lotes", []),
            "resumen": mp.resumen_lana(lana_id),
        })
    # POST -> agregar lote
    data = request.get_json(force=True, silent=True) or {}
    nuevo, err = mp.agregar_lote(
        lana_id,
        data.get("lote"),
        data.get("cantidad_disponible_kg"),
        data.get("coste_kg"),
        data.get("fecha_entrada"),
        usuario=(data.get("usuario") or "").strip(),
        proveedor=(data.get("proveedor") or "").strip(),
    )
    if err:
        return jsonify({"error": err}), 400
    return jsonify({"lote": nuevo, "resumen": mp.resumen_lana(lana_id)}), 201


@app.route("/api/materias-primas/lanas/<lana_id>/lotes/<lote_ref>",
           methods=["PUT", "DELETE"])
def api_lotes_item(lana_id, lote_ref):
    bl = _requiere("compras")
    if bl: return bl
    mp = _mp_module()
    if request.method == "DELETE":
        # DELETE puede recibir usuario en query string (al no llevar body
        # estructurado los clientes browser) o en body si lo trae.
        body = request.get_json(force=True, silent=True) or {}
        usuario = (body.get("usuario") or request.args.get("usuario") or "").strip()
        proveedor = (body.get("proveedor") or request.args.get("proveedor") or "").strip()
        ok, err = mp.borrar_lote(lana_id, lote_ref, usuario=usuario, proveedor=proveedor)
        if not ok:
            return jsonify({"error": err}), 400
        return jsonify({"ok": True, "resumen": mp.resumen_lana(lana_id)})
    data = request.get_json(force=True, silent=True) or {}
    # Solo enviamos los campos que vengan en el body: asi el caller
    # puede editar solo observaciones (o solo kg, etc.) sin pisar el
    # resto. Las keys ausentes se preservan en el partido existente.
    kwargs: dict = {
        "usuario":   (data.get("usuario") or "").strip(),
        "proveedor": (data.get("proveedor") or "").strip(),
    }
    if "lote" in data:                   kwargs["lote_ref_nuevo"] = data.get("lote") or lote_ref
    if "cantidad_disponible_kg" in data: kwargs["cantidad_kg"]    = data.get("cantidad_disponible_kg")
    # kg_proveedor: parte del partido que sigue en el almacen del proveedor
    if "kg_proveedor" in data:           kwargs["kg_proveedor"]   = data.get("kg_proveedor")
    if "coste_kg" in data:               kwargs["coste_kg"]       = data.get("coste_kg")
    if "fecha_entrada" in data:          kwargs["fecha_entrada"]  = data.get("fecha_entrada")
    if "observaciones" in data:          kwargs["observaciones"]  = data.get("observaciones")
    if "estanteria" in data:             kwargs["estanteria"]     = data.get("estanteria")
    if "fecha_compra" in data:           kwargs["fecha_compra"]   = data.get("fecha_compra")
    actualizado, err = mp.actualizar_lote(lana_id, lote_ref, **kwargs)
    if err:
        return jsonify({"error": err}), 400
    return jsonify({"lote": actualizado, "resumen": mp.resumen_lana(lana_id)})


# ----- Consumo (salida) de un lote concreto -----

@app.route("/api/materias-primas/lanas/<lana_id>/lotes/<lote_ref>/consumir",
           methods=["POST"])
def api_lotes_consumir(lana_id, lote_ref):
    """Consume kg de un lote seleccionado manualmente.

    Body JSON: {"kg": 5.5, "nota": "fabricacion ref X 2 m2"} (nota opcional).

    Util para empezar a probar el flujo de descontar inventario; despues
    se enganchara con el escandallo del producto para que el flujo de
    fabricacion pida los kg de cada materia prima del lote seleccionado.
    """
    bl = _requiere("compras")
    if bl: return bl
    mp = _mp_module()
    data = request.get_json(force=True, silent=True) or {}
    lote_act, err = mp.consumir_lote(
        lana_id, lote_ref,
        kg=data.get("kg"),
        usuario=(data.get("usuario") or "").strip(),
        nota=data.get("nota") or "",
        proveedor=(data.get("proveedor") or "").strip(),
    )
    if err:
        return jsonify({"error": err}), 400
    return jsonify({"lote": lote_act, "resumen": mp.resumen_lana(lana_id)})


# ----- Traslado de kg entre almacen Rols y almacen del proveedor -----

@app.route("/api/materias-primas/lanas/<lana_id>/lotes/<lote_ref>/trasladar",
           methods=["POST"])
def api_lotes_trasladar(lana_id, lote_ref):
    """Mueve kg entre las dos ubicaciones del MISMO partido (mismo nº lote).

    Body JSON:
        {
          "kg": 200,
          "direccion": "a-proveedor" | "a-rols",
          "proveedor": "COBO",   # opcional, desambigua multi-proveedor
          "nota": "comentario opcional",
          "usuario": "fernando"
        }

    No cambia el total del partido (kg + kg_proveedor), solo el reparto.
    Registra un movimiento de tipo "traslado" en el historico.
    """
    bl = _requiere("compras")
    if bl: return bl
    mp = _mp_module()
    data = request.get_json(force=True, silent=True) or {}
    lote_act, err = mp.trasladar_lote(
        lana_id, lote_ref,
        kg=data.get("kg"),
        direccion=(data.get("direccion") or "").strip(),
        usuario=(data.get("usuario") or "").strip(),
        nota=data.get("nota") or "",
        proveedor=(data.get("proveedor") or "").strip(),
    )
    if err:
        return jsonify({"error": err}), 400
    return jsonify({"lote": lote_act, "resumen": mp.resumen_lana(lana_id)})


# ----- Vista global de lotes -----

@app.route("/api/materias-primas/lotes")
def api_lotes_global():
    """Listado plano de todos los lotes de todas las lanas. Query params:
    - incluir_agotados=1 -> incluye lotes con kg<=0 (por defecto los oculta).
    - lana_id=<id>       -> filtra por una lana concreta (servidor-side).
    """
    bl = _requiere("compras")
    if bl: return bl
    mp = _mp_module()
    incluir = (request.args.get("incluir_agotados") or "").lower() in ("1", "true", "yes")
    data = mp.listar_lotes_global(incluir_agotados=incluir)
    lana_id = (request.args.get("lana_id") or "").strip()
    if lana_id:
        data["lotes"] = [l for l in data["lotes"] if l.get("lana_id") == lana_id]
    return jsonify(data)


# ----- Inventario operativo de lanas (estilo Alberto) -----

def _lanas_inv_module():
    rols_shared.ensure_shared_on_path()
    import lanas_inventario as _li
    return _li


# Fallback por rol cuando el modulo permisos no esta disponible o falla.
# Refleja el comportamiento historico antes de permisos.json.
_FALLBACK_POR_ROL = {
    "admin": {"compras": True, "calcular_presupuestos": True,
              "ver_presupuestos_todos": True,
              "editar_ficha_producto": True, "gestion_usuarios": True,
              "ver_stock_activo": True, "ver_productos_discontinuados": True,
              "ver_colecciones_cliente": True},
    "comercial": {"compras": True, "calcular_presupuestos": True,
                  "ver_presupuestos_todos": False,
                  "editar_ficha_producto": True, "gestion_usuarios": False,
                  "ver_stock_activo": True, "ver_productos_discontinuados": True,
                  "ver_colecciones_cliente": True},
    "representante": {"compras": False, "calcular_presupuestos": True,
                      "ver_presupuestos_todos": False,
                      "editar_ficha_producto": False, "gestion_usuarios": False,
                      "ver_stock_activo": True, "ver_productos_discontinuados": False,
                      "ver_colecciones_cliente": False},
}


def _puede(permiso: str) -> bool:
    """¿El rol actual tiene `permiso`? Lee del modulo compartido
    `shared/scripts/permisos`. Si no esta disponible o no hay rol, deja
    pasar (backwards-compat con scripts server-to-server sin header)."""
    rol = _user_rol()
    if not rol:
        return True  # sin header de rol → permisivo (calls internos)
    try:
        rols_shared.ensure_shared_on_path()
        import permisos as _perm
        return _perm.puede(rol, permiso)
    except Exception:
        # Si falla cargando permisos.json, usamos los defaults estaticos
        return _FALLBACK_POR_ROL.get(rol, {}).get(permiso, False)


def _puede_compras() -> bool:
    """Alias historico — `compras` es el permiso mas usado."""
    return _puede("compras")


def _requiere(permiso: str):
    """Devuelve un Response 403 si el usuario no tiene `permiso`.
    None si si lo tiene. Pattern de uso en cada endpoint:
        bl = _requiere("compras")
        if bl: return bl
    """
    if not _puede(permiso):
        return jsonify({"error": f"no autorizado: falta permiso {permiso!r}"}), 403
    return None


def _bloquear_representante():
    """Alias historico de _requiere('compras'). Mantenido para no romper
    los call sites existentes — los nuevos usar _requiere(permiso)."""
    return _requiere("compras")


@app.route("/api/lanas-inventario")
def api_lanas_inventario():
    """Lista de lanas operativas con estadisticas en cabecera.
    Bloqueado para rol=representante."""
    bl = _bloquear_representante()
    if bl:
        return bl
    li = _lanas_inv_module()
    li.invalidar_cache()
    return jsonify({
        "lanas":         li.listar_lanas(),
        "basamentos":    li.listar_basamentos(),
        "backings":      li.listar_backings(),
        "estadisticas":  li.estadisticas(),
    })


@app.route("/api/lanas-inventario/<lid>/campo", methods=["PUT"])
def api_lanas_inventario_campo(lid):
    """Actualiza un campo editable de una lana:
    {campo: 'limite_kg' | 'kg_a_pedir' | 'pedido_hecho' | 'observaciones'
            | 'precio_2025' | 'precio_2026',
     valor: any}
    """
    bl = _bloquear_representante()
    if bl:
        return bl
    li = _lanas_inv_module()
    body = request.get_json(force=True, silent=True) or {}
    campo = (body.get("campo") or "").strip()
    valor = body.get("valor")
    actualizado, err = li.actualizar_lana(lid, campo, valor)
    if err:
        return jsonify({"error": err}), 400
    return jsonify({"lana": actualizado, "estadisticas": li.estadisticas()})


@app.route("/api/lanas-inventario/<lid>/partidos", methods=["PUT"])
def api_lanas_inventario_partidos(lid):
    """Sustituye la lista entera de partidos de una lana. Recalcula
    total_kg automaticamente. Body: {partidos: [{partido, kg}, ...]}."""
    bl = _bloquear_representante()
    if bl:
        return bl
    li = _lanas_inv_module()
    body = request.get_json(force=True, silent=True) or {}
    actualizado, err = li.actualizar_partidos(lid, body.get("partidos") or [])
    if err:
        return jsonify({"error": err}), 400
    return jsonify({"lana": actualizado, "estadisticas": li.estadisticas()})


# ----- Movimientos (historico) -----

def _movs_module():
    rols_shared.ensure_shared_on_path()
    import movimientos_inventario as _m
    return _m


@app.route("/api/materias-primas/movimientos")
def api_movimientos():
    """Listado de movimientos de inventario, filtrable.

    Query params (todos opcionales):
    - lana_id, lote, tipo (entrada|ajuste|borrado)
    - desde, hasta (YYYY-MM-DD)
    - limit (int, default sin limite)
    """
    mi = _movs_module()
    mi.invalidar_cache()
    movs = mi.listar(
        lana_id=request.args.get("lana_id") or None,
        lote=request.args.get("lote") or None,
        tipo=request.args.get("tipo") or None,
        desde=request.args.get("desde") or None,
        hasta=request.args.get("hasta") or None,
        limit=int(request.args.get("limit")) if request.args.get("limit") else None,
    )
    return jsonify({"movimientos": movs, "total": len(movs)})


# ============================================================
# Lana en crudo (lana sin hilar, vive en almacen de hiladores)
# ============================================================

def _lana_cruda_module():
    rols_shared.ensure_shared_on_path()
    import lana_cruda as _lc
    return _lc


@app.route("/api/lana-cruda", methods=["GET"])
def api_lana_cruda_listar():
    """GET → contenedores + estadisticas para pintar el tab "Lana en crudo".
    Filtra por hilador via ?hilador=COBO si se pasa."""
    bl = _requiere("compras")
    if bl:
        return bl
    lc = _lana_cruda_module()
    lc.invalidar_cache()
    incluir_agotados = (request.args.get("incluir_agotados") or "1").lower() in ("1", "true", "yes")
    contenedores = lc.listar_contenedores(incluir_agotados=incluir_agotados)
    hilador_f = (request.args.get("hilador") or "").strip().upper()
    if hilador_f:
        contenedores = [c for c in contenedores
                        if (c.get("hilador_actual") or "").upper() == hilador_f]
    # Tambien devolvemos las ordenes pendientes (estado='pendiente')
    # para pintar la seccion "Ordenes en hilado" en la cabecera del tab.
    todas_ordenes = lc.listar_movimientos_hilado()
    pendientes = [o for o in todas_ordenes
                  if (o.get("estado") or "").lower() == "pendiente"]
    return jsonify({
        "contenedores":      contenedores,
        "estadisticas":      lc.estadisticas(),
        "ordenes_pendientes": pendientes,
    })


@app.route("/api/lana-cruda/contenedores", methods=["POST"])
def api_lana_cruda_crear_contenedor():
    """POST → registra un contenedor nuevo de lana en crudo.
    Body: {ref, hilador_actual, kg_inicial, coste_kg, fecha_compra?,
           fecha_llegada_hilador?, proveedor_origen?, observaciones?}.
    """
    bl = _requiere("compras")
    if bl:
        return bl
    body = request.get_json(force=True, silent=True) or {}
    usuario = (request.headers.get("X-Rols-User") or "").strip()
    lc = _lana_cruda_module()
    nuevo, err = lc.crear_contenedor(
        ref=                  body.get("ref") or "",
        hilador_actual=       body.get("hilador_actual") or "",
        kg_inicial=           body.get("kg_inicial"),
        coste_kg=             body.get("coste_kg"),
        fecha_compra=         body.get("fecha_compra") or "",
        fecha_llegada_hilador=body.get("fecha_llegada_hilador") or "",
        proveedor_origen=     body.get("proveedor_origen") or "",
        observaciones=        body.get("observaciones") or "",
        usuario=              usuario,
    )
    if err:
        return jsonify({"error": err}), 400
    return jsonify({"contenedor": nuevo}), 201


@app.route("/api/lana-cruda/contenedores/<cid>", methods=["GET", "PUT", "DELETE"])
def api_lana_cruda_contenedor(cid):
    """GET → ficha del contenedor + sus ordenes de hilado.
    PUT  → actualiza campos editables (ref, hilador_actual, coste_kg,
           fechas, proveedor_origen, observaciones).
    DELETE → borra el contenedor (bloqueado si kg_actual > 0 sin forzar).
    """
    bl = _requiere("compras")
    if bl:
        return bl
    lc = _lana_cruda_module()
    lc.invalidar_cache()
    if request.method == "GET":
        c = lc.contenedor_por_id(cid)
        if not c:
            return jsonify({"error": f"contenedor {cid!r} no existe"}), 404
        ordenes = lc.listar_movimientos_hilado(contenedor_id=cid)
        return jsonify({"contenedor": c, "ordenes_hilado": ordenes})
    usuario = (request.headers.get("X-Rols-User") or "").strip()
    if request.method == "PUT":
        body = request.get_json(force=True, silent=True) or {}
        actualizado, err = lc.actualizar_contenedor(cid, body, usuario=usuario)
        if err:
            return jsonify({"error": err}), 400
        return jsonify({"contenedor": actualizado})
    # DELETE
    forzar = (str(request.args.get("forzar") or "")
              .strip().lower() in ("1", "true", "yes"))
    ok, err = lc.borrar_contenedor(cid, forzar=forzar, usuario=usuario)
    if not ok:
        return jsonify({"error": err}), 400
    return jsonify({"ok": True})


@app.route("/api/lana-cruda/apartar", methods=["POST"])
def api_lana_cruda_apartar():
    """POST → aparta kg de uno o varios contenedores para hilar.
    Crea una orden en estado "pendiente". El partido en la calidad
    hilada NO se crea aun — se hace al cerrar la orden con los kg
    hilados reales.

    Body:
      {
        "contenedores_consumo": [{"contenedor_id": "...", "kg": 1000}, ...],
        "calidad_destino_id":   "65-2c__pais-normal",
        "hilador":              "COBO",
        "partido_ref":          "4923C"  (opcional, se puede rellenar al cerrar),
        "fecha_orden":          "2026-05-25",
        "nota":                 ""
      }
    """
    bl = _requiere("compras")
    if bl:
        return bl
    body = request.get_json(force=True, silent=True) or {}
    usuario = (request.headers.get("X-Rols-User") or "").strip()
    lc = _lana_cruda_module()
    orden, err = lc.apartar_para_hilar(
        contenedores_consumo=  body.get("contenedores_consumo") or [],
        calidad_destino_id=    body.get("calidad_destino_id") or "",
        hilador=               body.get("hilador") or "",
        partido_ref=           body.get("partido_ref") or "",
        fecha_orden=           body.get("fecha_orden") or "",
        usuario=               usuario,
        nota=                  body.get("nota") or "",
    )
    if err:
        return jsonify({"error": err}), 400
    return jsonify({"orden": orden}), 201


@app.route("/api/lana-cruda/ordenes/<oid>/cerrar", methods=["POST"])
def api_lana_cruda_cerrar_orden(oid):
    """POST → cierra una orden pendiente. Crea el partido en la
    calidad hilada con el coste ponderado calculado.

    Body:
      {
        "kg_hilado":            970,
        "tarifa_hilado_eur_kg": 1.20,
        "partido_ref":          "4923C"  (opcional si la orden ya lo tenia),
        "fecha_recibido":       "2026-05-25"
      }
    """
    bl = _requiere("compras")
    if bl:
        return bl
    body = request.get_json(force=True, silent=True) or {}
    usuario = (request.headers.get("X-Rols-User") or "").strip()
    lc = _lana_cruda_module()
    orden, err = lc.cerrar_orden_hilado(
        orden_id=             oid,
        kg_hilado=            body.get("kg_hilado"),
        tarifa_hilado_eur_kg= body.get("tarifa_hilado_eur_kg") or 0,
        partido_ref=          body.get("partido_ref") or "",
        fecha_recibido=       body.get("fecha_recibido") or "",
        usuario=              usuario,
    )
    if err:
        return jsonify({"error": err}), 400
    return jsonify({"orden": orden})


@app.route("/api/lana-cruda/ordenes/<oid>/anular", methods=["POST"])
def api_lana_cruda_anular_orden(oid):
    """POST → anula una orden pendiente y devuelve los kg al(los)
    contenedor(es) de origen. Body: {motivo}.
    """
    bl = _requiere("compras")
    if bl:
        return bl
    body = request.get_json(force=True, silent=True) or {}
    usuario = (request.headers.get("X-Rols-User") or "").strip()
    lc = _lana_cruda_module()
    orden, err = lc.anular_orden_hilado(
        orden_id=oid,
        motivo=body.get("motivo") or "",
        usuario=usuario,
    )
    if err:
        return jsonify({"error": err}), 400
    return jsonify({"orden": orden})


@app.route("/api/lana-cruda/ordenes", methods=["GET"])
def api_lana_cruda_ordenes():
    """GET → historico de ordenes de hilado. Filtros: contenedor_id,
    variante_id, estado, limit."""
    bl = _requiere("compras")
    if bl:
        return bl
    lc = _lana_cruda_module()
    lc.invalidar_cache()
    limit = request.args.get("limit")
    try:
        limit_i = int(limit) if limit else None
    except ValueError:
        limit_i = None
    ordenes = lc.listar_movimientos_hilado(
        contenedor_id=request.args.get("contenedor_id") or None,
        variante_id=  request.args.get("variante_id")   or None,
        limit=        limit_i,
    )
    # Filtro adicional por estado si se pide
    estado_f = (request.args.get("estado") or "").strip().lower()
    if estado_f:
        ordenes = [o for o in ordenes if (o.get("estado") or "").lower() == estado_f]
    return jsonify({"ordenes": ordenes, "total": len(ordenes)})


# ----- Compras: generar pedido a proveedor -----

def _pdf_pedido_module():
    rols_shared.ensure_shared_on_path()
    import pdf_pedido_proveedor as _p
    return _p


@app.route("/api/compras/generar-pedido", methods=["POST"])
def api_compras_generar_pedido():
    """Registra un pedido y devuelve metadatos + URLs para descargar el PDF
    de cada proveedor implicado.

    Body JSON:
      {
        "lineas": [{"variante_id": "65-2c__pais-normal__cobo",
                    "kg": 2000, "eur_kg": 7.71}, ...],
        "nota":   "Plazo entrega aprox. 4 semanas."
      }

    Devuelve:
      {
        "ref": "PED-20260522-001",
        "fecha": "...",
        "proveedores": {"COBO": [{...}], "HTC": [{...}]},
        "urls_pdf":    {"COBO": "/api/compras/pedido/PED-20260522-001/pdf?proveedor=COBO", ...}
      }

    Solo admin/comercial.
    """
    bl = _bloquear_representante()
    if bl:
        return bl
    li = _lanas_inv_module()
    body = request.get_json(force=True, silent=True) or {}
    lineas = body.get("lineas") or []
    nota = (body.get("nota") or "").strip()
    usuario = (request.headers.get("X-Rols-User") or "").strip()
    resultado, err = li.registrar_pedido(lineas, usuario=usuario, nota=nota)
    if err:
        return jsonify({"error": err}), 400
    ref = resultado["ref"]
    # Construir URLs de descarga (una por proveedor)
    urls = {}
    for prov in resultado["proveedores"].keys():
        urls[prov] = f"/api/compras/pedido/{ref}/pdf?proveedor={prov}"
    resultado["urls_pdf"] = urls
    return jsonify(resultado)


@app.route("/api/compras/pedido/<ref>/campo", methods=["PUT"])
def api_compras_pedido_campo(ref):
    """Actualiza un campo editable del pedido (de momento solo
    fecha_estimada_llegada). Body: {variante_id, campo, valor}.
    """
    bl = _bloquear_representante()
    if bl:
        return bl
    body = request.get_json(force=True, silent=True) or {}
    vid = (body.get("variante_id") or "").strip()
    campo = (body.get("campo") or "").strip()
    valor = body.get("valor")
    if not vid or not campo:
        return jsonify({"error": "faltan variante_id y/o campo"}), 400
    li = _lanas_inv_module()
    out, err = li.actualizar_pedido(vid, ref, campo, valor)
    if err:
        return jsonify({"error": err}), 400
    return jsonify(out)


@app.route("/api/compras/pedido/<ref>/recibido", methods=["POST"])
def api_compras_pedido_recibido(ref):
    """Marca un pedido como recibido. Body:
        {
          variante_id: "...",
          usuario:     opcional,
          kg_a_rols:   opcional. Cuantos kg del pedido llegan al almacen
                       Rols (el resto se queda en almacen proveedor).
                       Si no se pasa, TODO va al almacen Rols.
                       Solo aplica si ref es especifica (no '*').
        }

    Si `ref == "*"` o "all", se interpreta como cerrar todos los pedidos
    abiertos de esa variante (uso historico). En ese caso kg_a_rols se
    ignora — todo va a Rols.
    """
    bl = _bloquear_representante()
    if bl:
        return bl
    body = request.get_json(force=True, silent=True) or {}
    vid = (body.get("variante_id") or "").strip()
    if not vid:
        return jsonify({"error": "falta variante_id"}), 400
    usuario = (body.get("usuario")
               or request.headers.get("X-Rols-User") or "").strip()
    kg_a_rols = body.get("kg_a_rols")  # puede ser None, int o float
    li = _lanas_inv_module()
    real_ref = "" if ref in ("*", "all") else ref
    # Si es cerrar-todos, ignoramos kg_a_rols (no se puede splittear varios)
    if not real_ref:
        kg_a_rols = None
    out, err = li.marcar_pedido_recibido(vid, ref_pedido=real_ref,
                                         usuario=usuario,
                                         kg_a_rols=kg_a_rols)
    if err:
        return jsonify({"error": err}), 400
    return jsonify({**out, "estadisticas": li.estadisticas()})


@app.route("/api/compras/pedido/<ref>/anular", methods=["POST"])
def api_compras_pedido_anular(ref):
    """Anula un pedido. Body: {variante_id, motivo?, usuario?}. La
    variante vuelve a su estado natural segun stock. Si ref es "*" o
    "all", anula todos los pedidos abiertos de la variante."""
    bl = _bloquear_representante()
    if bl:
        return bl
    body = request.get_json(force=True, silent=True) or {}
    vid = (body.get("variante_id") or "").strip()
    if not vid:
        return jsonify({"error": "falta variante_id"}), 400
    usuario = (body.get("usuario")
               or request.headers.get("X-Rols-User") or "").strip()
    motivo = (body.get("motivo") or "").strip()
    li = _lanas_inv_module()
    real_ref = "" if ref in ("*", "all") else ref
    out, err = li.anular_pedido(vid, ref_pedido=real_ref,
                                usuario=usuario, motivo=motivo)
    if err:
        return jsonify({"error": err}), 400
    return jsonify({**out, "estadisticas": li.estadisticas()})


@app.route("/api/compras/pedido/<ref>/pdf", methods=["GET"])
def api_compras_pedido_pdf(ref):
    """Devuelve el PDF del pedido `ref` para el proveedor indicado en
    query param `?proveedor=COBO`. Reconstruye las lineas desde el
    historico persistido en lanas_inventario.json (lana.pedidos[]).
    """
    bl = _bloquear_representante()
    if bl:
        return bl
    proveedor = (request.args.get("proveedor") or "").strip().upper()
    if not proveedor:
        return jsonify({"error": "falta query param 'proveedor'"}), 400

    li = _lanas_inv_module()
    li.invalidar_cache()
    nota = ""
    lineas = []
    for v in li.listar_lanas():
        if (v.get("proveedor") or "").upper() != proveedor:
            continue
        for ped in (v.get("pedidos") or []):
            if ped.get("ref") != ref:
                continue
            lineas.append({
                "titulo":           v.get("titulo"),
                "tipo":             v.get("tipo"),
                "kg":               ped.get("kg"),
                "eur_kg":           ped.get("eur_kg"),
                "importe":          ped.get("importe"),
                "partido_previsto": ped.get("partido_previsto"),
            })
            if ped.get("nota") and not nota:
                nota = ped["nota"]
    if not lineas:
        return jsonify({"error": f"pedido {ref!r} no tiene lineas para proveedor {proveedor!r}"}), 404

    # Si el proveedor tiene ficha, la pasamos para que el PDF incluya
    # razon social + CIF + direccion + persona de contacto.
    pm = _proveedores_module()
    proveedor_data = pm.por_id(proveedor)
    pdfmod = _pdf_pedido_module()
    bytes_pdf = pdfmod.generar_pdf_pedido(proveedor, lineas,
                                          ref_pedido=ref, nota=nota,
                                          proveedor_data=proveedor_data)
    return Response(
        bytes_pdf, mimetype="application/pdf",
        headers={
            "Content-Disposition":
                f'inline; filename="pedido_{ref}_{proveedor}.pdf"',
        },
    )


# Cache busting: url_for('static', ...) añade ?v=<mtime> al final.
# Esto invalida la cache del navegador automáticamente cuando editamos JS/CSS,
# sin tener que pedir Ctrl+Shift+R al usuario.
@app.url_defaults
def _static_cache_buster(endpoint, values):
    if endpoint != "static":
        return
    filename = values.get("filename")
    if not filename:
        return
    fpath = APP_DIR / "static" / filename
    if fpath.exists():
        values.setdefault("v", int(fpath.stat().st_mtime))


@app.after_request
def _no_cache_static_js_css(resp):
    """Evita cache agresivo de los assets que cambian frecuentemente.

    - HTML (Content-Type text/html): no se cachea NUNCA. Asi cuando
      reorganizamos un sidebar, anadimos pestanas o renombramos la
      plataforma, el navegador del comercial no se queda con la version
      vieja sin que tenga que hacer Ctrl+F5.
    - /static/*.js y *.css: tampoco cachean (el url_for ya anade ?v=mtime
      pero algunos browsers cachean el name+query si la cabecera no
      lo prohibe). Doble seguro.
    - Imagenes en /static/imagenes_colores/ y resto de assets si pueden
      cachear (no cambian a menudo y son pesados de transferir).
    """
    p = request.path or ""
    ctype = resp.headers.get("Content-Type", "")
    es_html = ctype.startswith("text/html")
    es_js_css = p.startswith("/static/") and (p.endswith(".js") or p.endswith(".css"))
    if es_html or es_js_css:
        resp.headers["Cache-Control"] = "no-cache, must-revalidate"
        resp.headers["Pragma"] = "no-cache"
    return resp




if __name__ == "__main__":
    port = int(os.environ.get("ROLS_ERP_PORT", "5060"))
    # Sincroniza el catalogo de titulos con los valores en uso en datos.
    try:
        n = _sincronizar_catalogo_titulos()
        if n:
            print(f"  · Catalogo de titulos: {n} valor(es) anadido(s) desde datos")
    except Exception as _e:
        print(f"  · Aviso: no se pudo sincronizar catalogo de titulos ({_e})")
    print()
    print("=" * 60)
    print(f"  ERP Produccion Rols — Compras  ·  http://localhost:{port}")
    print("=" * 60)
    print()
    app.run(host="127.0.0.1", port=port, debug=False)
