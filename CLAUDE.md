# CLAUDE.md

Contexto para Claude Code. Se carga al arrancar sesión en este repo.

---

## Qué es este proyecto

**ERP de producción** de Moquetas Rols, S.A. Empieza con el módulo de
**Compras / Materias primas**, extraído de Rols One (`rols-calculadora`) para
crecer de forma independiente. La idea: la parte de producción va a crecer
mucho, así que vive en su propio repo y se conectará con Rols One **por API**.

- Usuario: **Fernando Ferrer** (`fernando@rolscarpets.com`) — admin.
- Repo GitHub: `ROLSCARPETS/rols-erp-produccion`.
- Origen del código: `ROLSCARPETS/rols-one` → `rols-calculadora` (subsistema
  de materias primas / compras). La calculadora de presupuestos y las fichas
  de producto/escandallo **NO** se copiaron: se quedan en Rols One.

---

## Arquitectura

App Flask **autónoma** (un solo `app.py`). A diferencia de Rols One (que
compone 5 apps bajo un dominio con `DispatcherMiddleware`), aquí hay una sola.

```
app.py             ← rutas de Compras (extraídas de rols-calculadora/app.py)
shared/scripts/    ← módulos de datos vendorizados (rols_shared, proveedores,
                     materias_primas, catalogo_materias, lanas_inventario,
                     movimientos_inventario, lana_cruda, pdf_pedido_proveedor,
                     permisos)
shared/data/       ← JSON seed (runtime → ROLS_DATA_DIR en prod)
shared/static/     ← sso-guard.js, lang-switcher/ (servidos en /shared/)
templates/ static/ ← UI de Compras
```

Los módulos de `shared/scripts/` localizan sus datos en `shared/data/` (por
`Path(__file__).parent.parent / "data"`) o en `ROLS_DATA_DIR` si está definido.
Por eso `scripts/` y `data/` deben seguir siendo hermanos dentro de `shared/`.

## La costura con Rols One (pendiente, por API)

- El **escandallo** de producto (en Rols One) referencia las calidades de lana
  de aquí por su `calidad_id` (slug estable, p.ej. `65-2c__pais-normal`). Esos
  IDs se conservaron intactos en la extracción.
- Cuando se implemente la integración: este ERP expone las calidades/stock de
  lana por API y Rols One (calculadora/escandallo) las consume. No duplicar
  datos: una sola fuente de verdad por dominio (Compras aquí, comercial allí).
- El SSO sigue siendo Rols One (`rols-cuentas`). `sso-guard.js` y el `nav`
  (`shared/scripts/rols_shared.py`) apuntan a la suite; al desplegar este ERP
  en su propio dominio habrá que **reapuntar** esas URLs al login de Rols One.

## Convenciones (heredadas de Rols One)

### Paleta Rols
```
--bg-page:#FAF8F6  --bg-card:#FFFFFF  --bg-sidebar:#4D4D4D  --text-sidebar:#D7CDC5
--accent:#D5B38C   --accent-hover:#B89368  --accent-soft:#EFE2CD  --border:#E5DCD2
```

### Reglas críticas
- **DECIMAL** para todo lo monetario y kg (nunca FLOAT).
- **IDs naturales** (slugs estables) donde ya existen (`calidad_id`).
- **Migración/seed idempotente**: correr varias veces sin duplicar.
- **Permisos por rol** (admin / comercial / representante / hilador) vía
  `shared/scripts/permisos.py` + `shared/data/permisos.json`. El header
  `X-Rols-User-Rol` (lo pone `sso-guard.js`) decide; sin header → permisivo
  (llamadas internas). Filtro de UX, no de seguridad.

## Arranque

- Local: `Iniciar ERP Produccion.bat` o `python app.py` → `http://localhost:5060`.
- Flask **no** tiene hot-reload de Python: tras cambios hay que reiniciar.
- Producción: `passenger_wsgi.py` (Plesk/Passenger). Siembra `ROLS_DATA_DIR`
  desde `shared/data` (idempotente) y bootstrapea reportlab.

## Git

- Cuenta autenticada: **ROLSCARPETS**. Repo: `ROLSCARPETS/rols-erp-produccion`.
- `git push` solo cuando se pida explícitamente.
- PowerShell 5.1: `&&`/`||` no existen (usar `; if ($?) { }`).

## Qué NO hacer

- No reintroducir la calculadora de presupuestos ni las fichas de producto/
  escandallo: eso es de Rols One. Aquí solo Compras/producción.
- No romper la relación `scripts/` ↔ `data/` dentro de `shared/`.
