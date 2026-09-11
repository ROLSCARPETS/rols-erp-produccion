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
muestras desde 2015, esquema v8). Permiso propio **`muestras_fabricadas`** (sección
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
  terminada. **Colortec** (`FLUJO_COLORTEC`) lleva esas etapas de diseño por
  delante del textil como Varilla, pero sin `diseno_listo`.
  Los **Pompones** y los **Festones** no se tejen (`FLUJO_POMPON`):
  por_empezar →
  en_tintoreria → `revisar_color` («Revisar color», a la vuelta de tintorería)
  → terminada. Las etapas que solo existen en un flujo propio
  (`ESTADOS_EXCLUSIVOS`: listo_diseno, revision_diseno, diseno_listo,
  revisar_color) se
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
- **Datos técnicos** (telares de `TELARES_TECNICOS`: **Varilla**, **Lancetas**,
  **Rapier**, **Colortec**, **Tufting Bucle**, **Tufting Corte**, **Pompón**,
  **Kibby** y **Festón**), en dos bloques en la UI:
  *Datos de tejeduría* (`pasadas`, `altura_felpa`, `n_cuerpos` — textos
  cortos —, `pelo` con etiqueta "Construcción" y `acabado`: latex |
  sin_aprestar | resina | latex_resina | pendiente) y
  *Datos de materias*: la tabla `materias[]`, una fila por cuerpo
  (`{id, cuerpo, materia, hilos_pua, colorido}`, máx. `MAX_MATERIAS` = 12).
  La ficha y el alta los enseñan solo si el telar es de los técnicos (si
  cambia, se conservan). Las **construcciones** dependen del telar
  (`PELOS_POR_TELAR` / `MS.PELOS_POR_TELAR`): Varilla (corte, bucle,
  corte_bucle, estructurado, pendiente), Lancetas (bucle_sencillo,
  tejido_plano, bucle_saltillo, pendiente). Rapier, Colortec y los dos Tufting
  **no eligen**: son siempre `tejido_plano`, `corte`, `bucle` y `corte`
  (`pelo_fijo()` la pone al crear y al cambiar a ese telar, y la UI enseña el
  valor fijo en vez del selector). `pelo` se valida contra la unión de todas,
  así que cambiar de telar nunca deja un valor no válido.
  Toda la configuración va en **`TECNICOS_POR_TELAR`** (espejo en
  `MS.TECNICOS_POR_TELAR`), que además dice: `es_telar` (Pompón, Kibby y
  Festón **no son telares**: el rótulo del bloque dice "técnica X" en vez de
  "telar X"), `tejeduria` (esos tres la llevan a False: solo materias, ver
  `_TEC_SOLO_MATERIAS`), `etiqueta_n` (en los Tufting, `n_cuerpos` se llama
  "Nº de colores"), `etiqueta_cuerpo` (en los tres, la columna de la tabla de
  materias es "Color") y `hilos_pua` (no llevan esa columna). Helpers:
  `config_tecnica`, `etiqueta_n_cuerpos`, `etiqueta_cuerpo`, `lleva_tejeduria`,
  `lleva_hilos_pua`, `es_telar`; el endpoint de catálogos lo sirve en
  `tecnicos_por_telar`.
  La tabla de materias se guarda **entera** en cada cambio (`PUT` con
  `materias`, sin endpoint por fila): el servidor tira las filas que no dicen
  nada de la materia (solo el nº de cuerpo no cuenta) y reaprovecha los `id`
  por posición. v6 pasó los campos planos `material` / `hilos_pua` a una
  primera fila de la tabla. `resumen_tecnico()` junta materias y tejeduría
  para el hero y los correos; `materiales` y `coloridos` de `catalogos` salen
  de las filas ya escritas (datalist). **El alta de un telar técnico exige los
  datos técnicos rellenos** (los campos de tejeduría y todas las casillas
  de cada materia): lo que no se sepa se escribe «Pdte», y en Construcción y
  Acabado está la opción «Pendiente». Es un control del modal de alta (marca en
  rojo lo que falte); el backend no lo exige, para no romper las variantes
  (se crean desde la ficha copiando cliente y telar) ni el histórico.
- **Catálogo de telares**: el de `TELARES_DEFAULT` más los que use alguna
  muestra. La opción «Otro…» del selector **solo añade la opción a ese
  selector** (`MS.gestionarOtro`); el telar entra en el catálogo cuando se
  guarda la muestra (`_anadir_a_catalogo` desde `crear`/`actualizar`). Antes se
  guardaba nada más escribirlo y un valor tecleado por error se quedaba para
  siempre; v8 limpió lo que había caído así (lo que no está en
  `TELARES_DEFAULT` ni usa ninguna muestra).
- **Técnicas retiradas** (`TELARES_RETIRADOS`: Raschel y el **Tufting** a
  secas, que v7 partió en «Tufting Bucle» y «Tufting Corte» — las muestras
  antiguas se quedan como estaban, no se puede saber cuál de los dos era):
  siguen en el
  histórico, en los filtros y en las muestras que ya las llevan, pero no se
  ofrecen al dar de alta ni en el selector de la ficha
  (`catalogos.telares_alta` = el catálogo sin ellas; `telares` sigue completo
  para los filtros). No hay veto en el backend: las variantes de una muestra
  antigua copian su telar.
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
- **Orden del listado**: las dos vistas (En curso e Histórico) van por
  `fecha_solicitud` descendente, la más reciente arriba, con la fecha como
  primera columna; en En curso se puede reordenar pulsando una cabecera.
- **Próximo hito** (`proximo_hito_fecha` + `proximo_hito`): fecha del siguiente
  paso previsto, la ponen comercial o laboratorio (columna editable en En curso
  y campos en la ficha); en rojo si ya pasó, contador en el KPI En curso;
  terminada/cancelada lo limpian.
- **Avisos por correo** (`shared/scripts/correo.py` + `muestras_avisos.py`): a
  quien encargó la muestra al cambiar de etapa, al terminar/cancelar y el día
  del próximo hito (`hito_avisado` evita repetir). No se avisa a quien hace el
  cambio, salvo en los `HITOS_CLAVE` («Listo para revisión diseño», que pide
  marcar la Verificación de diseño, y «Terminada»), que avisan siempre. Las
  **etapas de diseño** suman destinatarios (sale un único correo con todos):
  «Listo para empezar diseño» (`listo_diseno` de Varilla y el `por_empezar` de
  Print, `listo_para_disenar()`) al buzón de diseño
  (`ROLS_MUESTRAS_DISENO_EMAIL`, por defecto `diseno@rolscarpets.com`, sin eñe
  a propósito: una ñ en la parte local exige SMTPUTF8); «Listo para revisión
  diseño» también a quien **creó** la muestra (`creado_por`); «Diseño listo» al
  buzón del laboratorio. Y al **crear** una muestra,
  resumen a `laboratorio@rolscarpets.com` (`ROLS_MUESTRAS_LAB_EMAIL`), a
  quien la crea y, si nace lista para empezar diseño (una Print), a diseño
  (`aviso_nueva_muestra`, motivo `nueva` en el historial). Envío como Rols Muestras:
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
