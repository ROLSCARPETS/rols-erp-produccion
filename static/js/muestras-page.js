// ============================================================
// Muestras fabricadas — listado: En curso · Histórico · Análisis
// + modal de alta. Requiere muestras-common.js (window.MS).
// ============================================================
(function () {
  'use strict';
  const { esc, fmtFecha, hoyISO, fmtNum, numeroHtml, estadoPill, prioPill, clienteHtml, colorearPrio, api,
          ESTADOS, ESTADOS_LABEL, ESTADOS_FLUJO, llenarSelect, llenarSelectPersonas, gestionarOtro } = window.MS;
  const $ = id => document.getElementById(id);
  const debounce = (fn, ms) => { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; };

  const ST = {
    tab: 'en-curso',
    catalogos: null,
    resumen: null,
    ec: { rows: [], estados: new Set(), sort: { campo: null, dir: 1 }, cargado: false },
    hi: { rows: [], total: 0, limite: 0, cargado: false },
    an: { cargado: false },
  };

  // ------------------------------------------------------------
  // Tabs
  // ------------------------------------------------------------
  function activarTab(tab, sinHash) {
    ST.tab = tab;
    document.querySelectorAll('.tab-btn').forEach(b => b.classList.toggle('active', b.dataset.tab === tab));
    document.querySelectorAll('[data-tab-panel]').forEach(p => { p.style.display = p.dataset.tabPanel === tab ? '' : 'none'; });
    if (!sinHash) history.replaceState(null, '', tab === 'en-curso' ? location.pathname : '#' + tab);
    if (tab === 'historico' && !ST.hi.cargado) cargarHistorico();
    if (tab === 'analisis' && !ST.an.cargado) cargarAnalisis();
  }
  document.querySelectorAll('.tab-btn').forEach(b => b.addEventListener('click', () => activarTab(b.dataset.tab)));

  // ------------------------------------------------------------
  // Catálogos (selects de filtros y del alta)
  // ------------------------------------------------------------
  function pintarCatalogos() {
    const c = ST.catalogos;
    if (!c) return;
    llenarSelect($('ec-telar'), c.telares, { vacio: 'Todos los telares' });
    llenarSelect($('hi-telar'), c.telares, { vacio: 'Todos los telares' });
    // Filtro "Encargada por": se escribe o se elige (usuarios de One primero,
    // después los nombres antiguos del libro).
    const activas = (c.personas_activas || []).map(p => p.nombre);
    const legacy = (c.personas_legacy || []).filter(n => !activas.includes(n));
    $('ms-personas-dl').innerHTML = activas.map(n => `<option value="${esc(n)}"></option>`).join('')
      + legacy.map(n => `<option value="${esc(n)}">antiguo</option>`).join('');
    const dl = $('ms-clientes');
    dl.innerHTML = (c.clientes || []).map(x => `<option value="${esc(x)}"></option>`).join('');
  }

  function pintarAnios() {
    const anios = (ST.resumen && ST.resumen.anios) || [];
    const opts = anios.map(a => `<option value="${a}">${a}</option>`).join('');
    const hi = $('hi-anio'), an = $('an-anio');
    const vh = hi.value, va = an.value;
    hi.innerHTML = `<option value="">Todos los años</option>` + opts;
    an.innerHTML = `<option value="">Todos los años</option>` + opts;
    hi.value = vh; an.value = va;
  }

  // ------------------------------------------------------------
  // KPIs + chips de estado (cabecera)
  // ------------------------------------------------------------
  function pintarKpis() {
    const r = ST.resumen;
    if (!r) return;
    $('kpi-curso').textContent = fmtNum(r.en_curso);
    const arch = r.archivadas_sin_terminar || 0;
    $('kpi-curso-sub').textContent = arch ? `+ ${fmtNum(arch)} archivadas sin terminar` : 'muestras en fabricación';
    $('kpi-alta').textContent = fmtNum(r.prioridad_alta);
    $('kpi-anio-lbl').textContent = r.anio;
    $('kpi-anio-lbl2').textContent = r.anio;
    $('kpi-solic').textContent = fmtNum(r.solicitadas_anio);
    $('kpi-solic-sub').textContent = `≈ ${String(r.media_mes_anio).replace('.', ',')} al mes`;
    $('kpi-term').textContent = fmtNum(r.terminadas_anio);
    $('kpi-term-sub').textContent = 'entregadas este año';
    $('tc-en-curso').textContent = fmtNum(r.en_curso);
    $('tc-historico').textContent = fmtNum(Math.max(0, (r.total || 0) - (r.en_curso || 0)));
    $('ms-n-siguiente').textContent = `M-${r.siguiente_numero}`;
  }

  function pintarChipsEstado() {
    const r = ST.resumen;
    if (!r) return;
    const cont = $('ec-estados');
    const slugs = ESTADOS_FLUJO.filter(s => s !== 'terminada');
    const activos = ST.ec.estados;
    let html = `<button type="button" class="ms-chip ${activos.size ? '' : 'activo'}" data-estado="">Todos <span class="n">${fmtNum(r.en_curso)}</span></button>`;
    slugs.forEach(s => {
      const n = (r.por_estado && r.por_estado[s]) || 0;
      html += `<button type="button" class="ms-chip ${activos.has(s) ? 'activo' : ''}" data-estado="${s}" ${n ? '' : 'style="opacity:0.55"'}>` +
              `<span class="dot ms-dot-${s}"></span>${esc(ESTADOS_LABEL[s])} <span class="n">${fmtNum(n)}</span></button>`;
    });
    cont.innerHTML = html;
  }
  $('ec-estados').addEventListener('click', (e) => {
    const b = e.target.closest('.ms-chip');
    if (!b) return;
    const s = b.dataset.estado;
    if (!s) ST.ec.estados.clear();
    else if (ST.ec.estados.has(s)) ST.ec.estados.delete(s);
    else ST.ec.estados.add(s);
    pintarChipsEstado();
    pintarEnCurso();
  });

  // ------------------------------------------------------------
  // EN CURSO
  // ------------------------------------------------------------
  function filtrosEnCurso() {
    const p = new URLSearchParams({ vista: 'en-curso' });
    const q = $('ec-q').value.trim();
    if (q) p.set('q', q);
    if ($('ec-telar').value) p.set('telar', $('ec-telar').value);
    if ($('ec-persona').value) p.set('persona', $('ec-persona').value);
    if ($('ec-prio').value) p.set('prioridad', $('ec-prio').value);
    if ($('ec-tipo').value) p.set('tipo', $('ec-tipo').value);
    return p;
  }

  async function cargarEnCurso(conCatalogos) {
    const p = filtrosEnCurso();
    if (conCatalogos) p.set('con_catalogos', '1');
    let data;
    try {
      data = await api('/api/muestras?' + p.toString());
    } catch (e) {
      $('ec-tbody').innerHTML = `<tr><td colspan="11" class="ms-vacio">No se pudo cargar: ${esc(e.message)}</td></tr>`;
      return;
    }
    ST.ec.rows = data.muestras || [];
    ST.ec.cargado = true;
    ST.resumen = data.resumen;
    if (data.catalogos) { ST.catalogos = data.catalogos; pintarCatalogos(); }
    pintarAnios();
    pintarKpis();
    pintarChipsEstado();
    pintarEnCurso();
  }

  function opcionesEstado(actual) {
    return ESTADOS.filter(e => e[0] !== 'sin_seguimiento' || e[0] === actual)
      .map(e => `<option value="${e[0]}" ${e[0] === actual ? 'selected' : ''}>${esc(e[1])}</option>`).join('');
  }

  function ordenar(rows) {
    const { campo, dir } = ST.ec.sort;
    if (!campo) return rows;
    const val = m => {
      if (campo === 'numero') return [(m.numero == null ? 1e9 : m.numero), m.sufijo || ''];
      if (campo === 'prioridad') return [m.prioridad == null ? 9 : m.prioridad];
      if (campo === 'dias') return [m.dias == null ? -1 : m.dias];
      return [String(m[campo] || '').toLowerCase()];
    };
    return rows.slice().sort((a, b) => {
      const va = val(a), vb = val(b);
      for (let i = 0; i < va.length; i++) {
        if (va[i] < vb[i]) return -1 * dir;
        if (va[i] > vb[i]) return 1 * dir;
      }
      return 0;
    });
  }

  function filaEnCurso(m) {
    const ult = m.ultimo_apunte;
    const sel = `<select class="ms-sel-estado ms-estado-${esc(m.estado)}" data-id="${esc(m.id)}" data-estado="${esc(m.estado)}" title="Cambiar el estado">${opcionesEstado(m.estado)}</select>`;
    const mudo = '<span class="ms-mudo">—</span>';
    return `<tr class="ms-fila" data-id="${esc(m.id)}">
      <td>${numeroHtml(m)}</td>
      <td class="ms-fecha">${fmtFecha(m.fecha_solicitud, false) || mudo}</td>
      <td class="ms-cliente">${clienteHtml(m)}</td>
      <td><div class="ms-desc" title="${esc(m.descripcion)}">${esc(m.descripcion) || mudo}</div></td>
      <td>${esc(m.encargada_por) || mudo}</td>
      <td>${prioPill(m.prioridad)}</td>
      <td>${esc(m.telar) || mudo}</td>
      <td>${sel}</td>
      <td class="num"><span class="ms-dias ${(m.dias || 0) > 120 ? 'tarde' : ''}" title="Días desde la solicitud">${m.dias != null ? fmtNum(m.dias) : '—'}</span></td>
      <td>${ult ? `<div class="ms-apunte-mini" title="${esc(ult.texto)}"><b>${esc(fmtFecha(ult.fecha, false) || 's/f')}</b>${esc(ult.texto)}</div>` : '<span class="ms-mudo">sin apuntes</span>'}</td>
      <td><span class="ms-ir" title="Abrir la ficha">→</span></td>
    </tr>`;
  }

  function pintarEnCurso() {
    let rows = ST.ec.rows;
    if (ST.ec.estados.size) rows = rows.filter(m => ST.ec.estados.has(m.estado));
    rows = ordenar(rows);
    $('ec-count').textContent = fmtNum(rows.length);
    const tb = $('ec-tbody');
    if (!rows.length) {
      const hayFiltro = ST.ec.estados.size || filtrosEnCurso().toString() !== 'vista=en-curso';
      tb.innerHTML = `<tr><td colspan="11" class="ms-vacio">${hayFiltro ? 'Ninguna muestra en curso coincide con el filtro.' : 'No hay muestras en curso. Crea una con «Nueva muestra».'}</td></tr>`;
    } else {
      tb.innerHTML = rows.map(filaEnCurso).join('');
    }
    const total = ST.ec.rows.length;
    $('ec-counter').textContent = rows.length !== total ? `${fmtNum(rows.length)} de ${fmtNum(total)}` : '';
    const hayFiltros = ST.ec.estados.size || filtrosEnCurso().toString() !== 'vista=en-curso';
    $('ec-limpiar').hidden = !hayFiltros;
    document.querySelectorAll('#ec-tabla th.sortable').forEach(th => {
      const on = th.dataset.sort === ST.ec.sort.campo;
      th.classList.toggle('sorted', on);
      th.querySelector('.arrow').textContent = on && ST.ec.sort.dir < 0 ? '▼' : '▲';
    });
  }

  // Filtros
  const recargarEC = debounce(() => cargarEnCurso(false), 250);
  $('ec-q').addEventListener('input', recargarEC);
  $('ec-persona').addEventListener('input', recargarEC);
  ['ec-telar', 'ec-prio', 'ec-tipo'].forEach(id => $(id).addEventListener('change', () => cargarEnCurso(false)));
  $('ec-limpiar').addEventListener('click', () => {
    $('ec-q').value = ''; $('ec-telar').value = ''; $('ec-persona').value = ''; $('ec-prio').value = ''; $('ec-tipo').value = '';
    ST.ec.estados.clear();
    cargarEnCurso(false);
  });
  // Orden por cabecera: asc → desc → natural
  document.querySelectorAll('#ec-tabla th.sortable').forEach(th => th.addEventListener('click', () => {
    const campo = th.dataset.sort;
    const s = ST.ec.sort;
    if (s.campo !== campo) { s.campo = campo; s.dir = 1; }
    else if (s.dir === 1) s.dir = -1;
    else { s.campo = null; s.dir = 1; }
    pintarEnCurso();
  }));

  // Click en fila → ficha (salvo sobre el select de estado)
  $('ec-tbody').addEventListener('click', (e) => {
    if (e.target.closest('select')) return;
    const tr = e.target.closest('tr.ms-fila');
    if (tr) location.href = '/muestras-fabricadas/' + encodeURIComponent(tr.dataset.id);
  });

  // Cambio de estado inline
  $('ec-tbody').addEventListener('change', async (e) => {
    const sel = e.target.closest('select.ms-sel-estado');
    if (!sel) return;
    const id = sel.dataset.id, anterior = sel.dataset.estado, nuevo = sel.value;
    if (nuevo === anterior) return;
    let nota = '';
    if (nuevo === 'terminada') {
      const r = await window.mostrarConfirmacion({
        titulo: `Marcar M-${id} como terminada`,
        mensaje: 'Se fijará hoy como fecha de muestra lista y dejará de aparecer en «En curso» (queda en el histórico).',
        textoConfirmar: 'Sí, terminada', conMotivo: true, placeholderMotivo: 'Apunte final para el diario (opcional)',
      });
      if (!r.ok) { sel.value = anterior; return; }
      nota = r.motivo || '';
    } else if (nuevo === 'cancelada') {
      const r = await window.mostrarConfirmacion({
        titulo: `Cancelar la muestra M-${id}`,
        mensaje: 'La muestra pasa al histórico como cancelada. Puedes indicar el motivo: se guarda en el diario.',
        textoConfirmar: 'Cancelar muestra', tipo: 'danger', conMotivo: true, placeholderMotivo: 'Motivo (opcional)',
      });
      if (!r.ok) { sel.value = anterior; return; }
      nota = r.motivo || '';
    }
    sel.classList.add('saving');
    try {
      await api(`/api/muestras/${encodeURIComponent(id)}/estado`, { method: 'POST', body: { estado: nuevo, nota } });
      await cargarEnCurso(false);
    } catch (err) {
      sel.value = anterior;
      sel.classList.remove('saving');
      await window.mostrarAlerta({ titulo: 'No se pudo cambiar el estado', mensaje: err.message, tipo: 'danger' });
    }
  });

  // ------------------------------------------------------------
  // HISTÓRICO
  // ------------------------------------------------------------
  function filtrosHistorico() {
    const p = new URLSearchParams({ vista: 'historico', limite: '400' });
    const q = $('hi-q').value.trim();
    if (q) p.set('q', q);
    if ($('hi-anio').value) p.set('anio', $('hi-anio').value);
    const est = $('hi-estado').value;
    if (est === '__archivadas') p.set('estado', 'activas_archivadas');
    else if (est) p.set('estado', est);
    if ($('hi-telar').value) p.set('telar', $('hi-telar').value);
    if ($('hi-persona').value) p.set('persona', $('hi-persona').value);
    if ($('hi-tipo').value) p.set('tipo', $('hi-tipo').value);
    return p;
  }

  async function cargarHistorico() {
    const tb = $('hi-tbody');
    let data;
    try {
      data = await api('/api/muestras?' + filtrosHistorico().toString());
    } catch (e) {
      tb.innerHTML = `<tr><td colspan="10" class="ms-vacio">No se pudo cargar: ${esc(e.message)}</td></tr>`;
      return;
    }
    ST.hi.rows = data.muestras || [];
    ST.hi.total = data.total || 0;
    ST.hi.limite = data.limite || 0;
    ST.hi.cargado = true;
    if (data.resumen) { ST.resumen = data.resumen; pintarAnios(); pintarKpis(); }
    pintarHistorico();
  }

  function filaHistorico(m) {
    const mudo = '<span class="ms-mudo">—</span>';
    const terminal = ['terminada', 'cancelada', 'sin_seguimiento'].includes(m.estado);
    const arch = (m.archivada && !terminal) ? '<span class="ms-tag-archivada" title="Archivada sin marcar como terminada (en el Excel estaba en la hoja de terminadas)">archivada</span>' : '';
    return `<tr class="ms-fila" data-id="${esc(m.id)}">
      <td>${numeroHtml(m)}</td>
      <td class="ms-fecha">${fmtFecha(m.fecha_solicitud, false) || mudo}</td>
      <td class="ms-cliente">${clienteHtml(m)}</td>
      <td><div class="ms-desc" title="${esc(m.descripcion)}">${esc(m.descripcion) || mudo}</div></td>
      <td>${esc(m.encargada_por) || mudo}</td>
      <td>${esc(m.telar) || mudo}</td>
      <td>${estadoPill(m.estado, m.estado_label)}${arch}</td>
      <td class="ms-fecha">${fmtFecha(m.fecha_lista, false) || mudo}</td>
      <td class="num">${(m.dias_tipo === 'plazo' && m.dias != null) ? `<span class="ms-dias" title="Días de la solicitud a la muestra lista">${fmtNum(m.dias)}</span>` : mudo}</td>
      <td><div class="ms-desc" title="${esc(m.resultado)}">${esc(m.resultado) || mudo}</div></td>
    </tr>`;
  }

  function pintarHistorico() {
    const rows = ST.hi.rows;
    $('hi-count').textContent = fmtNum(ST.hi.total);
    const tb = $('hi-tbody');
    tb.innerHTML = rows.length ? rows.map(filaHistorico).join('')
      : `<tr><td colspan="10" class="ms-vacio">Ninguna muestra coincide con el filtro.</td></tr>`;
    const hayFiltros = filtrosHistorico().toString() !== 'vista=historico&limite=400';
    $('hi-limpiar').hidden = !hayFiltros;
    $('hi-counter').textContent = ST.hi.total > rows.length
      ? `mostrando las ${fmtNum(rows.length)} más recientes de ${fmtNum(ST.hi.total)} · afina el filtro o busca para ver el resto`
      : '';
  }
  const recargarHI = debounce(cargarHistorico, 250);
  $('hi-q').addEventListener('input', recargarHI);
  $('hi-persona').addEventListener('input', recargarHI);
  ['hi-anio', 'hi-estado', 'hi-telar', 'hi-tipo'].forEach(id => $(id).addEventListener('change', cargarHistorico));
  $('hi-limpiar').addEventListener('click', () => {
    ['hi-q', 'hi-anio', 'hi-estado', 'hi-telar', 'hi-persona', 'hi-tipo'].forEach(id => { $(id).value = ''; });
    cargarHistorico();
  });
  $('hi-tbody').addEventListener('click', (e) => {
    const tr = e.target.closest('tr.ms-fila');
    if (tr) location.href = '/muestras-fabricadas/' + encodeURIComponent(tr.dataset.id);
  });

  // ------------------------------------------------------------
  // ANÁLISIS
  // ------------------------------------------------------------
  const MESES = ['Ene', 'Feb', 'Mar', 'Abr', 'May', 'Jun', 'Jul', 'Ago', 'Sep', 'Oct', 'Nov', 'Dic'];

  async function cargarAnalisis() {
    let d;
    try {
      const anio = $('an-anio').value;
      d = await api('/api/muestras/analisis' + (anio ? `?anio=${encodeURIComponent(anio)}` : ''));
    } catch (e) {
      $('an-anios').innerHTML = `<tr><td colspan="6" class="ms-vacio">No se pudo cargar: ${esc(e.message)}</td></tr>`;
      return;
    }
    ST.an.cargado = true;
    // Por año
    $('an-anios').innerHTML = (d.por_anio || []).map(f => `<tr>
        <td><b>${f.anio}</b></td>
        <td class="num">${fmtNum(f.solicitadas)}</td>
        <td class="num">${String(f.media_mes).replace('.', ',')}</td>
        <td class="num">${fmtNum(f.terminadas)}</td>
        <td class="num">${f.canceladas ? fmtNum(f.canceladas) : '<span class="ms-mudo">—</span>'}</td>
        <td class="num">${f.plazo_medio_dias != null ? `${fmtNum(f.plazo_medio_dias)} días <span class="ms-mudo" title="muestras con las dos fechas">(${fmtNum(f.n_plazos)})</span>` : '<span class="ms-mudo">—</span>'}</td>
      </tr>`).join('') || '<tr><td colspan="6" class="ms-vacio">Sin datos</td></tr>';
    // Por mes (año actual vs anterior)
    const anios = Object.keys(d.por_mes || {}).map(Number).sort((a, b) => b - a);
    const actual = anios[0], prev = anios[1];
    const va = (d.por_mes && d.por_mes[String(actual)]) || [], vp = (d.por_mes && d.por_mes[String(prev)]) || [];
    const max = Math.max(1, ...va, ...vp);
    $('an-meses').innerHTML = MESES.map((m, i) => `<div class="ms-mes">
        <div class="cols">
          <div class="col prev" style="height:${Math.round(((vp[i] || 0) / max) * 90)}px" title="${prev}: ${vp[i] || 0}"></div>
          <div class="col" style="height:${Math.round(((va[i] || 0) / max) * 90)}px" title="${actual}: ${va[i] || 0}"></div>
        </div><div class="lbl">${m}</div></div>`).join('');
    $('an-leg-actual').textContent = `${actual} (${fmtNum(va.reduce((s, x) => s + x, 0))})`;
    $('an-leg-prev').textContent = `${prev} (${fmtNum(vp.reduce((s, x) => s + x, 0))})`;
    $('an-meses-hint').textContent = 'solicitudes de cada mes: año actual frente al anterior';
    // Reparto
    const barras = (lista, clave) => {
      const mx = Math.max(1, ...lista.map(x => x.n));
      return lista.slice(0, 14).map(x => `<div class="ms-bar-row"><span class="lbl" title="${esc(x[clave])}">${esc(x[clave])}</span><div class="ms-bar"><i style="width:${Math.round((x.n / mx) * 100)}%"></i></div><span class="n">${fmtNum(x.n)}</span></div>`).join('')
        || '<span class="ms-mudo">Sin datos</span>';
    };
    $('an-telar').innerHTML = barras(d.por_telar || [], 'telar');
    $('an-persona').innerHTML = barras(d.por_persona || [], 'persona');
  }
  $('an-anio').addEventListener('change', cargarAnalisis);

  // ------------------------------------------------------------
  // NUEVA MUESTRA (modal)
  // ------------------------------------------------------------
  const modal = $('ms-modal-nueva');
  let tipoNuevo = 'cliente';
  function ponerTipoNuevo(tipo) {
    tipoNuevo = tipo === 'interna' ? 'interna' : 'cliente';
    modal.querySelectorAll('#ms-n-tipo-seg .ms-seg-btn').forEach(b => b.classList.toggle('active', b.dataset.tipo === tipoNuevo));
    const interna = tipoNuevo === 'interna';
    $('ms-n-cliente-lbl').textContent = interna ? 'Para quién / proyecto (opcional)' : 'Cliente';
    $('ms-n-cliente').placeholder = interna ? 'Ej. Marta · colección 2027 · prueba de calidad' : 'Nombre del cliente';
  }
  $('ms-n-tipo-seg').addEventListener('click', (e) => {
    const b = e.target.closest('.ms-seg-btn');
    if (b) ponerTipoNuevo(b.dataset.tipo);
  });
  function abrirNueva() {
    ponerTipoNuevo('cliente');
    const c = ST.catalogos || { personas_activas: [], telares: [] };
    const u = window.__rolsUser || {};
    // Por defecto, quien está logueado (si tiene acceso a muestras)
    llenarSelectPersonas($('ms-n-persona'), c.personas_activas, { vacio: '— quién la encarga —', usuario: u.username || '' });
    llenarSelect($('ms-n-telar'), c.telares, { vacio: '— telar / técnica —', otro: true, valor: '' });
    $('ms-n-telar').dataset.vacio = '— telar / técnica —';
    $('ms-n-cliente').value = ''; $('ms-n-desc').value = ''; $('ms-n-prio').value = '2';
    colorearPrio($('ms-n-prio'));
    $('ms-n-fecha').value = hoyISO();
    $('ms-n-variante').value = ''; $('ms-n-manual').value = '';
    modal.querySelector('input[name="ms-n-tipo"][value="auto"]').checked = true;
    const err = $('ms-n-error'); err.textContent = ''; err.classList.remove('show');
    modal.classList.add('open');
    setTimeout(() => $('ms-n-cliente').focus(), 50);
  }
  function cerrarNueva() { modal.classList.remove('open'); }
  $('ms-btn-nueva').addEventListener('click', abrirNueva);
  $('ms-n-cancelar').addEventListener('click', cerrarNueva);
  modal.addEventListener('click', (e) => { if (e.target === modal) cerrarNueva(); });
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && modal.classList.contains('open')) cerrarNueva(); });
  $('ms-n-prio').addEventListener('change', () => colorearPrio($('ms-n-prio')));
  $('ms-n-telar').addEventListener('change', () => gestionarOtro($('ms-n-telar'), 'telares', 'telar / técnica'));
  // Escribir en un campo de número selecciona su opción
  $('ms-n-variante').addEventListener('focus', () => { modal.querySelector('input[name="ms-n-tipo"][value="variante"]').checked = true; });
  $('ms-n-manual').addEventListener('focus', () => { modal.querySelector('input[name="ms-n-tipo"][value="manual"]').checked = true; });

  $('ms-n-crear').addEventListener('click', async () => {
    const err = $('ms-n-error');
    const fallo = (msg) => { err.textContent = msg; err.classList.add('show'); };
    err.classList.remove('show');
    const cliente = $('ms-n-cliente').value.trim();
    if (tipoNuevo === 'cliente' && !cliente) return fallo('Indica el cliente, o marca la muestra como interna.');
    const tipo = modal.querySelector('input[name="ms-n-tipo"]:checked').value;
    const body = {
      cliente, tipo: tipoNuevo, descripcion: $('ms-n-desc').value.trim(),
      encargada_por: $('ms-n-persona').value,
      telar: $('ms-n-telar').value === '__otro__' ? '' : $('ms-n-telar').value,
      prioridad: Number($('ms-n-prio').value), fecha_solicitud: $('ms-n-fecha').value || undefined,
    };
    if (tipo === 'variante') {
      const v = $('ms-n-variante').value.trim();
      if (!v) return fallo('Indica de qué número de M es variante.');
      body.variante_de = v;
    } else if (tipo === 'manual') {
      const n = $('ms-n-manual').value.trim();
      if (!n) return fallo('Indica el número manual.');
      body.numero_manual = Number(n);
    }
    const btn = $('ms-n-crear');
    btn.disabled = true;
    try {
      const d = await api('/api/muestras', { method: 'POST', body });
      location.href = '/muestras-fabricadas/' + encodeURIComponent(d.muestra.id);
    } catch (e) {
      fallo(e.message);
      btn.disabled = false;
    }
  });

  // ------------------------------------------------------------
  // Arranque
  // ------------------------------------------------------------
  const hash = (location.hash || '').replace('#', '');
  cargarEnCurso(true).then(() => {
    if (hash === 'historico' || hash === 'analisis') activarTab(hash, true);
  });
})();
