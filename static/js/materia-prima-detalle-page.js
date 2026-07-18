// Cache local del ultimo dataset cargado, lo usa el boton "Editar" de
// los lotes para inflar el modal sin volver a pedir al servidor.
let _DATOS = null;
// Cache del catalogo de clasificaciones / materiales / titulos. Lo
// cargamos una vez al abrir la ficha y lo reusamos para poblar los
// selects y para traducir id → label en el subtitulo del hero.
let _CATALOGO = { clasificaciones: [], materiales_felpa: [], titulos: [] };
function currentUsuario() {
  try { return (window.__rolsUser && window.__rolsUser.username) || ''; }
  catch (_) { return ''; }
}

// =====================================================================
// Catalogo editable de clasificaciones y materiales
// =====================================================================
//
// Los selects "Clasificacion de materia" y "Material" ya no son hardcoded
// en HTML — sus opciones vienen de /api/catalogos/materia y el usuario
// puede anadir nuevas desde la propia ficha (opcion "+ Nuevo..." al
// final de cada select).

async function cargarCatalogo() {
  try {
    const r = await fetch('/api/catalogos/materia');
    if (!r.ok) throw new Error('HTTP ' + r.status);
    _CATALOGO = await r.json();
  } catch (e) {
    // Fallback silencioso a las opciones por defecto si algo falla
    _CATALOGO = {
      clasificaciones: [
        {id: 'materia-felpa', label: 'Materia felpa'},
        {id: 'basamentos',    label: 'Basamentos'},
        {id: 'otros',         label: 'Otros'},
      ],
      materiales_felpa: [
        {id: 'lana-hilada', label: 'Lana hilada'},
        {id: 'lana-bruto',  label: 'Lana en bruto'},
        {id: 'pp',          label: 'Polipropileno (PP)'},
        {id: 'pes',         label: 'Poliéster (PES)'},
      ],
      titulos: [],
    };
  }
  poblarSelectsCatalogo();
}

// Repobla los selects con las opciones del catalogo. Conserva el valor
// seleccionado si sigue siendo valido. Anade siempre la entrada
// "+ Nuevo..." al final.
//
// useLabel=true (selects de Titulo): el value de cada opcion es el
//   `label` (lo que se guarda en variante.titulo es el texto literal,
//   no un slug). Asi el valor enviado al backend coincide con el campo
//   tal como esta en el JSON.
// useLabel=false (selects de Clasificacion / Material): el value es el
//   `id` slug (lo que se guarda en variante.clasificacion /
//   variante.material_felpa). El label solo se muestra al usuario.
function poblarSelectsCatalogo() {
  const _pob = (sel, lista, opts) => {
    if (!sel) return;
    const useLabel = !!(opts && opts.useLabel);
    const placeholder = (opts && opts.placeholder) || '— seleccionar —';
    const prev = sel.value;
    sel.innerHTML = `<option value="">${escapeHtml(placeholder)}</option>` +
      lista.map(it => {
        const v = useLabel ? (it.label || it.id) : it.id;
        return `<option value="${escapeHtml(v)}">${escapeHtml(it.label)}</option>`;
      }).join('') +
      `<option value="__nuevo__" style="font-style:italic; color:#c8a771">+ Añadir nuevo…</option>` +
      (lista.length
        ? `<option value="__gestionar__" style="font-style:italic; color:#7a7a7a">⚙ Gestionar lista…</option>`
        : '');
    // Conservar valor previo si sigue siendo opcion valida
    const valoresValidos = lista.map(it => useLabel ? (it.label || it.id) : it.id);
    if (prev && valoresValidos.includes(prev)) sel.value = prev;
  };
  _pob(document.getElementById('mpd-clasif'),   _CATALOGO.clasificaciones || []);
  _pob(document.getElementById('mpd-material'), _CATALOGO.materiales_felpa || []);
  _pob(document.getElementById('mpd-titulo-select'), _CATALOGO.titulos     || [],
       {useLabel: true, placeholder: '— sin asignar —'});
}

// Devuelve el label de un id, consultando el catalogo cacheado. Si no
// existe (catalogo no cargado o id huerfano), devuelve el id literal.
function labelCatalogo(tipo, id) {
  if (!id) return '';
  const lista = tipo === 'clasificacion'
                ? (_CATALOGO.clasificaciones || [])
                : (_CATALOGO.materiales_felpa || []);
  const item = lista.find(it => it.id === id);
  return item ? item.label : id;
}

// Cuando el usuario selecciona "+ Nuevo...", abrimos un prompt para
// pedir el label, POSTeamos al endpoint, recargamos el catalogo y
// pre-seleccionamos el nuevo valor. Si cancela, restauramos el valor
// previo. Funciona para los DOS selects (mismo handler).
async function _onSelectCatalogoChange(e) {
  const sel = e.target;
  // Si es "gestionar", abrimos el modal de gestion y restauramos el
  // valor previo del select (el "gestionar" no es una seleccion real)
  if (sel.value === '__gestionar__') {
    const prev = sel.dataset.prevValue || '';
    sel.value = prev;
    abrirGestionCatalogo(sel.dataset.catalogo, sel);
    return;
  }
  if (sel.value !== '__nuevo__') return;
  const tipo = sel.dataset.catalogo;  // 'clasificacion' | 'material_felpa' | 'titulo'
  const meta = {
    clasificacion:  {titulo: 'Nueva clasificación de materia', ph: 'Ej. Hilados técnicos'},
    material_felpa: {titulo: 'Nuevo material',                  ph: 'Ej. Algodón'},
    titulo:         {titulo: 'Nuevo título',                    ph: 'Ej. 120/2C'},
  }[tipo] || {titulo: 'Nuevo valor', ph: ''};
  // Estado previo (antes de seleccionar "+ Nuevo")
  const prev = sel.dataset.prevValue || '';
  const { ok, valor } = await mostrarPrompt({
    titulo: meta.titulo,
    mensaje: 'Escribe el nombre tal como quieres que aparezca en los selects.',
    etiqueta: 'Nombre',
    placeholder: meta.ph,
    textoConfirmar: '+ Añadir',
    validador: (v) => {
      v = (v || '').trim();
      if (!v) return 'No puede estar vacío';
      if (v.length > 80) return 'Máximo 80 caracteres';
      return null;
    },
  });
  if (!ok) {
    // Restauramos el valor anterior — no disparamos otro change
    sel.value = prev;
    return;
  }
  try {
    const r = await fetch(`/api/catalogos/materia/${encodeURIComponent(tipo)}`, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({label: valor}),
    });
    const ct = r.headers.get('content-type') || '';
    if (!ct.includes('application/json')) {
      throw new Error(`El servidor no reconoce este endpoint (HTTP ${r.status}). ` +
                      `Reinicia "Iniciar ERP Produccion.bat".`);
    }
    const d = await r.json();
    if (!r.ok) throw new Error(d.error || 'HTTP ' + r.status);
    // Recargar catalogo y seleccionar el nuevo valor. Para titulo
    // usamos el LABEL como value (porque variante.titulo guarda label);
    // para clasificacion/material usamos el ID (slug).
    await cargarCatalogo();
    const nuevoVal = tipo === 'titulo' ? (d.label || d.id) : d.id;
    sel.value = nuevoVal;
    sel.dataset.prevValue = nuevoVal;
    // Disparar el guardado adecuado segun el tipo
    if (tipo === 'titulo') {
      guardarTitulo();
    } else {
      if (tipo === 'clasificacion') ajustarVisibilidadMaterial();
      guardarClasificacion();
    }
  } catch (err) {
    sel.value = prev;
    await mostrarAlerta({titulo: 'Error',
                         mensaje: err.message, tipo: 'danger'});
  }
}

// Trackear el valor previo de cada select para poder restaurarlo si
// el usuario cancela el prompt de "+ Nuevo..."
function _trackPrevValue(sel) {
  sel.dataset.prevValue = sel.value;
  sel.addEventListener('focus', () => { sel.dataset.prevValue = sel.value; });
}

// =====================================================================
// Modal "Gestionar catalogo": lista las entradas del tipo seleccionado
// con un boton × por fila. Las entradas en uso (que alguna calidad las
// tiene asignadas) se bloquean — el backend devuelve 409 con la lista
// de calidades que las usan, y la mostramos como tooltip.
// =====================================================================
let _GESTION_CTX = null;  // {tipo, sourceSel}

const TIPO_LABEL = {
  clasificacion:  {titulo: 'Gestionar clasificaciones', singular: 'clasificación'},
  material_felpa: {titulo: 'Gestionar materiales',      singular: 'material'},
  titulo:         {titulo: 'Gestionar títulos',         singular: 'título'},
};

function _calculaUsoLocal(tipo, id, label) {
  // Calculo aproximado de "en uso" basado en _DATOS local (solo cuenta
  // ESTA calidad). El backend hace el calculo global; aqui solo mostramos
  // si esta calidad lo usa, como hint. El bloqueo real lo decide el 409.
  if (!_DATOS) return 0;
  const c = _DATOS.calidad || {};
  if (tipo === 'clasificacion'  && c.clasificacion  === id)    return 1;
  if (tipo === 'material_felpa' && c.material_felpa === id)    return 1;
  if (tipo === 'titulo'         && (c.titulo || '') === label) return 1;
  return 0;
}

function abrirGestionCatalogo(tipo, sourceSel) {
  if (!TIPO_LABEL[tipo]) return;
  _GESTION_CTX = {tipo, sourceSel};
  const lista = tipo === 'clasificacion'  ? (_CATALOGO.clasificaciones  || [])
              : tipo === 'material_felpa' ? (_CATALOGO.materiales_felpa || [])
              :                              (_CATALOGO.titulos         || []);
  document.getElementById('mpd-cat-titulo').textContent = TIPO_LABEL[tipo].titulo;
  document.getElementById('mpd-cat-error').classList.remove('show');
  document.getElementById('mpd-cat-error').textContent = '';
  const cont = document.getElementById('mpd-cat-lista');
  if (!lista.length) {
    cont.innerHTML = '<div style="color:#9a9a9a; font-style:italic; padding:0.8rem; text-align:center">Lista vacía.</div>';
  } else {
    cont.innerHTML = lista.map(it => {
      const hintEnUso = _calculaUsoLocal(tipo, it.id, it.label)
        ? `<span style="color:#9b1c1c; font-size:0.72rem; margin-left:0.5rem">(esta calidad lo usa)</span>`
        : '';
      return `
        <div class="mpd-cat-fila" data-id="${escapeHtml(it.id)}" data-label="${escapeHtml(it.label || it.id)}"
             style="display:flex; align-items:center; gap:0.6rem; padding:0.5rem 0.7rem;
                    border:1px solid var(--border); border-radius:8px; background:#fff">
          <span style="flex:1; font-size:0.9rem">${escapeHtml(it.label)}${hintEnUso}</span>
          <button type="button" class="mpd-cat-borrar mp-btn-row"
                  data-id="${escapeHtml(it.id)}" data-label="${escapeHtml(it.label || it.id)}"
                  style="color:#9b1c1c; border-color:#e8c2c2">× Borrar</button>
        </div>`;
    }).join('');
  }
  document.getElementById('mpd-modal-cat').classList.add('open');
}

function _cerrarGestionCatalogo() {
  document.getElementById('mpd-modal-cat').classList.remove('open');
  _GESTION_CTX = null;
}
document.getElementById('mpd-cat-cerrar').addEventListener('click', _cerrarGestionCatalogo);
document.getElementById('mpd-modal-cat').addEventListener('click', (e) => {
  if (e.target.id === 'mpd-modal-cat') _cerrarGestionCatalogo();
});

// Click delegado en los botones × de la lista
document.getElementById('mpd-cat-lista').addEventListener('click', async (e) => {
  const btn = e.target.closest('.mpd-cat-borrar');
  if (!btn || !_GESTION_CTX) return;
  const id = btn.dataset.id;
  const label = btn.dataset.label || id;
  const tipo = _GESTION_CTX.tipo;
  // Confirmar
  const {ok} = await mostrarConfirmacion({
    titulo: `Borrar "${label}"`,
    mensaje: `¿Eliminar "${label}" del catálogo? Si alguna calidad lo usa, el servidor lo impedirá automáticamente.`,
    textoConfirmar: '× Borrar',
    tipo: 'danger',
  });
  if (!ok) return;
  btn.disabled = true;
  const errBox = document.getElementById('mpd-cat-error');
  errBox.classList.remove('show');
  try {
    const r = await fetch(
      `/api/catalogos/materia/${encodeURIComponent(tipo)}/${encodeURIComponent(id)}`,
      {method: 'DELETE'}
    );
    const ct = r.headers.get('content-type') || '';
    if (!ct.includes('application/json')) {
      throw new Error(`El servidor no reconoce este endpoint (HTTP ${r.status}). ` +
                      `Reinicia "Iniciar ERP Produccion.bat".`);
    }
    const d = await r.json();
    if (r.status === 409) {
      // En uso — mostrar la lista de calidades afectadas
      const calsTxt = (d.en_uso || [])
        .slice(0, 8)
        .map(c => `${c.titulo || ''} ${c.tipo || ''}${c.proveedor ? ' (' + c.proveedor + ')' : ''}`.trim())
        .join(' · ');
      const masTxt = (d.en_uso || []).length > 8 ? ` (+${d.en_uso.length - 8} más)` : '';
      errBox.textContent = `No se puede borrar — ${(d.en_uso || []).length} calidad(es) lo usan: ${calsTxt}${masTxt}`;
      errBox.classList.add('show');
      btn.disabled = false;
      return;
    }
    if (!r.ok) throw new Error(d.error || 'HTTP ' + r.status);
    // Borrado OK: recargar catalogo y re-pintar el modal + selects
    await cargarCatalogo();
    abrirGestionCatalogo(tipo, _GESTION_CTX.sourceSel);
  } catch (err) {
    errBox.textContent = err.message;
    errBox.classList.add('show');
    btn.disabled = false;
  }
});

function escapeHtml(s) {
  return String(s == null ? '' : s).replace(/[&<>"']/g, c =>
    ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}
function fmtNum(n, dec=0) {
  if (n == null || isNaN(n)) return '—';
  return Number(n).toLocaleString('es-ES', {
    minimumFractionDigits: dec, maximumFractionDigits: dec,
    useGrouping: 'always',
  });
}
function fmtKg(n)  { return n == null || isNaN(n) ? '—' : fmtNum(n, 0) + ' kg'; }
function fmtEur(n) { return n == null || isNaN(n) ? '—' : fmtNum(n, 2) + ' €/kg'; }
function fmtFecha(s) {
  if (!s) return '—';
  // ISO date or datetime → dd/mm/yyyy
  const d = new Date(s);
  if (isNaN(d.getTime())) return s;
  return d.toLocaleDateString('es-ES');
}
function provKey(p) { return (p || '').split('/')[0].trim().toUpperCase(); }

// Slug del proveedor (sin acentos, minusculas, con guiones). Igual que
// el backend en proveedores.py: usamos esto para construir links a la
// ficha del proveedor (el id estable es ese slug).
function slugProveedor(s) {
  return (s || '').normalize('NFKD').replace(/[̀-ͯ]/g, '')
                   .toLowerCase().trim()
                   .replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '');
}

async function cargar() {
  try {
    const r = await fetch('/api/materia-prima/' + encodeURIComponent(CAL_ID));
    if (r.status === 404) {
      document.getElementById('mpd-titulo').textContent = 'No encontrada';
      document.getElementById('mpd-tipo').textContent = '';
      ['mpd-lotes-tbody', 'mpd-precios-tbody', 'mpd-consumos-tbody'].forEach(id => {
        document.getElementById(id).innerHTML = '<tr><td colspan="9" class="mpd-empty">Esta calidad no existe.</td></tr>';
      });
      return;
    }
    const d = await r.json();
    if (!r.ok) throw new Error(d.error || 'HTTP ' + r.status);
    _DATOS = d;
    pintarCabecera(d);
    pintarLotes(d.lotes || []);
    pintarPrecios(d.precios || []);
    pintarConsumos(d.consumos || []);
  } catch (err) {
    document.getElementById('mpd-lotes-tbody').innerHTML =
      `<tr><td colspan="9" class="mpd-empty">Error: ${escapeHtml(err.message)}</td></tr>`;
  }
}

function pintarCabecera(d) {
  const c = d.calidad;
  const variantes = d.variantes || [];
  const titulo = (c.titulo || '').trim() || c.tipo || c.calidad_id;
  document.title = titulo + ' — Rols ERP Producción';
  document.getElementById('mpd-titulo').textContent = titulo;
  document.getElementById('mpd-tipo').textContent = c.tipo || '';
  document.getElementById('mpd-bread-calidad').textContent = `${titulo} · ${c.tipo || ''}`;
  // Stock total: muestra TODO el stock disponible (Rols + reservado en
  // proveedor). Si hay algo en proveedor, añadimos sub-texto con el
  // breakdown para que el usuario sepa cuanto puede tocar ya y cuanto
  // tiene que pedir el traslado.
  const sumaKgProv = (d.lotes || [])
    .filter(l => l.tipo === 'fisico')
    .reduce((s, l) => s + (Number(l.kg_proveedor) || 0), 0);
  const totalRols  = Number(c.total_kg) || 0;
  const stockEl = document.getElementById('mpd-kpi-stock');
  if (sumaKgProv > 0) {
    stockEl.innerHTML = `${fmtKg(totalRols + sumaKgProv)}` +
      `<div style="font-size:0.7rem; font-weight:500; color:#7a7a7a; margin-top:0.15rem">` +
      `${fmtKg(totalRols)} Rols + <span style="color:#2c5b8a">${fmtKg(sumaKgProv)} proveedor</span></div>`;
  } else {
    stockEl.textContent = fmtKg(totalRols);
  }
  document.getElementById('mpd-kpi-coste').textContent =
    c.coste_medio_kg != null ? fmtEur(c.coste_medio_kg) : '—';
  // KPIs editables: limite_kg (Cantidad min. seguridad) y kg_a_pedir
  // (Cantidad de reposicion). Vienen agregados de todas las variantes.
  document.getElementById('mpd-kpi-limite').value = c.limite_kg || '';
  document.getElementById('mpd-kpi-pedir').value  = c.kg_a_pedir || '';
  // Clasificacion + material (solo si clasificacion = materia-felpa)
  document.getElementById('mpd-clasif').value   = c.clasificacion || '';
  document.getElementById('mpd-material').value = c.material_felpa || '';
  // El titulo se almacena como label literal (p.ej. "100/2C"). El
  // backend ya auto-sincroniza el catalogo con los titulos en uso, asi
  // que en teoria todos los titulos de las calidades existentes ya
  // estan como opcion. Como salvaguarda, si por algun motivo el valor
  // actual no esta, lo anadimos al cache local y al select como una
  // opcion mas (sin etiquetar de "no en catalogo" — luego el backend
  // lo registrara permanentemente en el proximo refresh).
  const _selT = document.getElementById('mpd-titulo-select');
  const titActual = (c.titulo || '').trim();
  if (titActual && !(_CATALOGO.titulos || []).some(t => (t.label || t.id) === titActual)) {
    _CATALOGO.titulos = [...(_CATALOGO.titulos || []), {id: titActual, label: titActual}];
    poblarSelectsCatalogo();
  }
  _selT.value = titActual;
  _selT.dataset.prevValue = titActual;
  // Nombre comercial de la calidad (campo `tipo`): texto libre
  const _inpTipo = document.getElementById('mpd-tipo-input');
  if (_inpTipo) {
    _inpTipo.value = c.tipo || '';
    _inpTipo.dataset.prevValue = _inpTipo.value;
  }
  ajustarVisibilidadMaterial();
  // Proveedores como links a su ficha (abre la tab Proveedores con el
  // proveedor correspondiente auto-expandido). Cada uno lleva un × al
  // lado para quitarlo de la calidad. La salvaguarda real esta en el
  // backend (no permite si hay kg vivo o pedidos abiertos sin forzar).
  const provsEl = document.getElementById('mpd-kpi-provs');
  // Filtramos placeholders: variantes con proveedor vacio (creadas con
  // "Anadir nueva materia prima" antes de asignar el primer proveedor
  // real). No tiene sentido pintarlas como chip vacio.
  const variantesConProv = variantes.filter(v => (v.proveedor || '').trim());
  if (variantesConProv.length) {
    provsEl.innerHTML = variantesConProv.map(v => {
      const slug = slugProveedor(v.proveedor || '');
      const nombre = v.proveedor || '';
      return `<span class="mpd-prov-chip">` +
        `<a href="/materias-primas#proveedores:${encodeURIComponent(slug)}"
            class="mpd-prov-link"
            title="Ver ficha del proveedor">${escapeHtml(nombre)}</a>` +
        `<button type="button" class="mpd-prov-quitar"
                 data-prov="${escapeHtml(nombre)}"
                 title="Quitar ${escapeHtml(nombre)} de esta calidad"
                 aria-label="Quitar proveedor ${escapeHtml(nombre)}">×</button>` +
        `</span>`;
    }).join(' ');
  } else {
    provsEl.innerHTML = '<span style="color:#9a9a9a; font-size:0.82rem; font-style:italic">' +
                        'Sin proveedor — añade uno con + Añadir ↓</span>';
  }
  // Pedidos en camino: la card solo se muestra si hay alguno (>0). Si
  // no, esconderla evita ruido visual en el caso comun.
  const enCamino = (d.lotes || []).filter(l => l.ubicacion === 'en-camino').length;
  const enCaminoCard = document.getElementById('mpd-kpi-encamino-card');
  document.getElementById('mpd-kpi-encamino').textContent = enCamino + (enCamino === 1 ? ' pedido' : ' pedidos');
  if (enCaminoCard) enCaminoCard.classList.toggle('hidden', enCamino === 0);

  // Subtitulo del hero: "Materia felpa · Lana hilada" (o solo clasificacion,
  // o "—" si no hay nada). Asi de un vistazo se ve el tipo de materia sin
  // tener que mirar los selects de Configuracion. Los labels se traducen
  // contra el catalogo cacheado (que incluye los anadidos por el usuario).
  const partes = [];
  if (c.clasificacion)  partes.push(labelCatalogo('clasificacion',  c.clasificacion));
  if (c.material_felpa) partes.push(labelCatalogo('material_felpa', c.material_felpa));
  const subEl = document.getElementById('mpd-hero-subtitle');
  if (subEl) subEl.textContent = partes.length ? partes.join(' · ') : '—';

  // Estado de la calidad: en-camino > pedir > bajo > ok > sin. Calculado
  // sobre los AGREGADOS de calidad (no por variante), porque la card
  // operativa del Kanban tambien es por calidad.
  const stock  = Number(c.total_kg)   || 0;
  const limite = Number(c.limite_kg)  || 0;
  let estado;
  if (enCamino > 0)               estado = 'en-camino';
  else if (limite <= 0)           estado = 'sin';
  else if (stock <= limite)       estado = 'pedir';
  else if (stock <= limite * 1.3) estado = 'bajo';
  else                            estado = 'ok';
  const LABEL = {
    'en-camino': 'Pedido en camino',
    'pedir':     'A pedir',
    'bajo':      'Stock bajo',
    'ok':        'OK',
    'sin':       'Sin mínimo de seguridad',
  };
  const chip = document.getElementById('mpd-kpi-estado');
  chip.className = 'mpd-chip-estado estado-' + estado;
  chip.textContent = LABEL[estado];
}

// Guardar inline limite_kg / kg_a_pedir agregados a nivel calidad
async function guardarKpiCalidad(campo, valor, inp) {
  inp.classList.remove('saved-ok');
  inp.classList.add('saving');
  try {
    const r = await fetch(`/api/materia-prima/${encodeURIComponent(CAL_ID)}/planificacion`, {
      method: 'PUT',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({campo, valor}),
    });
    const ct = r.headers.get('content-type') || '';
    if (!ct.includes('application/json')) {
      throw new Error(`El servidor no reconoce este endpoint (HTTP ${r.status}). ` +
                      `Reinicia "Iniciar ERP Produccion.bat".`);
    }
    const d = await r.json();
    if (!r.ok) throw new Error(d.error || 'HTTP ' + r.status);
    inp.classList.remove('saving');
    inp.classList.add('saved-ok');
    setTimeout(() => inp.classList.remove('saved-ok'), 700);
  } catch (err) {
    inp.classList.remove('saving');
    await mostrarAlerta({titulo: 'Error guardando ' + campo,
                         mensaje: err.message, tipo: 'danger'});
  }
}
document.getElementById('mpd-kpi-limite').addEventListener('change', (e) =>
  guardarKpiCalidad('limite_kg', e.target.value, e.target));
document.getElementById('mpd-kpi-pedir').addEventListener('change', (e) =>
  guardarKpiCalidad('kg_a_pedir', e.target.value, e.target));

// Clasificacion + material (felpa). El select Material solo se ve
// cuando Clasificacion = 'materia-felpa'.
function ajustarVisibilidadMaterial() {
  const clasif = document.getElementById('mpd-clasif').value;
  const grupoMat = document.getElementById('mpd-grupo-material');
  const grupoTit = document.getElementById('mpd-grupo-titulo');
  // El select "Titulo" tambien aplica solo a materia-felpa (los titulos
  // son grosor/numero de hilos: 65/2C, 100/2C... solo tiene sentido en
  // hilados). Para basamentos / otros no se muestra.
  if (clasif === 'materia-felpa') {
    grupoMat.classList.remove('oculto');
    grupoTit.classList.remove('oculto');
  } else {
    grupoMat.classList.add('oculto');
    grupoTit.classList.add('oculto');
    document.getElementById('mpd-material').value = '';
    // El titulo no se limpia automaticamente: aunque la clasificacion
    // cambie a basamentos, el titulo es metadatos historicos del
    // calidad y no queremos perderlo. Solo lo ocultamos del UI.
  }
}

async function guardarClasificacion() {
  const sel = document.getElementById('mpd-clasif');
  const matSel = document.getElementById('mpd-material');
  const clasif = sel.value;
  const material = matSel.value || null;
  if (!clasif) return;  // sin clasificacion no guardamos
  [sel, matSel].forEach(s => { s.classList.remove('saved-ok'); s.classList.add('saving'); });
  try {
    const r = await fetch(`/api/materia-prima/${encodeURIComponent(CAL_ID)}/clasificacion`, {
      method: 'PUT',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({clasificacion: clasif, material_felpa: material}),
    });
    const ct = r.headers.get('content-type') || '';
    if (!ct.includes('application/json')) {
      throw new Error(`El servidor no reconoce este endpoint (HTTP ${r.status}). ` +
                      `Reinicia "Iniciar ERP Produccion.bat".`);
    }
    const d = await r.json();
    if (!r.ok) throw new Error(d.error || 'HTTP ' + r.status);
    [sel, matSel].forEach(s => { s.classList.remove('saving'); s.classList.add('saved-ok'); });
    setTimeout(() => [sel, matSel].forEach(s => s.classList.remove('saved-ok')), 700);
  } catch (err) {
    [sel, matSel].forEach(s => s.classList.remove('saving'));
    await mostrarAlerta({titulo: 'Error guardando clasificación',
                         mensaje: err.message, tipo: 'danger'});
  }
}

// Guarda el titulo de la calidad. A diferencia de clasificacion /
// material, el titulo se almacena como LABEL (texto literal "100/2C"),
// no como slug, porque el `id` estable de la calidad/variante ya esta
// fijo. Endpoint dedicado: PUT /api/materia-prima/<cid>/titulo
async function guardarTitulo() {
  const sel = document.getElementById('mpd-titulo-select');
  const titulo = sel.value || '';
  sel.classList.remove('saved-ok');
  sel.classList.add('saving');
  try {
    const r = await fetch(`/api/materia-prima/${encodeURIComponent(CAL_ID)}/titulo`, {
      method: 'PUT',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({titulo}),
    });
    const ct = r.headers.get('content-type') || '';
    if (!ct.includes('application/json')) {
      throw new Error(`El servidor no reconoce este endpoint (HTTP ${r.status}). ` +
                      `Reinicia "Iniciar ERP Produccion.bat".`);
    }
    const d = await r.json();
    if (!r.ok) throw new Error(d.error || 'HTTP ' + r.status);
    sel.classList.remove('saving');
    sel.classList.add('saved-ok');
    setTimeout(() => sel.classList.remove('saved-ok'), 700);
    // Refrescamos los datos: el titulo afecta al H1 de la ficha
    // ("nylon luna nylon luna" → "100/2C nylon luna") y al subtitulo.
    cargar();
  } catch (err) {
    sel.classList.remove('saving');
    await mostrarAlerta({titulo: 'Error guardando título',
                         mensaje: err.message, tipo: 'danger'});
  }
}

// Wire-up de los selects de Clasificacion + Material + Titulo:
// - Detectan "+ Nuevo..." y abren prompt para anadir al catalogo
// - Si es una opcion normal, guardan al backend y ajustan visibilidad
const _selClasif   = document.getElementById('mpd-clasif');
const _selMaterial = document.getElementById('mpd-material');
const _selTitulo   = document.getElementById('mpd-titulo-select');
_trackPrevValue(_selClasif);
_trackPrevValue(_selMaterial);
_trackPrevValue(_selTitulo);
// Los DOS sentinels ('__nuevo__' y '__gestionar__') se desvian al handler
// del catalogo: antes solo se desviaba '__nuevo__', y elegir "⚙ Gestionar
// lista…" caia al guardado normal con el sentinel como valor (llegaba a
// renombrar el titulo de la calidad a "__gestionar__").
_selClasif.addEventListener('change', async (e) => {
  if (e.target.value === '__nuevo__' || e.target.value === '__gestionar__') {
    await _onSelectCatalogoChange(e);
    return;
  }
  ajustarVisibilidadMaterial();
  guardarClasificacion();
  _selClasif.dataset.prevValue = _selClasif.value;
});
_selMaterial.addEventListener('change', async (e) => {
  if (e.target.value === '__nuevo__' || e.target.value === '__gestionar__') {
    await _onSelectCatalogoChange(e);
    return;
  }
  guardarClasificacion();
  _selMaterial.dataset.prevValue = _selMaterial.value;
});
_selTitulo.addEventListener('change', async (e) => {
  if (e.target.value === '__nuevo__' || e.target.value === '__gestionar__') {
    await _onSelectCatalogoChange(e);
    return;
  }
  guardarTitulo();
  _selTitulo.dataset.prevValue = _selTitulo.value;
});

// ===== Nombre de la calidad (campo `tipo`) =====
// Input de texto libre. Se guarda al hacer blur o pulsar Enter; no en
// cada tecla para no spamear el endpoint mientras escribes. Si dejas
// el campo vacio se restaura al valor previo (no se permite vacio).
async function guardarTipo() {
  const inp = document.getElementById('mpd-tipo-input');
  if (!inp) return;
  const nuevo = (inp.value || '').trim();
  const prev = (inp.dataset.prevValue || '').trim();
  if (nuevo === prev) return;
  if (!nuevo) {
    // Restaurar valor previo si el usuario intento dejarlo vacio
    inp.value = prev;
    return;
  }
  inp.classList.remove('saved-ok');
  inp.classList.add('saving');
  try {
    const r = await fetch(`/api/materia-prima/${encodeURIComponent(CAL_ID)}/tipo`, {
      method: 'PUT',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({tipo: nuevo}),
    });
    const ct = r.headers.get('content-type') || '';
    if (!ct.includes('application/json')) {
      throw new Error(`El servidor no reconoce este endpoint (HTTP ${r.status}). ` +
                      `Reinicia "Iniciar ERP Produccion.bat".`);
    }
    const d = await r.json();
    if (!r.ok) throw new Error(d.error || 'HTTP ' + r.status);
    inp.classList.remove('saving');
    inp.classList.add('saved-ok');
    setTimeout(() => inp.classList.remove('saved-ok'), 700);
    inp.dataset.prevValue = nuevo;
    // El nombre aparece en el H1 hero y el breadcrumb → refrescar
    cargar();
  } catch (err) {
    inp.classList.remove('saving');
    inp.value = prev;  // rollback visual
    await mostrarAlerta({titulo: 'Error guardando el nombre',
                         mensaje: err.message, tipo: 'danger'});
  }
}
const _inpTipo = document.getElementById('mpd-tipo-input');
if (_inpTipo) {
  _inpTipo.addEventListener('blur', guardarTipo);
  _inpTipo.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') { e.preventDefault(); _inpTipo.blur(); }
    if (e.key === 'Escape') { _inpTipo.value = _inpTipo.dataset.prevValue || ''; _inpTipo.blur(); }
  });
}

// ===== Click-to-edit del nombre de la calidad en el H1 hero =====
// El span #mpd-tipo es el nombre comercial de la calidad (ej. "australia",
// "pais economico"). Antes solo se podia editar desde el input "Nombre
// de la calidad" en la zona de configuracion abajo, pero no era obvio
// que ese input controlara el H1. Ahora un click en el span lo convierte
// en un input editable in-place. Enter o blur guarda, Escape cancela.
(function _wireTipoH1Editable() {
  const span = document.getElementById('mpd-tipo');
  if (!span) return;
  let editando = false;
  span.addEventListener('click', () => {
    if (editando) return;
    editando = true;
    const valorActual = span.textContent || '';
    const inp = document.createElement('input');
    inp.type = 'text';
    inp.className = 'mpd-tipo-editable-input';
    inp.value = valorActual;
    inp.maxLength = 100;
    // Reemplazar el span por el input en sitio (preservamos el bloque
    // del DOM para no romper el layout)
    span.style.display = 'none';
    span.parentNode.insertBefore(inp, span.nextSibling);
    inp.focus();
    inp.setSelectionRange(0, inp.value.length);  // seleccionar todo

    const cerrar = (cancelado) => {
      if (!editando) return;
      editando = false;
      // Eliminar el input y restaurar el span
      try { inp.parentNode.removeChild(inp); } catch (_) {}
      span.style.display = '';
    };
    inp.addEventListener('blur', async () => {
      const nuevo = (inp.value || '').trim();
      if (!nuevo || nuevo === valorActual) {
        cerrar(true); return;
      }
      // Reutilizamos el endpoint via guardarTipo: pre-cargamos el input
      // "Nombre de la calidad" y disparamos su guardado.
      const inpAbajo = document.getElementById('mpd-tipo-input');
      if (inpAbajo) {
        inpAbajo.value = nuevo;
        // El listener blur de inpAbajo llama a guardarTipo() que
        // refrescará la ficha y el H1 con el nuevo valor.
        await guardarTipo();
      }
      cerrar(false);
    });
    inp.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') { e.preventDefault(); inp.blur(); }
      if (e.key === 'Escape') {
        e.preventDefault();
        inp.value = valorActual;  // restaurar para que el blur no guarde
        cerrar(true);
      }
    });
  });
})();

// Filtro "Ocultar agotados": re-pinta la tabla de partidos al cambiar.
document.getElementById('mpd-ocultar-agotados').addEventListener('change', () => {
  if (_DATOS) pintarLotes(_DATOS.lotes || []);
});

function pintarLotes(lotes) {
  const ocultar = document.getElementById('mpd-ocultar-agotados')?.checked;
  const visibles = ocultar
    ? lotes.filter(l => l.estado_intrinseco !== 'agotado')
    : lotes;
  const nAgotadosOcultos = lotes.length - visibles.length;
  // Contador: lotes visibles + nota de agotados si los hay
  const cnt = document.getElementById('mpd-lotes-count');
  cnt.textContent = nAgotadosOcultos > 0
    ? `${visibles.length} · ${nAgotadosOcultos} consumido${nAgotadosOcultos === 1 ? '' : 's'} oculto${nAgotadosOcultos === 1 ? '' : 's'}`
    : `${visibles.length}`;
  const tb = document.getElementById('mpd-lotes-tbody');
  if (!visibles.length) {
    tb.innerHTML = `<tr><td colspan="14" class="mpd-empty">${
      lotes.length === 0 ? 'No hay partidos.' : 'Todos los partidos están consumidos (desactiva el filtro para verlos).'
    }</td></tr>`;
    return;
  }
  tb.innerHTML = visibles.map(l => {
    const claseFila = l.estado_intrinseco === 'agotado' ? 'lote-agotado'
                    : l.ubicacion === 'en-camino' ? 'lote-en-camino' : '';
    const pkey = provKey(l.proveedor);
    const fechaLlegada = l.fecha_estimada
      ? `<span style="color:#1e40af">ETA ${fmtFecha(l.fecha_estimada)}</span>`
      : fmtFecha(l.fecha_entrada);
    // Botones de accion segun el tipo de partido:
    // - fisico (en almacen): Editar + Mover (Mover solo si tiene kg)
    // - pedido_abierto (en camino): botón "✓ Marcar recibido" que cierra
    //   el pedido y lo materializa como partido fisico (el endpoint
    //   ya existe, lo usa el kanban). Mostramos tambien la ref del
    //   pedido para que el usuario sepa cual va a cerrar.
    const tieneAlgoQueMover = (Number(l.kg) || 0) > 0 || (Number(l.kg_proveedor) || 0) > 0;
    let acciones;
    if (l.tipo === 'fisico') {
      acciones = `
        <div style="display:flex; gap:0.3rem; justify-content:flex-end; flex-wrap:wrap">
          <button class="mpd-btn-row" data-mpd-editar
                  data-vid="${escapeHtml(l.variante_id)}"
                  data-partido="${escapeHtml(l.partido)}">Editar</button>
          ${tieneAlgoQueMover
            ? `<button class="mpd-btn-row" data-mpd-mover
                      data-vid="${escapeHtml(l.variante_id)}"
                      data-partido="${escapeHtml(l.partido)}"
                      title="Mover kg entre tu almacén y el del proveedor">⇄ Mover</button>`
            : ''}
        </div>`;
    } else {
      // pedido_abierto: boton "Marcar recibido" + ref pequeña debajo
      acciones = `
        <div style="display:flex; flex-direction:column; gap:0.25rem; align-items:flex-end">
          <button class="mpd-btn-row" data-mpd-recibido
                  data-vid="${escapeHtml(l.variante_id)}"
                  data-ref="${escapeHtml(l.ref_pedido || '')}"
                  data-kg="${l.kg != null ? l.kg : ''}"
                  title="Cerrar el pedido y registrar la mercancía como recibida"
                  style="color:#2f6b29; border-color:#c8e2bd">✓ Marcar recibido</button>
          <span style="color:#7a7a7a; font-size:0.7rem">${escapeHtml(l.ref_pedido || '')}</span>
        </div>`;
    }
    // Las 3 columnas (En proveedor + En almacén Rols + Cantidad actual)
    // forman un bloque visual ("Cantidad actual" = suma de las otras
    // dos). Las marcamos con la clase .mpd-bloque-cant para tintarlas
    // con fondo cream y, en el caso de la "actual", remarcarla como
    // total. Sin subtextos: si el usuario quiere el desglose lo ve en
    // las celdas de la izquierda.
    const kgRols = Number(l.kg) || 0;
    const kgProv = Number(l.kg_proveedor) || 0;
    const kgTotal = kgRols + kgProv;
    const enProveedorHtml = kgProv > 0
      ? `<span style="color:#2c5b8a; font-weight:600">${fmtKg(kgProv)}</span>`
      : `<span style="color:#bbb">—</span>`;
    const enRolsHtml = kgRols > 0
      ? `<strong>${fmtKg(kgRols)}</strong>`
      : `<span style="color:#bbb">—</span>`;
    const cantActualHtml = kgTotal > 0
      ? `<strong style="font-size:1.02em">${fmtKg(kgTotal)}</strong>`
      : `<span style="color:#bbb">—</span>`;
    return `
      <tr class="${claseFila}" data-tipo="${escapeHtml(l.tipo)}"
          data-vid="${escapeHtml(l.variante_id)}"
          data-partido="${escapeHtml(l.partido)}">
        <td><strong>${escapeHtml(l.partido)}</strong></td>
        <td><span class="prov-pill prov-${escapeHtml(pkey)}">${escapeHtml(l.proveedor || '—')}</span></td>
        <td class="num" style="color:#7a7a7a">${fmtKg(l.kg_inicial)}</td>
        <td class="num mpd-bloque-cant mpd-bloque-cant-inicio">${enProveedorHtml}</td>
        <td class="num mpd-bloque-cant mpd-bloque-cant-mas">${enRolsHtml}</td>
        <td class="num mpd-bloque-cant mpd-bloque-cant-igual mpd-bloque-cant-fin">${cantActualHtml}</td>
        <td><span class="chip chip-${l.estado_intrinseco}">${l.estado_intrinseco === 'agotado' ? 'consumido' : l.estado_intrinseco}</span></td>
        <td><span class="chip chip-${l.ubicacion}">${
          l.ubicacion === 'en-camino' ? 'en camino'
          : l.ubicacion === 'en-fabricacion' ? 'en fabricación'
          : 'en almacén'}</span></td>
        <td>${l.tipo === 'fisico'
              ? `<input class="mpd-obs mpd-estanteria" type="text" maxlength="40"
                        data-vid="${escapeHtml(l.variante_id)}"
                        data-partido="${escapeHtml(l.partido)}"
                        value="${escapeHtml(l.estanteria || '')}"
                        placeholder="—" style="width:90px" />`
              : escapeHtml(l.estanteria || '—')}</td>
        <td class="num">${l.coste_kg != null ? fmtEur(l.coste_kg) : '—'}</td>
        <td>${fmtFecha(l.fecha_compra)}</td>
        <td>${fechaLlegada}</td>
        <td>${l.fecha_agotado ? `<span style="color:#9b1c1c">${fmtFecha(l.fecha_agotado)}</span>` : '—'}</td>
        <td>
          ${l.tipo === 'fisico'
            ? `<input class="mpd-obs" type="text" maxlength="300"
                      data-vid="${escapeHtml(l.variante_id)}"
                      data-partido="${escapeHtml(l.partido)}"
                      value="${escapeHtml(l.observaciones || '')}"
                      placeholder="—" />`
            : escapeHtml(l.observaciones || '—')}
        </td>
        <td>${acciones}</td>
      </tr>`;
  }).join('');
}

function pintarPrecios(precios) {
  document.getElementById('mpd-precios-count').textContent = precios.length;
  pintarSpark(precios);
  const tb = document.getElementById('mpd-precios-tbody');
  if (!precios.length) {
    tb.innerHTML = '<tr><td colspan="5" class="mpd-empty">Aún no hay precios registrados.</td></tr>';
    return;
  }
  // Orden descendente por fecha para la vista
  const ord = [...precios].sort((a, b) => (b.fecha || '').localeCompare(a.fecha || ''));
  tb.innerHTML = ord.map(p => `
    <tr>
      <td>${fmtFecha(p.fecha)}</td>
      <td>${escapeHtml(p.partido || '—')}</td>
      <td><span class="prov-pill prov-${escapeHtml(provKey(p.proveedor))}">${escapeHtml(p.proveedor || '—')}</span></td>
      <td class="num"><strong>${fmtEur(p.eur_kg)}</strong></td>
      <td style="color:#7a7a7a; font-size:0.78rem">${escapeHtml(p.origen || '')}</td>
    </tr>
  `).join('');
}

function pintarSpark(precios) {
  const cont = document.getElementById('mpd-spark');
  if (!precios.length) { cont.innerHTML = ''; return; }
  const ord = [...precios].sort((a, b) => (a.fecha || '').localeCompare(b.fecha || ''));
  const valores = ord.map(p => Number(p.eur_kg)).filter(v => !isNaN(v));
  if (valores.length < 2) {
    cont.innerHTML = `<span>último ${fmtEur(valores[0] || 0)}</span>`;
    return;
  }
  const min = Math.min(...valores), max = Math.max(...valores), range = max - min || 1;
  const W = 120, H = 24;
  const pts = valores.map((v, i) => {
    const x = (i / (valores.length - 1)) * W;
    const y = H - ((v - min) / range) * H;
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(' ');
  const last = valores[valores.length - 1];
  const first = valores[0];
  const tendencia = last > first ? '↑' : last < first ? '↓' : '→';
  const colorTend = last > first ? '#9b1c1c' : last < first ? '#2f6b29' : '#7a7a7a';
  cont.innerHTML = `
    <svg width="${W}" height="${H}" viewBox="0 0 ${W} ${H}">
      <polyline class="mpd-spark-line" points="${pts}" />
      <circle class="mpd-spark-dot" cx="${W}" cy="${H - ((last - min) / range) * H}" r="2" />
    </svg>
    <span>${fmtEur(first)} → <strong>${fmtEur(last)}</strong>
      <span style="color:${colorTend}">${tendencia}</span>
    </span>`;
}

function pintarConsumos(consumos) {
  document.getElementById('mpd-consumos-count').textContent = consumos.length;
  const tb = document.getElementById('mpd-consumos-tbody');
  if (!consumos.length) {
    tb.innerHTML = '<tr><td colspan="7" class="mpd-empty">Sin movimientos registrados.</td></tr>';
    return;
  }
  // La columna ΔKG se pinta segun el signo:
  //   negativo → rojo (consumo o ajuste a la baja)
  //   positivo → verde (ajuste a la alta / mercancia encontrada)
  // El "+" se añade explicitamente cuando es positivo para que el signo
  // sea evidente de un vistazo (los negativos ya llevan "-" del propio
  // numero).
  tb.innerHTML = consumos.map(m => {
    const delta = Number(m.cantidad_kg) || 0;
    const esPositivo = delta > 0;
    const color = esPositivo ? '#2f6b29' : '#9b1c1c';
    const signo = esPositivo ? '+' : '';
    return `
    <tr>
      <td>${fmtFecha(m.fecha)}</td>
      <td>${escapeHtml(m.lote || '—')}</td>
      <td><span class="prov-pill prov-${escapeHtml(provKey(m.proveedor))}">${escapeHtml(m.proveedor || '—')}</span></td>
      <td class="num" style="color:${color}"><strong>${signo}${fmtNum(delta, 2)} kg</strong></td>
      <td class="num">${fmtKg(m.saldo_nuevo_kg)}</td>
      <td style="color:#4d4d4d; font-size:0.82rem">${escapeHtml(m.usuario || '—')}</td>
      <td style="color:#4d4d4d; font-size:0.82rem">${escapeHtml(m.nota || '—')}</td>
    </tr>`;
  }).join('');
}

// ----- Edición inline en la tabla de lotes -----
// Captura cambios en .mpd-obs (observaciones) y .mpd-estanteria. El campo
// se infiere de la clase para no duplicar handlers.
document.getElementById('mpd-lotes-tbody').addEventListener('change', async (e) => {
  const inp = e.target.closest('input.mpd-obs, input.mpd-estanteria');
  if (!inp) return;
  const tr = inp.closest('tr');
  const vid = inp.dataset.vid;
  const partido = inp.dataset.partido;
  const campo = inp.classList.contains('mpd-estanteria') ? 'estanteria' : 'observaciones';
  inp.classList.remove('saved-ok');
  inp.classList.add('saving');
  try {
    const body = {
      lote: partido,
      proveedor: tr.querySelector('.prov-pill')?.textContent.trim() || '',
    };
    body[campo] = inp.value;  // observaciones o estanteria
    const r = await fetch(
      `/api/materias-primas/lanas/${encodeURIComponent(CAL_ID)}/lotes/${encodeURIComponent(partido)}`,
      {method: 'PUT', headers: {'Content-Type': 'application/json'},
       body: JSON.stringify(body)}
    );
    const ct = r.headers.get('content-type') || '';
    if (!ct.includes('application/json')) {
      throw new Error(`El servidor no reconoce este endpoint (HTTP ${r.status}). ` +
                      `Reinicia "Iniciar ERP Produccion.bat".`);
    }
    const d = await r.json();
    if (!r.ok) throw new Error(d.error || 'HTTP ' + r.status);
    inp.classList.remove('saving');
    inp.classList.add('saved-ok');
    setTimeout(() => inp.classList.remove('saved-ok'), 700);
  } catch (err) {
    inp.classList.remove('saving');
    await mostrarAlerta({titulo: 'Error guardando ' + campo,
                         mensaje: err.message, tipo: 'danger'});
  }
});

// ----- Botón "Editar" en cada lote físico -----
// Localiza el partido en _DATOS y abre el modal compartido.
document.getElementById('mpd-lotes-tbody').addEventListener('click', (e) => {
  const btn = e.target.closest('[data-mpd-editar]');
  if (!btn) return;
  const vid = btn.dataset.vid;
  const partidoRef = btn.dataset.partido;
  if (!_DATOS) return;
  const variante = (_DATOS.variantes || []).find(v => v.id === vid);
  if (!variante) return;
  const partido = (variante.partidos || []).find(p => p.partido === partidoRef);
  if (!partido) return;
  abrirModalPartido({
    vid,
    calidad_id: _DATOS.calidad?.calidad_id || CAL_ID,
    proveedor:  variante.proveedor || '',
    partido,
    lanaLabel:  `${_DATOS.calidad?.titulo || ''} ${_DATOS.calidad?.tipo || ''}`.trim(),
    usuario:    currentUsuario(),
    onSaved:    () => cargar(),
    onDeleted:  () => cargar(),
  });
});

// ----- Botón "✓ Marcar recibido" en cada pedido EN CAMINO -----
// Cierra el pedido y lo materializa como partido físico en almacén.
// Abre el modal con opciones de destino (todo a Rols / parte queda
// en almacén proveedor). Mismo endpoint que usa el kanban.
document.getElementById('mpd-lotes-tbody').addEventListener('click', async (e) => {
  const btn = e.target.closest('[data-mpd-recibido]');
  if (!btn) return;
  const vid = btn.dataset.vid;
  const ref = btn.dataset.ref || '';
  const kgTotal = parseFloat(btn.dataset.kg) || 0;
  if (!ref) return;
  const r = await mostrarModalRecibido({ ref, kgTotal });
  if (!r.ok) return;
  btn.disabled = true;
  try {
    const resp = await fetch(`/api/compras/pedido/${encodeURIComponent(ref)}/recibido`, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        variante_id: vid,
        ...(r.kg_a_rols != null ? { kg_a_rols: r.kg_a_rols } : {}),
      }),
    });
    const ct = resp.headers.get('content-type') || '';
    if (!ct.includes('application/json')) {
      throw new Error(`El servidor no reconoce este endpoint (HTTP ${resp.status}). ` +
                      `Reinicia "Iniciar ERP Produccion.bat".`);
    }
    const d = await resp.json();
    if (!resp.ok) throw new Error(d.error || 'HTTP ' + resp.status);
    await cargar();
  } catch (err) {
    await mostrarAlerta({titulo: 'Error', mensaje: err.message, tipo: 'danger'});
    btn.disabled = false;
  }
});

// =====================================================================
// Botón "⇄ Mover" en cada lote físico → modal de traslado kg Rols ↔ Proveedor
// =====================================================================
//
// El modal permite elegir direccion (a-proveedor / a-rols) + cantidad,
// y POSTea al endpoint /trasladar. El total del partido no cambia;
// solo se reparte entre `kg` (almacen Rols) y `kg_proveedor`.
let _MOVER_CTX = null;   // {vid, partidoRef, kgRols, kgProv, proveedor, calidadId}

document.getElementById('mpd-lotes-tbody').addEventListener('click', (e) => {
  const btn = e.target.closest('[data-mpd-mover]');
  if (!btn) return;
  const vid = btn.dataset.vid;
  const partidoRef = btn.dataset.partido;
  if (!_DATOS) return;
  const variante = (_DATOS.variantes || []).find(v => v.id === vid);
  if (!variante) return;
  const partido = (variante.partidos || []).find(p => p.partido === partidoRef);
  if (!partido) return;
  const kgRols = Number(partido.kg) || 0;
  const kgProv = Number(partido.kg_proveedor) || 0;
  _MOVER_CTX = {
    vid, partidoRef,
    kgRols, kgProv,
    proveedor: variante.proveedor || '',
    calidadId: _DATOS.calidad?.calidad_id || CAL_ID,
    direccion: null,
  };
  // Rellena los valores
  const lana = `${_DATOS.calidad?.titulo || ''} ${_DATOS.calidad?.tipo || ''}`.trim();
  document.getElementById('mpd-mover-sub').textContent =
    `${lana} · Lote ${partidoRef} · ${variante.proveedor || ''}`.replace(/\s+/g, ' ').trim();
  document.getElementById('mpd-mover-kg-rols').textContent = fmtKg(kgRols);
  document.getElementById('mpd-mover-kg-prov').textContent = fmtKg(kgProv);
  document.getElementById('mpd-mover-kg').value = '';
  document.getElementById('mpd-mover-nota').value = '';
  document.getElementById('mpd-mover-error').classList.remove('show');
  document.getElementById('mpd-mover-error').textContent = '';
  document.getElementById('mpd-mover-confirmar').disabled = true;
  document.getElementById('mpd-mover-max').textContent = '';
  // Reset direccion
  document.querySelectorAll('.mpd-mover-dir-btn').forEach(b => {
    b.classList.remove('active');
    // Deshabilita la direccion que no tiene origen
    const dir = b.dataset.dir;
    const sinOrigen = (dir === 'a-proveedor' && kgRols <= 0) ||
                      (dir === 'a-rols' && kgProv <= 0);
    b.disabled = sinOrigen;
  });
  // Pre-selecciona la unica direccion posible si solo hay una
  const dirsValidas = [...document.querySelectorAll('.mpd-mover-dir-btn')]
                        .filter(b => !b.disabled);
  if (dirsValidas.length === 1) {
    dirsValidas[0].click();
  }
  document.getElementById('mpd-modal-mover').classList.add('open');
  setTimeout(() => document.getElementById('mpd-mover-kg').focus(), 100);
});

// Toggle de direccion
document.querySelectorAll('.mpd-mover-dir-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    if (btn.disabled || !_MOVER_CTX) return;
    document.querySelectorAll('.mpd-mover-dir-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    _MOVER_CTX.direccion = btn.dataset.dir;
    // Actualiza el "max" hint
    const max = btn.dataset.dir === 'a-proveedor' ? _MOVER_CTX.kgRols : _MOVER_CTX.kgProv;
    document.getElementById('mpd-mover-max').textContent =
      `(máximo ${fmtKg(max)})`;
    document.getElementById('mpd-mover-kg').max = max;
    // Valida el input actual con el nuevo max
    _validarMoverKg();
  });
});

// Habilita confirmar solo si direccion + kg validos
function _validarMoverKg() {
  const err = document.getElementById('mpd-mover-error');
  const btnConf = document.getElementById('mpd-mover-confirmar');
  if (!_MOVER_CTX || !_MOVER_CTX.direccion) {
    btnConf.disabled = true;
    return;
  }
  const val = parseFloat(document.getElementById('mpd-mover-kg').value);
  const max = _MOVER_CTX.direccion === 'a-proveedor'
              ? _MOVER_CTX.kgRols : _MOVER_CTX.kgProv;
  err.classList.remove('show');
  err.textContent = '';
  if (isNaN(val) || val <= 0) { btnConf.disabled = true; return; }
  if (val > max + 1e-6) {
    err.textContent = `Máximo disponible: ${fmtKg(max)}`;
    err.classList.add('show');
    btnConf.disabled = true;
    return;
  }
  btnConf.disabled = false;
}
document.getElementById('mpd-mover-kg').addEventListener('input', _validarMoverKg);

// Cerrar modal
function _cerrarModalMover() {
  document.getElementById('mpd-modal-mover').classList.remove('open');
  _MOVER_CTX = null;
}
document.getElementById('mpd-mover-cancelar').addEventListener('click', _cerrarModalMover);
document.getElementById('mpd-modal-mover').addEventListener('click', (e) => {
  if (e.target.id === 'mpd-modal-mover') _cerrarModalMover();
});

// Confirmar traslado
document.getElementById('mpd-mover-confirmar').addEventListener('click', async () => {
  if (!_MOVER_CTX || !_MOVER_CTX.direccion) return;
  const kg = parseFloat(document.getElementById('mpd-mover-kg').value);
  const nota = document.getElementById('mpd-mover-nota').value || '';
  const btn = document.getElementById('mpd-mover-confirmar');
  btn.disabled = true;
  try {
    const r = await fetch(
      `/api/materias-primas/lanas/${encodeURIComponent(_MOVER_CTX.calidadId)}/lotes/${encodeURIComponent(_MOVER_CTX.partidoRef)}/trasladar`,
      {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
          kg,
          direccion: _MOVER_CTX.direccion,
          proveedor: _MOVER_CTX.proveedor,
          usuario: currentUsuario(),
          nota,
        }),
      }
    );
    const ct = r.headers.get('content-type') || '';
    if (!ct.includes('application/json')) {
      throw new Error(`El servidor no reconoce este endpoint (HTTP ${r.status}). ` +
                      `Reinicia "Iniciar ERP Produccion.bat".`);
    }
    const d = await r.json();
    if (!r.ok) throw new Error(d.error || 'HTTP ' + r.status);
    _cerrarModalMover();
    await cargar();
  } catch (err) {
    const errBox = document.getElementById('mpd-mover-error');
    errBox.textContent = err.message;
    errBox.classList.add('show');
    btn.disabled = false;
  }
});

// =====================================================================
// Botón "+ Hacer pedido nuevo": abre el modal de pedido AQUI mismo
//
// Antes navegaba a /materias-primas#pedido:<CAL_ID> y abria el modal
// alli. Cambia de pestaña y pierde el contexto de la ficha — molesto
// si solo quieres pedir esta calidad concreta. Ahora el modal se
// construye sobre las variantes de la propia calidad (_DATOS.variantes)
// y POSTea contra el mismo endpoint /api/compras/generar-pedido.
// =====================================================================

// Abrir modal de pedido — toda la logica vive en
// static/modal-generar-pedido.js (compartido con el listado de
// Materias primas). Aqui solo construimos las variantes que aplican a
// ESTA calidad y le pasamos las callbacks.
function abrirModalPedidoLocal() {
  if (!_DATOS) return;
  const variantes = _DATOS.variantes || [];
  if (!variantes.length) {
    mostrarAlerta({
      titulo: 'Sin proveedores',
      mensaje: 'Esta calidad no tiene proveedores asignados. Añade uno con "+ Añadir" antes de generar un pedido.',
      tipo: 'warn',
    });
    return;
  }
  const nombre = `${_DATOS.calidad?.titulo || ''} ${_DATOS.calidad?.tipo || ''}`.trim()
              || _DATOS.calidad?.calidad_id || 'esta calidad';
  // El modal espera cada variante con {id, proveedor, nombre, ...}.
  // Lo aplanamos asi para que la "Calidad" mostrada en la tabla sea
  // legible (incluimos el proveedor entre parentesis como hint).
  const variantesParaModal = variantes.map(v => ({
    id:           v.id,
    proveedor:    v.proveedor || '(sin proveedor)',
    nombre:       `${nombre} (${v.proveedor || '?'})`,
    kg_a_pedir:   v.kg_a_pedir,
    // El modal prioriza la tarifa oficial mantenida en la ficha del
    // proveedor; sin este campo el €/kg sugerido caia al precio legacy.
    tarifa_actual_eur_kg: v.tarifa_actual_eur_kg,
    precio_2026:  v.precio_2026,
    precio_2025:  v.precio_2025,
  }));
  window.abrirModalPedidoGenerar({
    variantes: variantesParaModal,
    onCreated: async () => {
      // Refrescar la ficha: el contador "Pedidos en camino" y la
      // tabla deben mostrar el nuevo pedido sin recargar la pagina.
      await cargar();
    },
  });
}
document.getElementById('mpd-btn-pedido').addEventListener('click', abrirModalPedidoLocal);

// ----- Botón "+ Añadir proveedor" → modal selector -----
// Carga la lista de proveedores existentes (excluyendo los que ya
// suministran esta calidad) y los muestra como botones clicables. Si
// el que busca no existe, hay opcion de crear uno nuevo.
async function abrirSelectorProveedor() {
  // 1. Cargar proveedores disponibles
  let provs = [];
  try {
    const r = await fetch('/api/proveedores');
    const ct = r.headers.get('content-type') || '';
    if (!ct.includes('application/json')) {
      throw new Error(`El servidor no reconoce este endpoint (HTTP ${r.status}). ` +
                      `Reinicia "Iniciar ERP Produccion.bat".`);
    }
    const d = await r.json();
    if (!r.ok) throw new Error(d.error || 'HTTP ' + r.status);
    provs = d.proveedores || [];
  } catch (err) {
    await mostrarAlerta({titulo: 'Error', mensaje: err.message, tipo: 'danger'});
    return;
  }
  // 2. Excluir los que ya suministran esta calidad
  const ya = new Set(((_DATOS?.variantes) || []).map(v => (v.proveedor || '').toUpperCase()));
  const disponibles = provs.filter(p => {
    if (!p.activo) return false;
    const alias = (p.alias || p.nombre || '').toUpperCase();
    return alias && !ya.has(alias);
  });

  // 3. Inyectar modal ad-hoc al body (idempotente con id)
  let modal = document.getElementById('mp-sel-prov');
  if (!modal) {
    modal = document.createElement('div');
    modal.id = 'mp-sel-prov';
    modal.className = 'uim-backdrop';
    modal.innerHTML = `
      <div class="uim-modal" style="min-width:480px; max-width:600px">
        <h3>Añadir proveedor a esta calidad</h3>
        <p class="uim-sub">Selecciona uno de tus proveedores. Se crea una variante nueva (sin partidos todavía) vinculada a esta calidad.</p>
        <div id="mp-sel-prov-lista"
             style="display:flex; flex-wrap:wrap; gap:0.45rem; margin-bottom:1rem;
                    max-height:280px; overflow-y:auto;
                    border:1px solid var(--border, #E5DCD2); border-radius:8px;
                    padding:0.7rem; background:#FAF8F6"></div>
        <div class="uim-actions">
          <button type="button" class="uim-btn uim-btn-ghost"   id="mp-sel-prov-nuevo">+ Crear nuevo proveedor…</button>
          <span style="flex:1"></span>
          <button type="button" class="uim-btn uim-btn-ghost"   id="mp-sel-prov-cancelar">Cancelar</button>
        </div>
      </div>`;
    document.body.appendChild(modal);
    modal.addEventListener('click', (e) => {
      if (e.target === modal) modal.classList.remove('open');
    });
    document.getElementById('mp-sel-prov-cancelar').addEventListener('click', () => {
      modal.classList.remove('open');
    });
    document.getElementById('mp-sel-prov-nuevo').addEventListener('click', async () => {
      modal.classList.remove('open');
      const {ok, valor} = await mostrarPrompt({
        titulo: 'Crear proveedor nuevo',
        mensaje: 'Indica el nombre del proveedor. Después podrás rellenar el resto de datos en su ficha.',
        etiqueta: 'Nombre',
        placeholder: 'Ej. AQUAFIL',
        textoConfirmar: 'Crear y añadir',
      });
      if (!ok || !valor.trim()) return;
      // Crear proveedor y vincularlo a esta calidad
      const alias = valor.trim().toUpperCase();
      try {
        const r1 = await fetch('/api/proveedores', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({nombre: alias}),
        });
        const d1 = await r1.json();
        if (!r1.ok && !/ya existe/.test(d1.error || '')) {
          throw new Error(d1.error || 'HTTP ' + r1.status);
        }
        await vincularProveedorACalidad(alias);
      } catch (err) {
        await mostrarAlerta({titulo: 'Error', mensaje: err.message, tipo: 'danger'});
      }
    });
  }
  const lista = document.getElementById('mp-sel-prov-lista');
  if (!disponibles.length) {
    lista.innerHTML = '<div style="color:#7a7a7a; font-size:0.86rem; padding:0.4rem">Todos los proveedores activos ya suministran esta calidad. Crea uno nuevo con el botón de abajo.</div>';
  } else {
    lista.innerHTML = disponibles.map(p => {
      const alias = p.alias || p.nombre || '';
      return `<button type="button" class="mp-sel-prov-item"
                      data-alias="${escapeHtml(alias)}"
                      style="background:#fff; border:1px solid var(--border); border-radius:999px;
                             padding:0.45rem 0.95rem; font-size:0.86rem; cursor:pointer;
                             font-family:inherit; transition:background 0.12s, border-color 0.12s">
                <strong>${escapeHtml(alias)}</strong>
                ${p.nombre && p.nombre.toUpperCase() !== alias.toUpperCase()
                  ? `<span style="color:#7a7a7a; font-weight:400; margin-left:0.4rem">${escapeHtml(p.nombre)}</span>`
                  : ''}
              </button>`;
    }).join('');
    // Hover dinámico
    lista.querySelectorAll('.mp-sel-prov-item').forEach(btn => {
      btn.addEventListener('mouseenter', () => {
        btn.style.background = '#fbf8f3';
        btn.style.borderColor = 'var(--accent)';
      });
      btn.addEventListener('mouseleave', () => {
        btn.style.background = '#fff';
        btn.style.borderColor = 'var(--border)';
      });
      btn.addEventListener('click', async () => {
        modal.classList.remove('open');
        await vincularProveedorACalidad(btn.dataset.alias);
      });
    });
  }
  modal.classList.add('open');
}

async function vincularProveedorACalidad(alias) {
  const btn = document.getElementById('mpd-btn-add-prov');
  btn.disabled = true;
  btn.textContent = 'Añadiendo…';
  try {
    const r = await fetch(`/api/materia-prima/${encodeURIComponent(CAL_ID)}/proveedor`, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({proveedor: alias}),
    });
    const ct = r.headers.get('content-type') || '';
    if (!ct.includes('application/json')) {
      throw new Error(`El servidor no reconoce este endpoint (HTTP ${r.status}). ` +
                      `Reinicia "Iniciar ERP Produccion.bat".`);
    }
    const d = await r.json();
    if (!r.ok) throw new Error(d.error || 'HTTP ' + r.status);
    await cargar();
  } catch (err) {
    await mostrarAlerta({titulo: 'No se pudo añadir el proveedor', mensaje: err.message, tipo: 'danger'});
  } finally {
    btn.disabled = false;
    btn.textContent = '+ Añadir';
  }
}

document.getElementById('mpd-btn-add-prov').addEventListener('click', abrirSelectorProveedor);

// ===== Quitar proveedor de la calidad =====
// Cada chip de proveedor lleva un boton × que dispara este handler.
// Delegacion sobre el contenedor donde se pintan los chips, asi
// sobrevive al repintado tras cargar().
document.getElementById('mpd-kpi-provs').addEventListener('click', async (e) => {
  const btn = e.target.closest('.mpd-prov-quitar');
  if (!btn) return;
  const prov = btn.dataset.prov || '';
  if (!prov) return;
  // Confirmacion suave. La salvaguarda real (kg vivo, pedidos abiertos)
  // esta en el backend, no perdemos nada por avisar dos veces.
  const {ok} = await (window.mostrarConfirmacion || (async (o) => ({ok: confirm(o.mensaje)})))({
    titulo: `Quitar ${prov} de la calidad`,
    mensaje: `Se eliminara la variante de ${prov} de esta calidad. ` +
             `Si tiene partidos con stock o pedidos abiertos, el sistema lo ` +
             `impedira y tendras que vaciarlos o anular los pedidos antes.`,
    textoConfirmar: 'Quitar proveedor',
    tipo: 'danger',
  });
  if (!ok) return;
  await intentarQuitarProveedor(prov, false);
});

async function intentarQuitarProveedor(prov, forzar) {
  try {
    const r = await fetch(
      `/api/materia-prima/${encodeURIComponent(CAL_ID)}/proveedor/${encodeURIComponent(prov)}` +
        (forzar ? '?forzar=1' : ''),
      { method: 'DELETE' }
    );
    const ct = r.headers.get('content-type') || '';
    if (!ct.includes('application/json')) {
      throw new Error(`El servidor no reconoce este endpoint (HTTP ${r.status}). ` +
                      `Reinicia "Iniciar ERP Produccion.bat".`);
    }
    const d = await r.json();
    if (!r.ok) {
      // Si la salvaguarda salto por kg vivo / pedidos abiertos, ofrecer
      // forzado explicito. Para "es la unica variante" no permitimos
      // forzar (el backend tambien lo bloquea).
      const esBloqueoForzable = !forzar && /kg|pedido/i.test(d.error || '');
      if (esBloqueoForzable) {
        const {ok: forzarOk} = await (window.mostrarConfirmacion || (async (o) => ({ok: confirm(o.mensaje)})))({
          titulo: 'Forzar la eliminación',
          mensaje: `${d.error}\n\nSi continuas, la variante se eliminara de todos modos ` +
                   `y se perdera la referencia a esos kg / pedidos. ¿Seguro?`,
          textoConfirmar: 'Forzar eliminación',
          tipo: 'danger',
        });
        if (forzarOk) await intentarQuitarProveedor(prov, true);
        return;
      }
      throw new Error(d.error || 'HTTP ' + r.status);
    }
    // OK: recargar la ficha para que desaparezca el chip
    await cargar();
  } catch (err) {
    await mostrarAlerta({
      titulo: 'No se pudo quitar el proveedor',
      mensaje: err.message,
      tipo: 'danger',
    });
  }
}

// ============ Borrar materia prima entera ============
// Borra la calidad y todas sus variantes. El backend bloquea si hay
// kg vivos o pedidos abiertos; en ese caso ofrecemos forzar
// explicitamente (registra movimientos tipo 'borrado' para auditoria).
document.getElementById('mpd-borrar-calidad').addEventListener('click', async () => {
  const nombreCalidad = (document.getElementById('mpd-hero-subtitle')?.textContent || CAL_ID).trim();
  const {ok} = await (window.mostrarConfirmacion || (async (o) => ({ok: confirm(o.mensaje)})))({
    titulo: 'Borrar materia prima',
    mensaje: `Se eliminará la calidad "${nombreCalidad}" con TODAS sus ` +
             `variantes (proveedores) y partidos. Esto no se puede deshacer.\n\n` +
             `Si la calidad tiene kg vivos o pedidos abiertos, el sistema ` +
             `bloqueará el borrado y podrás decidir si forzarlo.`,
    textoConfirmar: 'Borrar materia prima',
    tipo: 'danger',
  });
  if (!ok) return;
  await intentarBorrarCalidad(false);
});

async function intentarBorrarCalidad(forzar) {
  try {
    const r = await fetch(
      `/api/materia-prima/${encodeURIComponent(CAL_ID)}` + (forzar ? '?forzar=1' : ''),
      { method: 'DELETE' }
    );
    const ct = r.headers.get('content-type') || '';
    if (!ct.includes('application/json')) {
      throw new Error(`El servidor no reconoce este endpoint (HTTP ${r.status}). ` +
                      `Reinicia "Iniciar ERP Produccion.bat".`);
    }
    const d = await r.json();
    if (!r.ok) {
      const esBloqueoForzable = !forzar && /kg|pedido/i.test(d.error || '');
      if (esBloqueoForzable) {
        const {ok: forzarOk} = await (window.mostrarConfirmacion || (async (o) => ({ok: confirm(o.mensaje)})))({
          titulo: 'Forzar el borrado',
          mensaje: `${d.error}\n\nSi continúas, la materia prima se eliminará ` +
                   `de todos modos y se perderá la referencia a esos kg / pedidos. ` +
                   `Se registrarán movimientos de auditoría. ¿Seguro?`,
          textoConfirmar: 'Forzar borrado',
          tipo: 'danger',
        });
        if (forzarOk) await intentarBorrarCalidad(true);
        return;
      }
      throw new Error(d.error || 'HTTP ' + r.status);
    }
    // OK: navegamos al listado de materias primas
    window.location.href = '/materias-primas';
  } catch (err) {
    await mostrarAlerta({
      titulo: 'No se pudo borrar la materia prima',
      mensaje: err.message,
      tipo: 'danger',
    });
  }
}

// Bootstrap: primero el catalogo (para que los selects esten poblados y
// los labels disponibles) y luego cargar los datos de la calidad.
(async () => {
  await cargarCatalogo();
  await cargar();
})();
