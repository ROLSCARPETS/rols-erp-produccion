# -*- coding: utf-8 -*-
"""Pruebas de regresión de Muestras fabricadas (módulo + API + páginas).

Se ejecutan con el test client de Flask, el SSO y el correo de mentira, sobre
una COPIA del seed en una carpeta temporal: no tocan ningún dato real.

    python tests/test_muestras.py

Sale con código 0 si todo pasa y 1 si algo falla (y dice qué).
"""
import io
import json
import os
import shutil
import smtplib
import sys
import tempfile
from datetime import date
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
ERP = Path(__file__).resolve().parent.parent
TMP = Path(tempfile.mkdtemp(prefix="erp-muestras-test-"))
os.environ["ROLS_DATA_DIR"] = str(TMP)
shutil.copy(ERP / "shared/data/muestras_fabricadas.json", TMP / "muestras_fabricadas.json")
sys.path.insert(0, str(ERP / "shared" / "scripts"))
sys.path.insert(0, str(ERP))

import muestras_fabricadas as mf  # noqa: E402
import correo  # noqa: E402
import muestras_avisos as av  # noqa: E402
import app as appmod  # noqa: E402

# ---------------------------------------------------------------------------
# Entorno de mentira
# ---------------------------------------------------------------------------
ADMIN = {"username": "fernando@rolscarpets.com", "nombre": "Fernando Ferrández", "rol": "admin",
         "permisos": {"compras": True, "muestras_fabricadas": True}}
LAB = {"username": "isa@rolscarpets.com", "nombre": "Isa Laboratorio", "rol": "comercial",
       "permisos": {"compras": False, "muestras_fabricadas": True}}
SIN = {"username": "rep@rolscarpets.com", "nombre": "Rep", "rol": "representante",
       "permisos": {"compras": False, "muestras_fabricadas": False}}
CURRENT = {"user": ADMIN}
SSO_REAL = appmod._sso_user          # la de verdad, para probar el filtro de cookies
appmod._sso_user = lambda: CURRENT["user"]
# Sin cuentas: el módulo tira de los usuarios ya vistos en los datos
appmod._usuarios_one_con_permiso = lambda permiso: None

# Correo: configurado, pero en vez de mandar se apunta lo que saldría
ENVIADOS = []   # [(destinatarios, asunto, texto)]
correo._cfg = lambda: {"host": "smtp.test", "port": 587, "user": "", "password": "",
                       "de": "Rols Muestras <produccion@rolscarpets.com>", "origen": "test"}


def _enviar_de_mentira(ruta, msg):
    para = [d.strip() for d in (msg["To"] or "").split(",") if d.strip()]
    cuerpo = msg.get_body(preferencelist=("plain",))
    ENVIADOS.append((para, str(msg["Subject"]), cuerpo.get_content() if cuerpo else ""))
    return ""


correo._enviar_por = _enviar_de_mentira

app = appmod.app
app.config["TESTING"] = True
c = app.test_client()
HOY = date.today().isoformat()

fallos = []


def check(cond, msg):
    print(("  OK   " if cond else "  FAIL ") + msg)
    if not cond:
        fallos.append(msg)


def seccion(titulo):
    print(f"\n[{titulo}]")


def j(r):
    return json.loads(r.data.decode("utf-8"))


def pz(m, i=0):
    """La pieza i de una muestra publicada ({} si no la tiene)."""
    return ((m.get("piezas") or []) + [{}] * (i + 1))[i]


def mats(m, i=0):
    return pz(m, i).get("materias") or []


def alta(**datos):
    """Da de alta una muestra (por defecto de Print, encargada por Fernando)."""
    base = {"cliente": "TEST", "telar": "Print", "encargada_por": ADMIN["username"]}
    base.update(datos)
    return c.post("/api/muestras", json=base)


def estado(mid, e, **extra):
    return c.post(f"/api/muestras/{mid}/estado", json={"estado": e, **extra})


def dest(i=-1):
    return sorted(ENVIADOS[i][0]) if ENVIADOS else []


# ===========================================================================
seccion("unidad: números, telares y flujos")
check(mf.normalizar_numero("4102 B") == ("4102-B", 4102, "B"), "'4102 B' → 4102-B")
check(mf.normalizar_numero("M-4120 B") == ("4120-B", 4120, "B"), "'M-4120 B' → 4120-B")
check(mf.normalizar_numero(5448) == ("5448", 5448, ""), "5448 como número")
check(mf.flujo_de("Print") == mf.FLUJO_PRINT and mf.flujo_de("Varilla") == mf.FLUJO_TELAR
      and mf.flujo_de("Pompón") == mf.FLUJO_POMPON and mf.flujo_de("Festón") == mf.FLUJO_POMPON,
      "cada técnica con su flujo")
check(all(mf.flujo_de(t) == mf.FLUJO_TELAR for t in ("Colortec", "Lancetas", "Rapier", "Tufting Bucle", "Tufting Corte")),
      "los seis telares llevan el flujo con diseño delante")
check(mf.FLUJO_PRINT[0] == "por_empezar" and "listo_diseno" in mf.FLUJO_PRINT, "Print empieza en «Por empezar»")
check(mf.etapa_permitida("revisar_color", "Pompón") and not mf.etapa_permitida("revisar_color", "Varilla"),
      "«Revisar color» solo en Pompón/Festón")
check(mf.etapa_permitida("diseno_listo", "Colortec") and not mf.etapa_permitida("diseno_listo", "Print"),
      "«Diseño listo» solo en los telares")

seccion("unidad: datos técnicos por telar")
check([x[0] for x in mf.pelos_de("Lancetas")] == ["bucle_sencillo", "tejido_plano", "bucle_saltillo", "pendiente"],
      "construcciones de Lancetas")
check(mf.pelo_fijo("Rapier") == "tejido_plano" and mf.pelo_fijo("Colortec") == "corte"
      and mf.pelo_fijo("Tufting Bucle") == "bucle" and mf.pelo_fijo("Tufting Corte") == "corte"
      and mf.pelo_fijo("Varilla") == "", "construcción fija donde toca")
check("raya" not in {s for s, _ in mf.PELOS}, "«raya» ya no existe")
check(all(mf.lleva_gramaje(t) for t in ("Colortec", "Tufting Bucle", "Tufting Corte"))
      and not any(mf.lleva_gramaje(t) for t in ("Varilla", "Lancetas", "Rapier", "Pompón")),
      "gramaje: solo Colortec y los dos Tufting")
check(all(mf.lleva_medidas(t) for t in ("Varilla", "Lancetas", "Rapier", "Colortec", "Tufting Bucle", "Tufting Corte"))
      and not any(mf.lleva_medidas(t) for t in ("Pompón", "Kibby", "Festón", "Print", "Otros")),
      "ancho y largo: solo los telares")
for t in ("Pompón", "Kibby", "Festón"):
    check(not mf.lleva_tejeduria(t) and not mf.lleva_hilos_pua(t) and not mf.es_telar(t)
          and mf.etiqueta_cuerpo(t) == "Color", f"{t}: solo materias, por color, no es telar")
check(mf.etiqueta_n_cuerpos("Tufting Bucle") == "Nº de colores" and mf.etiqueta_n_cuerpos("Varilla") == "Nº de cuerpos",
      "en Tufting los cuerpos se llaman colores")
check(mf.medidas_texto({"ancho": "50 cm", "largo": "70 cm"}) == "50 cm × 70 cm"
      and mf.medidas_texto({"ancho": "50 cm"}) == "ancho 50 cm" and mf.medidas_texto({}) == "", "medidas_texto")
check("Raschel" in mf.TELARES_RETIRADOS and "Tufting" in mf.TELARES_RETIRADOS, "Raschel y Tufting a secas, retirados")

seccion("migraciones")
data = mf.cargar()
check(data["_meta"]["version_schema"] == 11, f"esquema v11 ({data['_meta']['version_schema']})")
check(all(not any(k in m for k in ("materias", "altura_felpa", "pasadas", "gramaje", "ancho", "largo",
                                   "n_cuerpos", "material", "hilos_pua"))
          for m in data["muestras"]), "ningún dato técnico suelto: todo en las piezas")
TOTAL = len(data["muestras"])
ULTIMO = data["_meta"]["ultimo_numero"]
check(len({m["id"] for m in data["muestras"]}) == TOTAL, f"ids únicos ({TOTAL} muestras)")
# v10/v11 sobre una muestra con la técnica plana, como estaba antes
_m = {"id": "X1", "telar": "Varilla", "pasadas": "30", "altura_felpa": "12 mm", "n_cuerpos": "2",
      "ancho": "50 cm", "largo": "70 cm", "pelo": "corte", "acabado": "latex",
      "materias": [{"id": "a", "cuerpo": "1", "materia": "Lana 100 3/c", "hilos_pua": "3", "colorido": "CREMA"}]}
_doc = {"muestras": [_m]}
mf._migrar_v10(_doc)
mf._migrar_v11(_doc)
_p = _m["piezas"][0]
check(len(_m["piezas"]) == 1 and _p["altura_felpa"] == "12 mm" and _p["pasadas"] == "30" and _p["ancho"] == "50 cm"
      and _p["materias"][0]["materia"] == "Lana 100 3/c" and "pasadas" not in _m and "materias" not in _m
      and _m["pelo"] == "corte", "v10+v11: la técnica plana pasa a la pieza 1 (construcción y acabado se quedan)")
_antes = json.dumps(_doc, sort_keys=True)
mf._migrar_v10(_doc)
mf._migrar_v11(_doc)
check(json.dumps(_doc, sort_keys=True) == _antes, "v10/v11 idempotentes")

seccion("alta")
r = alta(cliente="SIN NADIE", encargada_por="")
check(r.status_code == 400 and "obligatorio" in j(r)["error"], "sin «Encargada por» → 400")
r = alta(encargada_por="Paco")
check(r.status_code == 400, "un nombre antiguo del libro no vale para altas")
r = alta(cliente="")
check(r.status_code == 400, "muestra de cliente sin cliente → 400")
r = alta(cliente="", tipo="interna")
check(r.status_code == 201 and j(r)["muestra"]["tipo"] == "interna", "las internas no necesitan cliente")
r = alta(cliente="CLIENTE UNO", referencia="Print Wilton 4 cuerpos", descripcion="Prueba",
         cliente_navision="C0200", prioridad=1)
m = j(r)["muestra"]
MID = m["id"]
check(r.status_code == 201 and m["numero"] == ULTIMO + 2 and m["estado"] == "por_empezar",
      f"el número lo pone el servidor ({m['numero']}) y nace en «Por empezar»")
check(m["encargada_por_usuario"] == ADMIN["username"] and m["creado_por"] == ADMIN["username"],
      "quién la encarga y quién la crea")
check(m["referencia"] == "Print Wilton 4 cuerpos" and m["cliente_navision"] == "C0200", "referencia y código de Navision")
check(alta(referencia="x" * 121).status_code == 400, "referencia de más de 120 → 400")
r = alta(telar="Varilla", pasadas="30", altura_felpa="12 mm", n_cuerpos="2", ancho="50 cm", largo="70 cm",
         pelo="Corte y bucle", acabado="latex",
         materias=[{"cuerpo": "1", "materia": "Lana 100 3/c", "hilos_pua": "3", "colorido": "CREMA"}])
mv = j(r)["muestra"]
MID_V = mv["id"]
check(r.status_code == 201 and mv["n_piezas"] == 1 and pz(mv)["pasadas"] == "30" and pz(mv)["ancho"] == "50 cm"
      and mats(mv)[0]["materia"] == "Lana 100 3/c" and mv["pelo"] == "corte_bucle",
      "el alta técnica monta la pieza 1 (construcción por su etiqueta)")
check(mv["tecnica_resumen"] == "Cuerpo 1: Lana 100 3/c (CREMA · 3 hilos/púa) · 30 pasadas · felpa 12 mm · "
      "2 cuerpos · 50 cm × 70 cm · Corte y bucle · Látex", f"resumen técnico ({mv['tecnica_resumen']})")
r = alta(telar="Rapier")
check(j(r)["muestra"]["pelo"] == "tejido_plano", "Rapier nace en tejido plano")
r = alta(telar="Colortec", pasadas="18", gramaje="1.500 gr/m2")
MID_C = j(r)["muestra"]["id"]
check(j(r)["muestra"]["pelo"] == "corte" and pz(j(r)["muestra"])["gramaje"] == "1.500 gr/m2", "Colortec: corte y gramaje")
r = alta(telar="Pompón", materias=[{"cuerpo": "1", "materia": "Lana 65 2/c", "colorido": "SAGE"}])
MID_P = j(r)["muestra"]["id"]
check(j(r)["muestra"]["tecnica_resumen"] == "Color 1: Lana 65 2/c (SAGE)", "Pompón: solo materias, por color")
r = alta(telar="Print", variante_de=j(c.get(f"/api/muestras/{MID}"))["muestra"]["numero"])
check(r.status_code == 201 and j(r)["muestra"]["sufijo"] == "B", "variante → M-…-B")
check(alta(variante_de=999999).status_code == 400, "variante de un número que no existe → 400")
check(alta(estado="revisar_color").status_code == 400, "alta de Print en «Revisar color» → 400")

seccion("ficha")
r = c.put(f"/api/muestras/{MID}", json={"encargada_por": ""})
check(r.status_code == 400 and "no se puede dejar vacío" in j(r)["error"], "no se puede vaciar «Encargada por»")
r = c.put(f"/api/muestras/{MID}", json={"descripcion": "Otra", "prioridad": 3})
check(r.status_code == 200 and j(r)["muestra"]["prioridad"] == 3, "se guardan los campos")
check(any(h.get("campo") == "descripcion" for h in j(r)["muestra"]["historial"]), "queda en el historial")
check(c.put(f"/api/muestras/{MID}", json={"prioridad": 7}).status_code == 400, "prioridad fuera de rango → 400")
check(c.put(f"/api/muestras/{MID}", json={"material": "Lana"}).status_code == 400, "el viejo campo «material» no existe")
check(c.put(f"/api/muestras/{MID}", json={"altura_felpa": "12 mm"}).status_code == 400,
      "la altura ya no es de la muestra, es de la pieza")
check(c.put(f"/api/muestras/{MID_V}", json={"pelo": "rizado"}).status_code == 400, "construcción no válida → 400")
r = c.put(f"/api/muestras/{MID_V}", json={"telar": "Rapier"})
check(j(r)["muestra"]["pelo"] == "tejido_plano", "cambiar a Rapier pone su construcción fija")
c.put(f"/api/muestras/{MID_V}", json={"telar": "Varilla", "pelo": "corte_bucle"})
r = c.put(f"/api/muestras/{MID_V}", json={"telar": "Print"})
check(j(r)["muestra"]["n_piezas"] == 1 and j(r)["muestra"]["tecnica_resumen"] == "",
      "cambiar a un telar sin técnica conserva las piezas pero no las resume")
c.put(f"/api/muestras/{MID_V}", json={"telar": "Varilla"})
check(c.get("/api/muestras/no-existe").status_code == 404, "ficha que no existe → 404")

seccion("piezas tejidas")


def PZ(*piezas):
    return {"piezas": list(piezas)}


r = c.put(f"/api/muestras/{MID_V}", json=PZ(
    {"pasadas": "30", "materias": [{"cuerpo": "1", "materia": "Lana 100 3/c", "colorido": "CREMA"},
                                   {"cuerpo": "2", "materia": " Lana 100 5/c ", "colorido": "CARAMELO"},
                                   {"cuerpo": "3"}]}))
m = j(r)["muestra"]
check(r.status_code == 200 and len(mats(m)) == 2 and mats(m)[1]["materia"] == "Lana 100 5/c",
      "se tira la fila que solo trae el nº de cuerpo y se recortan espacios")
ids = [f["id"] for f in mats(m)]
pid = pz(m)["id"]
r = c.put(f"/api/muestras/{MID_V}", json=PZ(
    {"pasadas": "30", "materias": [{"cuerpo": "1", "materia": "Lana 100 3/c", "colorido": "BEIGE"},
                                   {"cuerpo": "2", "materia": "Lana 100 5/c", "colorido": "CARAMELO"}]}))
check([f["id"] for f in mats(j(r)["muestra"])] == ids and pz(j(r)["muestra"])["id"] == pid,
      "los ids de piezas y materias se reaprovechan por posición")
h = [x for x in j(r)["muestra"]["historial"] if x.get("campo") == "piezas"][-1]
check("CREMA" in h["de"] and "BEIGE" in h["a"], "el historial guarda las piezas en texto")
r = c.put(f"/api/muestras/{MID_V}", json=PZ(
    {"nombre": "Dib. 7846", "pasadas": "30", "altura_felpa": "10 mm", "resultado": "es la buena",
     "materias": [{"cuerpo": "1", "materia": "Lana 140 6/c", "colorido": "BLANCO SUAVE"}]},
    {"nombre": "Dib. 7847", "pasadas": "32", "altura_felpa": "12 mm",
     "materias": [{"cuerpo": "1", "materia": "Lana 140 6/c", "colorido": "CREMA"}]}))
m = j(r)["muestra"]
check(r.status_code == 200 and m["n_piezas"] == 2 and pz(m, 1)["nombre"] == "Dib. 7847"
      and pz(m)["resultado"] == "es la buena" and pz(m)["id"] != pz(m, 1)["id"], "dos piezas en la misma M")
check(m["tecnica_resumen"].startswith("2 piezas · 1) Dib. 7846") and "2) Dib. 7847" in m["tecnica_resumen"],
      f"el resumen las numera ({m['tecnica_resumen'][:70]}…)")
check(c.put(f"/api/muestras/{MID_V}", json={"piezas": "x"}).status_code == 400, "piezas que no es lista → 400")
check(c.put(f"/api/muestras/{MID_V}", json=PZ({"nope": 1})).status_code == 400, "campo desconocido en una pieza → 400")
check(c.put(f"/api/muestras/{MID_V}", json=PZ({"materias": [{"materia": "L", "x": 1}]})).status_code == 400,
      "campo desconocido en una materia → 400")
check(c.put(f"/api/muestras/{MID_V}", json=PZ({"altura_felpa": "x" * 41})).status_code == 400, "altura de más de 40 → 400")
check(c.put(f"/api/muestras/{MID_V}", json=PZ(*[{"nombre": f"P{i}"} for i in range(13)])).status_code == 400,
      "más de 12 piezas → 400")
check(c.put(f"/api/muestras/{MID_V}", json=PZ({"materias": [{"materia": f"L{i}"} for i in range(13)]})).status_code == 400,
      "más de 12 materias en una pieza → 400")
r = c.put(f"/api/muestras/{MID_C}", json=PZ({"gramaje": "1.500 gr/m2", "ancho": "50 cm", "largo": "1 m"}))
check("1.500 gr/m2" in j(r)["muestra"]["tecnica_resumen"] and "50 cm × 1 m" in j(r)["muestra"]["tecnica_resumen"],
      "gramaje y medidas en el resumen de Colortec")
r = c.put(f"/api/muestras/{MID_C}", json={"telar": "Varilla"})
check(pz(j(r)["muestra"])["gramaje"] == "1.500 gr/m2" and "1.500" not in j(r)["muestra"]["tecnica_resumen"],
      "en un telar sin gramaje se conserva pero no se enseña")
c.put(f"/api/muestras/{MID_C}", json={"telar": "Colortec"})
cat = j(c.get("/api/muestras/catalogos"))
check("BLANCO SUAVE" in cat["coloridos"] and "Lana 140 6/c" in cat["materiales"],
      "materiales y coloridos del catálogo salen de todas las piezas")
check(MID_V in {x["id"] for x in j(c.get("/api/muestras?vista=en-curso&q=7847"))["muestras"]},
      "el nombre de la pieza se busca")

seccion("catálogos")
tpt = cat["tecnicos_por_telar"]
check(tpt["Colortec"]["gramaje"] is True and tpt["Varilla"]["gramaje"] is False
      and tpt["Pompón"]["tejeduria"] is False and tpt["Pompón"]["es_telar"] is False,
      "configuración técnica por telar en el catálogo")
check("Raschel" in cat["telares"] and "Raschel" not in cat["telares_alta"] and "Tufting" not in cat["telares_alta"]
      and "Tufting Bucle" in cat["telares_alta"] and "Otros" in cat["telares_alta"],
      "las técnicas retiradas no se ofrecen al dar de alta; «Otros» sí")

seccion("estados y diario")
r = estado(MID, "listo_diseno", nota="lo mira Fran")
m = j(r)["muestra"]
check(r.status_code == 200 and m["estado"] == "listo_diseno"
      and m["apuntes"][-1]["texto"].startswith("Pasa a «Listo para empezar diseño»") and "lo mira Fran" in m["apuntes"][-1]["texto"],
      "cambio de etapa con nota → apunte automático")
check(estado(MID, "revisar_color").status_code == 400, "Print no puede ir a «Revisar color»")
check(estado(MID, "diseno_listo").status_code == 400, "Print no puede ir a «Diseño listo»")
r = estado(MID, "por_empezar")
check(j(r)["muestra"]["apuntes"][-1]["texto"].startswith("Vuelve a «Por empezar»"), "volver atrás es un retroceso")
r = estado(MID_P, "revisar_color")
check(r.status_code == 200, "Pompón sí pasa por «Revisar color»")
check(c.put(f"/api/muestras/{MID_P}", json={"telar": "Varilla"}).status_code == 400,
      "en «Revisar color» no se puede cambiar a un telar que no la tiene")
r = estado(MID_P, "terminada")
check(j(r)["muestra"]["fecha_lista"] == HOY and not j(r)["muestra"]["en_curso"], "terminada fija la fecha real y sale de En curso")
r = c.post(f"/api/muestras/{MID}/apuntes", json={"texto": "Se envía a tintar", "fecha": HOY})
aid = j(r)["muestra"]["apuntes"][-1]["id"]
check(r.status_code == 201, "apunte en el diario")
r = c.put(f"/api/muestras/{MID}/apuntes/{aid}", json={"texto": "Se envía a tintar 4 colores"})
check(j(r)["muestra"]["apuntes"][-1]["texto"] == "Se envía a tintar 4 colores", "editar un apunte")
check(c.delete(f"/api/muestras/{MID}/apuntes/{aid}").status_code == 200, "borrar un apunte")
check(c.post(f"/api/muestras/{MID}/apuntes", json={"texto": ""}).status_code == 400, "apunte vacío → 400")
r = c.post(f"/api/muestras/{MID}/archivar", json={"archivada": True})
check(j(r)["muestra"]["archivada"] and not j(r)["muestra"]["en_curso"], "archivar la saca de En curso")
c.post(f"/api/muestras/{MID}/archivar", json={"archivada": False})

seccion("verificación de diseño")
r = c.put(f"/api/muestras/{MID}", json={"diseno_verificado": True})
check(j(r)["muestra"]["diseno_verificado"] and j(r)["muestra"]["diseno_verificado_por"] == ADMIN["username"],
      "marcar la verificación apunta quién")
CURRENT["user"] = LAB
r = c.put(f"/api/muestras/{MID}", json={"diseno_verificado": False})
check(r.status_code == 400 and "solo esa persona" in j(r)["error"], "otro usuario no puede quitarla")
CURRENT["user"] = ADMIN
r = c.put(f"/api/muestras/{MID}", json={"diseno_verificado": False})
check(r.status_code == 200 and not j(r)["muestra"]["diseno_verificado"], "quien la puso sí la quita")

seccion("adjuntos: diseño e información de cliente")


def subir(nombre, contenido=b"\x89PNG prueba", clase=None, mid=None):
    datos = {"fichero": (io.BytesIO(contenido), nombre)}
    if clase is not None:
        datos["clase"] = clase
    return c.post(f"/api/muestras/{mid or MID}/adjuntos", data=datos, content_type="multipart/form-data")


r = subir("diseno v1.png")
a1 = j(r)["muestra"]["adjuntos"][-1]
check(r.status_code == 201 and a1["clase"] == "version" and a1["clase_label"] == "Versión 1" and a1["imagen"],
      "adjuntar diseño: versión 1 por defecto")
check((mf.ADJUNTOS_DIR / MID / f"{a1['id']}.png").is_file(), "el fichero va a la carpeta de adjuntos")
r = c.get(f"/api/muestras/{MID}/adjuntos/{a1['id']}")
check(r.status_code == 200 and r.mimetype == "image/png", "la imagen se abre en la pestaña")
r = subir("final.ai", b"%!PS", clase="Diseño final")
check(j(r)["muestra"]["adjuntos"][-1]["clase"] == "final", "clase por su etiqueta (Diseño final)")
r = subir("correo cliente.png", clase="cliente")
a3 = j(r)["muestra"]["adjuntos"][-1]
check(a3["clase"] == "cliente" and a3["clase_label"] == "Información de cliente" and "version_n" not in a3,
      "información de cliente: su clase y sin número de versión")
r = c.put(f"/api/muestras/{MID}/adjuntos/{a3['id']}", json={"clase": "otro"})
check(j(r)["muestra"]["adjuntos"][-1]["clase"] == "otro", "cambiar de bloque cambiando la etiqueta")
check(subir("malo.exe", b"x").status_code == 400, "extensión no admitida → 400")
check(subir("vacio.png", b"").status_code == 400, "fichero vacío → 400")
check(subir("x.png", clase="borrador").status_code == 400, "clase no válida → 400")
_lim = mf.ADJUNTO_MAX_BYTES
mf.ADJUNTO_MAX_BYTES = 4
check(subir("grande.pdf", b"12345").status_code == 400, "más grande del límite → 400")
mf.ADJUNTO_MAX_BYTES = _lim
r = c.delete(f"/api/muestras/{MID}/adjuntos/{a1['id']}")
check(r.status_code == 200 and not (mf.ADJUNTOS_DIR / MID / f"{a1['id']}.png").exists()
      and any(h["tipo"] == "adjunto" and h["a"] == "borrado" for h in j(r)["muestra"]["historial"]),
      "quitar el adjunto lo borra del disco y deja rastro")

seccion("listado")
lst = j(c.get("/api/muestras?vista=en-curso"))
fechas = [x["fecha_solicitud"] or "" for x in lst["muestras"]]
check(fechas == sorted(fechas, reverse=True), "En curso, la solicitud más reciente arriba")
fila = next(x for x in lst["muestras"] if x["id"] == MID)
check(fila["cliente_navision"] == "C0200", "el código de Navision llega al listado")
check(lst["resumen"]["en_curso"] >= 1 and "por_estado" in lst["resumen"], "el resumen de la cabecera")
check(len(j(c.get("/api/muestras?vista=todas&telar=Raschel"))["muestras"]) >= 1, "se filtra por técnicas retiradas")

seccion("avisos por correo")
cfg = j(c.get("/api/muestras/avisos/config"))
check(len(cfg["filas"]) == 16 and cfg["filas"][0]["clave"] == "nueva" and cfg["filas"][-1]["clave"] == "hito",
      "16 momentos configurables")
check(av.MODOS_ENCARGADA == ("no", "siempre") and cfg["config"]["en_telar"]["encargada"] == "siempre",
      "quien la encarga: avisar o no avisar")
check(cfg["config"]["listo_diseno"]["buzones"] == ["diseño@rolscarpets.com"], "el buzón de diseño lleva eñe")
r = c.put("/api/muestras/avisos/config", json={"en_telar": {"encargada": "salvo_actor"}})
check(j(r)["config"]["en_telar"]["encargada"] == "siempre", "el modo viejo «salvo si lo hace ella» se lee como avisar")
CURRENT["user"] = LAB
check(c.put("/api/muestras/avisos/config", json={"en_telar": {"encargada": "no"}}).status_code == 403,
      "solo un admin cambia los destinatarios")
CURRENT["user"] = ADMIN
n = len(ENVIADOS)
estado(MID_V, "listo_diseno")
check(len(ENVIADOS) == n + 1 and dest() == sorted(["diseño@rolscarpets.com", ADMIN["username"]])
      and "LISTO PARA EMPEZAR DISEÑO" in ENVIADOS[-1][1],
      f"«Listo para empezar diseño» → diseño y quien la encargó, en un solo correo ({dest()})")
n = len(ENVIADOS)
estado(MID_V, "listo_diseno")
check(len(ENVIADOS) == n, "volver a pulsar la misma etapa no manda nada")
c.put("/api/muestras/avisos/config", json={"en_diseno": {"encargada": "no"}})
n = len(ENVIADOS)
estado(MID_V, "en_diseno")
check(len(ENVIADOS) == n, "una etapa en «no se le avisa» no manda nada")
check(any(h["tipo"] == "aviso" and h["ok"] for h in j(c.get(f"/api/muestras/{MID_V}"))["muestra"]["historial"]),
      "cada aviso queda en el historial")
r = c.put("/api/muestras/avisos/config", json=av.avisos_por_defecto())
check(j(r)["config"] == av.avisos_por_defecto(), "se vuelve a los valores de fábrica")

seccion("correo: direcciones con eñe (SMTPUTF8)")
check(correo.no_ascii(["a@b.com", "diseño@rolscarpets.com", "", None]) == ["diseño@rolscarpets.com"], "no_ascii")


class _ServidorDeMentira:
    def __init__(self, utf8):
        self.utf8 = utf8

    def has_extn(self, x):
        return x == "smtputf8" and self.utf8


def _msg(*para):
    from email.message import EmailMessage
    msg = EmailMessage()
    msg["To"] = ", ".join(para)
    return msg


_m1 = _msg("diseño@rolscarpets.com", "laboratorio@rolscarpets.com")
check(correo._sin_smtputf8(_ServidorDeMentira(True), _m1) == "" and "diseño" in _m1["To"],
      "con SMTPUTF8 la eñe se entrega")
_m2 = _msg("diseño@rolscarpets.com", "laboratorio@rolscarpets.com")
aviso = correo._sin_smtputf8(_ServidorDeMentira(False), _m2)
check("diseño" not in _m2["To"] and "laboratorio" in _m2["To"] and "sin avisar a diseño" in aviso,
      "sin SMTPUTF8 se deja fuera la eñe y el correo sale para el resto")
try:
    correo._sin_smtputf8(_ServidorDeMentira(False), _msg("diseño@rolscarpets.com"))
    check(False, "si solo queda la eñe, se rechaza")
except smtplib.SMTPNotSupportedError:
    check(True, "si solo queda la eñe, se rechaza")

seccion("PDF de la caja")
try:
    import pdf_muestra
    r = c.get(f"/api/muestras/{MID_V}/pdf")
    check(r.status_code == 200 and r.mimetype == "application/pdf" and r.data[:4] == b"%PDF",
          "el PDF se genera")
    try:
        from pypdf import PdfReader
    except ImportError:
        PdfReader = None
    if PdfReader:
        txt = PdfReader(io.BytesIO(r.data)).pages[0].extract_text()
        check("PIEZA 1" in txt and "PIEZA 2" in txt and "Dib. 7847" in txt and "Resultado" in txt,
              "una sección por pieza, con su resultado")
except ImportError:
    print("  (sin reportlab: se salta el PDF)")

seccion("páginas")
listado = c.get("/muestras-fabricadas").data.decode("utf-8")
check('class="ms-kpis"' not in listado and 'id="tc-en-curso"' in listado, "cabecera sin KPIs, con los contadores")
check('class="ms-av-lista"' in listado and "an-avisos-tabla" not in listado, "los avisos van en filas")
check('id="ms-n-persona" required' in listado and "obligatorio" in listado, "el alta marca «Encargada por» obligatorio")
ficha = c.get(f"/muestras-fabricadas/{MID_V}").data.decode("utf-8")
check('id="md-piezas"' in ficha and 'id="md-pieza-add"' in ficha and 'id="md-pieza-copia"' in ficha,
      "la ficha lleva las piezas, «+ Añadir pieza» y «+ Añadir otra igual»")
check("md-f-pasadas" not in ficha and 'id="md-f-pelo"' in ficha and 'id="md-f-acabado"' in ficha,
      "arriba solo construcción y acabado")
check('id="md-cliente-info"' in ficha and ficha.index('id="md-cliente-info"') > ficha.index('id="md-adjuntos-wrap"'),
      "«Información de cliente» debajo de Diseño")

seccion("seguridad: escrituras que no vienen de la propia aplicación")
ap = lambda **h: c.post(f"/api/muestras/{MID_V}/apuntes", json={"texto": "prueba de origen"}, headers=h)
check(ap(**{"Sec-Fetch-Site": "cross-site"}).status_code == 403, "desde otra web → 403")
check(ap(**{"Sec-Fetch-Site": "same-site"}).status_code == 403,
      "desde otro subdominio de rolscarpets.com (mismo «sitio» para la cookie) → 403")
check(ap(**{"Sec-Fetch-Site": "same-origin"}).status_code == 201, "desde la propia aplicación → pasa")
check(ap(Origin="https://evil.example.com").status_code == 403, "navegador sin Sec-Fetch-Site pero con Origin ajeno → 403")
check(ap(Origin="http://localhost").status_code == 201, "Origin propio → pasa")
r = c.post(f"/api/muestras/{MID_V}/estado", data='{"estado":"cancelada","nota":"x="}', content_type="text/plain",
           headers={"Sec-Fetch-Site": "cross-site", "Origin": "https://evil.example.com"})
check(r.status_code == 403 and j(c.get(f"/api/muestras/{MID_V}"))["muestra"]["estado"] != "cancelada",
      "el ataque real (formulario text/plain de otra web) ya no cancela la muestra")
check(c.get("/api/muestras?vista=en-curso", headers={"Sec-Fetch-Site": "cross-site"}).status_code == 200,
      "las lecturas no se tocan")
r = c.post("/api/muestras/avisos/hitos", headers={"X-Rols-Api-Token": "no-vale", "Sec-Fetch-Site": "cross-site"})
check(r.status_code != 403 or "no viene de esta aplicación" not in r.get_data(as_text=True),
      "servidor a servidor con token: lo decide el endpoint, no esta barrera")

seccion("seguridad: cabeceras y límites")
for nombre, r in (("página", c.get("/muestras-fabricadas")), ("API", c.get("/api/muestras?vista=en-curso")),
                  ("PDF", c.get(f"/api/muestras/{MID_V}/pdf"))):
    h = r.headers
    check(h.get("X-Content-Type-Options") == "nosniff" and h.get("Referrer-Policy") == "strict-origin-when-cross-origin"
          and "frame-ancestors 'self' https://*.rolscarpets.com" in (h.get("Content-Security-Policy") or ""),
          f"{nombre}: nosniff, Referrer-Policy y solo enmarcable desde la suite")
check("Strict-Transport-Security" not in c.get("/api/muestras").headers, "sin HSTS en local (http)")
check(c.get("/api/muestras", base_url="https://produccion.rolscarpets.com").headers.get("Strict-Transport-Security")
      == "max-age=31536000", "HSTS en producción")
r = c.post(f"/api/muestras/{MID_V}/apuntes", data=b"x" * (31 * 1024 * 1024), content_type="application/json")
check(r.status_code == 413, f"una petición de más de 30 MB → 413 ({r.status_code})")

seccion("seguridad: páginas de Compras y filtro de cookies")
check(c.get("/materias-primas").status_code == 200 and c.get("/").status_code == 200, "con permiso se ven")
CURRENT["user"] = SIN
r = c.get("/materias-primas")
check(r.status_code == 302 and r.headers["Location"].endswith("/inicio"), "Compras sin permiso → al inicio de One")
check(c.get("/materia-prima/65-2c__pais-normal").status_code == 302, "ficha de materia prima sin permiso → fuera")
CURRENT["user"] = None
check(c.get("/").status_code == 302 and "/login" in c.get("/").headers["Location"], "el inicio del ERP pide sesión")
CURRENT["user"] = LAB
check(c.get("/").status_code == 200, "el inicio vale para cualquiera con sesión (el laboratorio no tiene Compras)")
CURRENT["user"] = ADMIN
import urllib.request as _ur
_llamadas = []
_urlopen_real = _ur.urlopen


def _urlopen_espia(req, *a, **k):
    _llamadas.append(getattr(req, "full_url", req))
    raise OSError("sin red en las pruebas")


_ur.urlopen = _urlopen_espia
try:
    for valor, debe_preguntar in (("cualquiera", False), ("<script>", False), ("a.b", False),
                                  ("eyJ1c2VyX2lkIjo0Mn0.aP3xZg.Qk1v0WQ8vX5t9pYl2mH7rJ3c", True)):
        _llamadas.clear()
        appmod._SSO_CACHE.clear()
        with app.test_request_context("/api/muestras", headers={"Cookie": f"rols_one_session={valor}"}):
            usuario = SSO_REAL()
        check(usuario is None and bool(_llamadas) == debe_preguntar,
              f"cookie {valor[:14]!r}: {'se pregunta a cuentas' if debe_preguntar else 'se descarta sin preguntar'}")
finally:
    _ur.urlopen = _urlopen_real

seccion("rendimiento: el documento se lee una vez por petición")
import jsonstore as _js
_lecturas = {"n": 0}
_load_real = _js._Store.load


def _load_contado(self, key, *a, **k):
    if key == "muestras_fabricadas" and getattr(self._local, "tx_docs", None) is None:
        _lecturas["n"] += 1
    return _load_real(self, key, *a, **k)


_js._Store.load = _load_contado
try:
    _lecturas["n"] = 0
    c.get("/api/muestras?vista=en-curso&catalogos=1")
    check(_lecturas["n"] == 1, f"el listado lee el documento una vez ({_lecturas['n']})")
    _lecturas["n"] = 0
    r = estado(MID_V, "en_hilatura")
    check(r.status_code == 200 and _lecturas["n"] == 1,
          f"un cambio de etapa: una lectura fuera de la transacción ({_lecturas['n']})")
    # otra petición no hereda nada: lo cambiado por fuera se ve en la siguiente
    mf.actualizar(MID_V, {"referencia": "cambiada por fuera"}, usuario=None)
    check(j(c.get(f"/api/muestras/{MID_V}"))["muestra"]["referencia"] == "cambiada por fuera",
          "cada petición parte de cero: no hay datos rancios entre peticiones")
finally:
    _js._Store.load = _load_real

seccion("permisos")
CURRENT["user"] = SIN
check(c.get("/api/muestras").status_code == 403, "sin permiso → 403")
r = c.get("/muestras-fabricadas")
check(r.status_code == 302 and r.headers["Location"].endswith("/inicio"), "página sin permiso → al inicio de One")
CURRENT["user"] = None
r = c.get("/muestras-fabricadas")
check(r.status_code == 302 and "/login?next=" in r.headers["Location"], "página sin sesión → al login")
check(c.get("/api/muestras").status_code == 403, "API sin sesión → 403")
CURRENT["user"] = LAB
check(c.delete(f"/api/muestras/{MID}").status_code == 403, "borrar solo el nivel Completo")
CURRENT["user"] = ADMIN
check(c.delete(f"/api/muestras/{MID}").status_code == 200 and c.get(f"/api/muestras/{MID}").status_code == 404,
      "un admin la borra")

seccion("integridad al final")
data = mf.cargar()
check(len({m["id"] for m in data["muestras"]}) == len(data["muestras"]), "ids únicos")
check(data["_meta"]["version_schema"] == 11, "esquema v11")

# ---------------------------------------------------------------------------
print()
print("RESULTADO:", "TODO OK" if not fallos else f"{len(fallos)} FALLOS")
for f in fallos:
    print("  -", f)
shutil.rmtree(TMP, ignore_errors=True)
sys.exit(1 if fallos else 0)
