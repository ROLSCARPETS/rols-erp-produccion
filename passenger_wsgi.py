"""Passenger WSGI entrypoint del ERP de Produccion (modulo Compras) en Plesk.

App Flask UNICA (a diferencia de Rols One, que compone 5 apps bajo un dominio).
Aqui solo hay una: el modulo de Compras / Materias primas.

Que hace:
- Anade shared/scripts al path (rols_shared + modulos de datos).
- Fija ROLS_DATA_DIR: los datos de runtime persisten FUERA del docroot para que
  ni el deploy ni git los toquen. Se siembran (idempotente) desde shared/data.
- (reportlab se instala en el venv en el deploy, no en runtime.)
- Normaliza PATH_INFO (decode_path_info) por si Passenger lo entrega aun
  percent-encoded (rutas con espacios: /materia-prima/<id>, etc.).
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SHARED_SCRIPTS = ROOT / "shared" / "scripts"
if str(SHARED_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SHARED_SCRIPTS))

from rols_shared import decode_path_info  # noqa: E402

# Datos de runtime FUERA del docroot (persisten entre deploys/reinicios). Solo
# afecta a prod: en local este entrypoint no se usa y los modulos caen a shared/data.
os.environ.setdefault("ROLS_DATA_DIR", str(ROOT.parent / "rols-erp-produccion-data"))


def _seed_data_dir():
    """Siembra idempotente: copia el seed del repo (shared/data) a ROLS_DATA_DIR
    solo para los ficheros que aun no existan. Nunca pisa datos ya vivos."""
    import shutil

    dst = Path(os.environ["ROLS_DATA_DIR"])
    src = ROOT / "shared" / "data"
    try:
        dst.mkdir(parents=True, exist_ok=True)
    except OSError:
        return  # sin permisos: los modulos caen a shared/data
    runtime = (
        "lanas_inventario", "movimientos_inventario", "proveedores",
        "lana_cruda", "catalogo_materias", "permisos",
    )
    for name in runtime:
        s, d = src / f"{name}.json", dst / f"{name}.json"
        if s.exists() and not d.exists():
            try:
                shutil.copy2(s, d)
                print(f"[erp] seed inicial: {name}.json -> {dst}")
            except OSError as exc:
                print(f"[erp] WARN no pude sembrar {name}.json: {exc}")


_seed_data_dir()

# reportlab (PDF del pedido a proveedor) se instala en el venv en el DESPLIEGUE
# (está en requirements.txt), NO en runtime: instalar paquetes desde el worker
# web es un riesgo de cadena de suministro y una dependencia de red frágil. El
# import de pdf_pedido_proveedor es defensivo: si faltara, el PDF queda
# deshabilitado con mensaje claro y la app arranca igual.

# Carga la app Flask (app.py en la raiz del repo) y la envuelve con el
# normalizador de PATH_INFO como capa mas externa.
sys.path.insert(0, str(ROOT))
from app import app as _flask_app  # noqa: E402

application = decode_path_info(_flask_app)
