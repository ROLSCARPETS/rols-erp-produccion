# Rols ERP Producción — módulo de Compras

ERP de producción de **Moquetas Rols, S.A.** Este repo arranca con el módulo de
**Compras / Materias primas**, extraído de [Rols One](https://github.com/ROLSCARPETS/rols-one)
(`rols-calculadora`) para crecer de forma independiente como ERP de producción.

App Flask **autónoma**: no depende del árbol de Rols One. Trae vendorizados sus
propios módulos de datos, plantillas y assets.

## Qué incluye (Compras)

- **Materias primas (lanas):** listado de calidades, fichas, clasificación,
  planificación y límites de reposición.
- **Proveedores:** ficha, KPIs, calidades asociadas.
- **Inventario de lanas:** partidos/lotes (en almacén / en camino), consumos,
  traslados y movimientos de inventario.
- **Lana cruda:** contenedores, órdenes (apartar / cerrar / anular).
- **Pedidos de compra (Kanban):** generación de pedido a proveedor, seguimiento
  de estado, recepción y PDF del pedido.

## Qué NO incluye (se queda en Rols One)

- Calculadora de presupuestos, termosoldado, condiciones, divisas, clientes Navision.
- **Fichas de producto y escandallo** (llevan info comercial: precios de venta,
  etc.). El escandallo apunta a las calidades de lana por `calidad_id`; la
  conexión Compras ↔ escandallo se hará **por API** más adelante
  (ver [CLAUDE.md](CLAUDE.md)).

## Estructura

```
.
├── app.py                  ← app Flask (solo rutas de Compras)
├── passenger_wsgi.py       ← entrypoint de despliegue (Plesk/Passenger)
├── requirements.txt
├── Iniciar ERP Produccion.bat
├── templates/              ← materias_primas, materia_prima_detalle, proveedor_detalle
├── static/                 ← CSS/JS/i18n de la UI de Compras
└── shared/
    ├── scripts/            ← módulos de datos (lanas_inventario, proveedores, ...)
    ├── data/               ← JSON SEED (en prod la verdad vive en ROLS_DATA_DIR)
    └── static/             ← assets comunes servidos en /shared/ (sso-guard, lang-switcher)
```

## Arrancar en local

Doble clic en **`Iniciar ERP Produccion.bat`** (instala Flask/reportlab la
primera vez) o:

```
python app.py
```

Servidor en `http://localhost:5060`. Los datos de runtime se leen/escriben en
`shared/data/*.json` (en local) o en `ROLS_DATA_DIR` (en producción).

## Datos

JSON con escritura atómica (`tmp.replace`) + `RLock` + `lru_cache`, en
`shared/data/`. Los `*.json` del repo son **seed**: en producción el
`passenger_wsgi.py` los siembra (idempotente) en `ROLS_DATA_DIR`, fuera del
docroot, para que persistan entre deploys.

## Requisitos

- Python 3.9+ en el PATH.
- Flask (obligatorio) y reportlab (para el PDF de pedido a proveedor).
