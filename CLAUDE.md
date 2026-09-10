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
                     permisos, muestras_fabricadas)
shared/data/       ← JSON seed (runtime → ROLS_DATA_DIR en prod)
shared/static/     ← sso-guard.js, lang-switcher/ (servidos en /shared/)
templates/ static/ ← UI de Compras
```

Los módulos de `shared/scripts/` localizan sus datos en `shared/data/` (por
`Path(__file__).parent.parent / "data"`) o en `ROLS_DATA_DIR` si está definido.
Por eso `scripts/` y `data/` deben seguir siendo hermanos dentro de `shared/`.

## Muestras fabricadas (`/muestras-fabricadas`)

Seguimiento de prototipos y muestras tejidas en fábrica (sustituye al
`LIBRO DE MUESTRAS.xlsx` de `X:. MUESTRAS`). Módulo
`shared/scripts/muestras_fabricadas.py` (doc jsonstore `muestras_fabricadas`,
seed `shared/data/muestras_fabricadas.json` importado del Excel: 2.337
muestras desde 2015, esquema v5). Permiso propio **`muestras_fabricadas`** (sección
"Rols Producción" en cuentas), separado de `compras` para que el
laboratorio pueda llevar las muestras sin ver costes.

- **Número de M** lo asigna el servidor (`_meta.ultimo_numero + 1`); las
  variantes llevan sufijo (M-5448-C). Los ids NO cambian nunca.
- **Estados** (slugs estables): por_empezar → en_diseno → en_hilatura →
  en_tintoreria → bobinando → esperando_telar → en_telar → en_aprestos →
  terminada; además cancelada y `sin_seguimiento` (solo histórico del
  registro antiguo, no seleccionable). Las muestras de **Print** llevan su
  flujo corto (`FLUJO_PRINT`): por_empezar («Listo para empezar diseño») →
  en_diseno → `revision_diseno` («Listo para revisión diseño») → terminada.
  Las de **Varilla** llevan el diseño por delante del textil (`FLUJO_VARILLA`):
  por_empezar → `listo_diseno` («Listo para empezar diseño») → en_diseno →
  `revision_diseno` → `diseno_listo` («Diseño listo») → en_hilatura → … →
  terminada. Las etapas que solo existen en un flujo propio
  (`ESTADOS_EXCLUSIVOS`: listo_diseno, revision_diseno, diseno_listo) se
  rechazan en backend para las técnicas que no las recorren
  (`etapa_permitida`), también al cambiar de telar estando en una de ellas.
  `etiqueta_estado(estado, telar)` / `MS.etiquetaEstado` dan el label que
  toca, `flujo_de`/`MS.flujoDe` el flujo de la técnica y
  `flujo_que_contiene`/`MS.flujoQueContiene` el flujo con el que se pinta (si
  la etapa actual no está en el de su técnica, el primero que la contenga:
  una Print histórica parada en una etapa textil sigue el flujo completo).
- `archivada` = fuera de "En curso" sin estar terminada (lo que en el Excel
  era mover la fila a la hoja de terminadas).
- `fecha_estimada` = "Fecha estimada muestra lista": previsión que mantiene
  quien la lleva (en rojo si se pasa). `fecha_lista` es la fecha REAL: la fija
  el paso a `terminada` y es la que usan plazos y análisis; en la ficha solo
  se enseña cuando la muestra está terminada.
- `referencia` = "Referencia muestra": resumen corto de una línea (≤120) que
  sale en la columna del listado, en el hero de la ficha y en los correos;
  `descripcion` sigue siendo el texto largo (el listado la enseña si no hay
  referencia). v5 rellenó a mano la referencia de las que estaban en curso
  (`_REFERENCIAS_V5`).
- **Datos técnicos** (solo con telar **Varilla**), en dos bloques en la UI:
  *Datos de tejeduría* (`pasadas`, `altura_felpa`, `n_cuerpos` — textos
  cortos —, `pelo` con etiqueta "Construcción": corte | bucle | corte_bucle |
  estructurado, y `acabado`: latex | sin_aprestar | resina | latex_resina) y
  *Datos de materias* (`material`, `hilos_pua`). Van planos en la muestra; la
  ficha y el alta los enseñan solo si el telar es de varilla (si cambia, se
  conservan).
  `resumen_tecnico()` los junta para el hero y los correos.
- **Diseño adjunto** (`adjuntos[]`): ficheros en
  `ROLS_DATA_DIR/muestras_adjuntos/<id>/<aid>.<ext>` (imagen, PDF, AI/EPS/PSD,
  ZIP, 25 MB máx.); metadatos en la muestra, nunca la ruta. Rutas
  `POST /api/muestras/<id>/adjuntos` (multipart `fichero`) y
  `GET|DELETE /api/muestras/<id>/adjuntos/<aid>` (`?dl=1` fuerza descarga;
  imagen/PDF se abren en la pestaña). Cada adjunto lleva `clase`: `version`
  (las versiones se numeran por orden de subida en la UI), `final` (diseño
  final) u `otro`; `PUT …/adjuntos/<aid>` `{clase}` la cambia. Rastro en el
  historial (`tipo: adjunto`, a = anadido | etiqueta | borrado). Check
  **Verificación de diseño** (`diseno_verificado` + `_por`, `_por_nombre`,
  `_en`, que pone el servidor con el actor al marcarlo y limpia al quitarlo);
  chip "Diseño verificado" en el hero.
- El diario del laboratorio son apuntes fechados (`apuntes[]`); el texto del
  Excel se troceó por fechas (`parsear_diario`) sin pérdida. Cada cambio de
  etapa deja además un apunte automático (`tipo: "estado"`, "Pasa a «…»",
  "Muestra terminada."…) con la nota opcional a continuación.
- `tipo` = `cliente` | `interna` (desarrollo propio; en el libro era el cliente
  "INTERNA ( NANDO )", "MOQUETAS ROLS"...). Las internas no necesitan cliente.
  Prioridad 1 Alta (rojo) · 2 Media (azul) · 3 Baja (verde claro).
- Migraciones de esquema en `cargar()` (version-gated, idempotentes). v2:
  tipo deducido, telares unificados (Escala→Rapier, Solo diseño→Print), dos
  erratas de fecha del libro corregidas y fuera las 6 M de dic-2014.
- **Quien encarga** (`encargada_por` + `encargada_por_usuario`) debe ser un
  usuario de Rols One: `app.py` pide a cuentas `/api/usuarios/con-permiso?permiso=muestras_fabricadas`
  (cache 5 min; si cuentas no responde, se usan los usuarios ya vistos en
  datos). v3 pasó los nombres cortos del libro a su cuenta (Fernando →
  Fernando Ferrández, JM → Jose Manuel Sánchez, Damián, Carmen, Romu, Victor);
  v4: Alberto → Alberto Recio. Paco, Emilio, Blanca, Señor Gómez y Tano quedan
  como "antiguos" (`catalogos.personas_legacy`): filtran el histórico, no
  valen para altas.
- **Próximo hito** (`proximo_hito_fecha` + `proximo_hito`): fecha del siguiente
  paso previsto, la ponen comercial o laboratorio (columna editable en En curso
  y campos en la ficha); en rojo si ya pasó, contador en el KPI En curso;
  terminada/cancelada lo limpian.
- **Avisos por correo** (`shared/scripts/correo.py` + `muestras_avisos.py`): a
  quien encargó la muestra al cambiar de etapa, al terminar/cancelar y el día
  del próximo hito (`hito_avisado` evita repetir). No se avisa a quien hace el
  cambio, salvo en los `HITOS_CLAVE` («Listo para revisión diseño», que pide
  marcar la Verificación de diseño, y «Terminada»), que avisan siempre; y al **crear** una muestra,
  resumen a `laboratorio@rolscarpets.com` (`ROLS_MUESTRAS_LAB_EMAIL`) y a
  quien la crea (`aviso_nueva_muestra`, motivo `nueva` en el historial). Envío como Rols Muestras:
  MTA local de Plesk (localhost:25) por defecto; opcional `ROLS_SMTP_*` /
  `SMTP_*` en el `.env` (app.py lo carga) o `ROLS_DATA_DIR/correo.json`. El
  chequeo de hitos corre en segundo plano como mucho cada 15 min desde
  `before_request` y bajo demanda en `POST /api/muestras/avisos/hitos` (token
  API o Completo, para un cron). Rastro en el historial (`tipo: aviso`).
- **Cliente**: texto libre (prospectos) con buscador sobre el maestro de
  clientes de Navision que tiene Rols One (`/api/navision/clientes`, copia
  diaria de BC; el ERP lo proxya en `/api/muestras/clientes-navision`). Al
  elegir uno se guarda también `cliente_navision` (código C6535...).

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
