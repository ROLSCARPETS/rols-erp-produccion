// ============================================================
// Muestras fabricadas — listado: En curso · Histórico · Análisis
// + modal de alta. Requiere muestras-common.js (window.MS).
// ============================================================
(function () {
  'use strict';
  const { esc, fmtFecha, hoyISO, fmtNum, esTecnico, configTecnica, pintarConstruccion, numeroHtml, estadoPill, prioPill, clienteHtml, colorearPrio, api,
          ESTADOS, ESTADOS_LABEL, flujoQueContiene, etiquetaEstado, montarTablaMaterias,
          llenarSelect, llenarSelectPersonas, montarBuscadorCliente } = window.MS;
  const $ = id => document.getElementById(id);
  const debounce = (fn, ms) => { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; };

  const ST = {
    tab: 'en-curso',
    catalogos: null,
    resumen: null,
    // por defecto, por fecha de solicitud descendente (la más reciente arriba)
    ec: { rows: [], estados: new Set(), sort: { campo: 'fecha_solicitud', dir: -1 }, cargado: false },
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
    const sub = [];
    if (r.hitos_vencidos) sub.push(`${fmtNum(r.hitos_vencidos)} hito${r.hitos_vencidos === 1 ? '' : 's'} vencido${r.hitos_vencidos === 1 ? '' : 's'}`);
    if (r.hitos_semana) sub.push(`${fmtNum(r.hitos_semana)} hito${r.hitos_semana === 1 ? '' : 's'} esta semana`);
    if (arch) sub.push(`${fmtNum(arch)} archivadas sin terminar`);
    $('kpi-curso-sub').textContent = sub.length ? sub.join(' · ') : 'muestras en fabricación';
    $('kpi-curso-sub').style.color = r.hitos_vencidos ? '#9b1c1c' : '';
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
    // Todas las etapas vivas, con la de revisión de diseño (Print) en su sitio.
    const slugs = ESTADOS.map(e => e[0])
      .filter(s => !['terminada', 'cancelada', 'sin_seguimiento'].includes(s));
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
      $('ec-tbody').innerHTML = `<tr><td colspan="12" class="ms-vacio">No se pudo cargar: ${esc(e.message)}</td></tr>`;
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

  // Opciones del select de estado de una fila: el flujo que toca a SU técnica
  // (el corto de Print, el de Varilla o el textil), más cancelada y el estado
  // actual. Igual que la ficha, una Print parada en una etapa textil sigue su
  // flujo textil.
  function opcionesEstado(m) {
    const actual = m.estado;
    const flujo = flujoQueContiene(m.telar, actual);
    return ESTADOS.filter(e => {
      const s = e[0];
      if (s === actual) return true;
      if (s === 'sin_seguimiento') return false;
      if (s === 'cancelada') return true;
      return flujo.includes(s);
    }).map(e => `<option value="${e[0]}" ${e[0] === actual ? 'selected' : ''}>${esc(etiquetaEstado(e[0], m.telar))}</option>`).join('');
  }

  function ordenar(rows) {
    const { campo, dir } = ST.ec.sort;
    if (!campo) return rows;
    const val = m => {
      if (campo === 'numero') return [(m.numero == null ? 1e9 : m.numero), m.sufijo || ''];
      if (campo === 'fecha_solicitud') return [m.fecha_solicitud || '', (m.numero == null ? 0 : m.numero)];
      if (campo === 'prioridad') return [m.prioridad == null ? 9 : m.prioridad];
      if (campo === 'dias') return [m.dias == null ? -1 : m.dias];
      if (campo === 'proximo_hito_fecha') return [m.proximo_hito_fecha || '9999-12-31'];
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
    const sel = `<select class="ms-sel-estado ms-estado-${esc(m.estado)}" data-id="${esc(m.id)}" data-estado="${esc(m.estado)}" title="Cambiar el estado">${opcionesEstado(m)}</select>`;
    const mudo = '<span class="ms-mudo">—</span>';
    return `<tr class="ms-fila" data-id="${esc(m.id)}">
      <td class="ms-fecha">${fmtFecha(m.fecha_solicitud, false) || mudo}</td>
      <td>${numeroHtml(m)}</td>
      <td class="ms-cliente">${clienteHtml(m)}</td>
      <td><div class="ms-desc${m.referencia ? ' ref' : ''}" title="${esc(m.referencia ? (m.descripcion ? m.referencia + '\n\n' + m.descripcion : m.referencia) : m.descripcion)}">${esc(m.referencia || m.descripcion) || mudo}</div></td>
      <td>${esc(m.encargada_por) || mudo}</td>
      <td>${prioPill(m.prioridad)}</td>
      <td>${esc(m.telar) || mudo}</td>
      <td>${sel}</td>
      <td class="num"><span class="ms-dias ${(m.dias || 0) > 120 ? 'tarde' : ''}" title="Días desde la solicitud">${m.dias != null ? fmtNum(m.dias) : '—'}</span>${m.fecha_estimada ? `<div class="ms-prev ${m.fecha_estimada < hoyISO() ? 'pasada' : ''}" title="Fecha estimada de muestra lista">prev. ${esc(fmtFecha(m.fecha_estimada, false))}</div>` : ''}</td>
      <td class="ms-hito-td"><input type="date" class="ms-hito-inp ${m.hito_vencido ? 'vencido' : ''}" data-id="${esc(m.id)}" value="${esc(m.proximo_hito_fecha || '')}" title="${esc(m.proximo_hito || 'Fecha del próximo hito (se guarda al cambiarla)')}" />${m.proximo_hito ? `<div class="ms-hito-txt" title="${esc(m.proximo_hito)}">${esc(m.proximo_hito)}</div>` : ''}${m.hito_vencido ? '<div class="ms-hito-venc">vencido</div>' : ''}</td>
      <td>${ult ? `<div class="ms-apunte-mini" title="${esc(ult.texto)}${ult.usuario_nombre ? ' — ' + esc(ult.usuario_nombre) : ''}"><b>${esc(fmtFecha(ult.fecha, false) || 's/f')}</b>${esc(ult.texto)}${ult.usuario_nombre ? ` <span class="ms-mudo">— ${esc(ult.usuario_nombre)}</span>` : ''}</div>` : '<span class="ms-mudo">sin apuntes</span>'}</td>
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
      tb.innerHTML = `<tr><td colspan="12" class="ms-vacio">${hayFiltro ? 'Ninguna muestra en curso coincide con el filtro.' : 'No hay muestras en curso. Crea una con «Nueva muestra».'}</td></tr>`;
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

  // Click en fila → ficha (salvo sobre el select de estado o la fecha del hito)
  $('ec-tbody').addEventListener('click', (e) => {
    if (e.target.closest('select') || e.target.closest('input')) return;
    const tr = e.target.closest('tr.ms-fila');
    if (tr) location.href = '/muestras-fabricadas/' + encodeURIComponent(tr.dataset.id);
  });

  // Fecha del próximo hito inline (comercial o laboratorio la ponen desde la tabla)
  $('ec-tbody').addEventListener('change', async (e) => {
    const inp = e.target.closest('input.ms-hito-inp');
    if (!inp) return;
    inp.disabled = true;
    try {
      await api(`/api/muestras/${encodeURIComponent(inp.dataset.id)}`, { method: 'PUT', body: { proximo_hito_fecha: inp.value || '' } });
      await cargarEnCurso(false);
    } catch (err) {
      inp.disabled = false;
      await window.mostrarAlerta({ titulo: 'No se pudo guardar el hito', mensaje: err.message, tipo: 'danger' });
    }
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
      <td class="ms-fecha">${fmtFecha(m.fecha_solicitud, false) || mudo}</td>
      <td>${numeroHtml(m)}</td>
      <td class="ms-cliente">${clienteHtml(m)}</td>
      <td><div class="ms-desc${m.referencia ? ' ref' : ''}" title="${esc(m.referencia ? (m.descripcion ? m.referencia + '\n\n' + m.descripcion : m.referencia) : m.descripcion)}">${esc(m.referencia || m.descripcion) || mudo}</div></td>
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
    pintarMeses(d);
    // Reparto
    const barras = (lista, clave) => {
      const mx = Math.max(1, ...lista.map(x => x.n));
      return lista.slice(0, 14).map(x => `<div class="ms-bar-row"><span class="lbl" title="${esc(x[clave])}">${esc(x[clave])}</span><div class="ms-bar"><i style="width:${Math.round((x.n / mx) * 100)}%"></i></div><span class="n">${fmtNum(x.n)}</span></div>`).join('')
        || '<span class="ms-mudo">Sin datos</span>';
    };
    $('an-telar').innerHTML = barras(d.por_telar || [], 'telar');
    $('an-persona').innerHTML = barras(d.por_persona || [], 'persona');
    cargarAvisosEstado();
  }

  // Estado de los avisos por correo (pestaña Análisis) + correo de prueba
  async function cargarAvisosEstado() {
    const box = $('an-avisos-estado');
    try {
      const e = await api('/api/muestras/avisos/estado');
      if (e.configurado) {
        box.innerHTML = `<span class="ms-estado" style="background:#e8f3e1;color:#2f6b29">Correo configurado</span> ` +
          `remitente <b>${esc(e.remitente)}</b> · servidor ${esc(e.host)}${e.origen ? ' — ' + esc(e.origen) : ''} · e-mails conocidos de ${fmtNum(e.directorio_usuarios)} usuarios` +
          (e.ultimo_chequeo_hitos ? ` · último chequeo de hitos ${esc(String(e.ultimo_chequeo_hitos).replace('T', ' ').slice(0, 16))}` : ' · el chequeo de hitos corre solo al usar la app (como mucho cada 15 min)') +
          (e.ultimo && e.ultimo.cuando ? ` · último envío ${esc(String(e.ultimo.cuando).replace('T', ' ').slice(0, 16))}: ${e.ultimo.ok ? 'OK por ' + esc(e.ultimo.via || '') : 'ERROR ' + esc(e.ultimo.error || '')}` : '');
      } else {
        box.innerHTML = `<span class="ms-estado" style="background:#fde2e2;color:#9b1c1c">Correo sin configurar</span> ` +
          `hasta que el servidor tenga <code>ROLS_SMTP_HOST</code>, <code>ROLS_SMTP_USER</code> y <code>ROLS_SMTP_PASS</code> en su <code>.env</code> (o un <code>correo.json</code> en la carpeta de datos) no se envía nada; el resto funciona igual.`;
      }
      $('an-avisos-prueba').hidden = !e.es_admin;
      if (!AVISOS) cargarAvisosConfig();
    } catch (err) {
      box.textContent = 'No se pudo consultar el estado de los avisos: ' + err.message;
    }
  }
  // ------------------------------------------------------------
  // Quién recibe cada aviso (la tabla se puede cambiar si eres admin)
  // ------------------------------------------------------------
  let AVISOS = null;
  const MODOS = [['no', 'No se le avisa'], ['salvo_actor', 'Sí, salvo si lo hace ella'], ['siempre', 'Sí, siempre']];

  async function cargarAvisosConfig() {
    const tb = $('an-avisos-filas');
    try {
      AVISOS = await api('/api/muestras/avisos/config');
    } catch (e) {
      tb.innerHTML = `<tr><td colspan="5" class="ms-vacio">No se pudo cargar: ${esc(e.message)}</td></tr>`;
      return;
    }
    pintarAvisosConfig();
  }

  function filaCambiada(clave) {
    const c = AVISOS.config[clave] || {}, d = AVISOS.por_defecto[clave] || {};
    return c.encargada !== d.encargada || !!c.creador !== !!d.creador
      || (c.buzones || []).join(',') !== (d.buzones || []).join(',');
  }

  function pintarAvisosConfig() {
    const { config, filas, editable } = AVISOS;
    const off = editable ? '' : ' disabled';
    $('an-avisos-filas').innerHTML = filas.map(f => {
      const c = config[f.clave] || {};
      const etiqueta = f.tipo === 'etapa'
        ? `<span class="ms-estado ms-estado-${esc(f.clave)}">${esc(f.etiqueta)}</span>`
        : `<span class="ms-estado ms-estado-${f.clave === 'nueva' ? 'esperando_telar' : 'en_telar'}">${esc(f.etiqueta)}</span>`;
      const opciones = MODOS.map(([v, l]) =>
        `<option value="${v}" ${c.encargada === v ? 'selected' : ''}>${esc(l)}</option>`).join('');
      return `<tr data-clave="${esc(f.clave)}">
        <td>${etiqueta}${filaCambiada(f.clave) ? '<span class="ms-av-cambiado" title="Cambiado respecto al valor de fábrica">cambiado</span>' : ''}
          ${f.nota ? `<div class="ms-hint">${esc(f.nota)}</div>` : ''}</td>
        <td><select class="ms-av-campo" data-campo="encargada"${off}>${opciones}</select></td>
        <td><label class="ms-av-check"><input type="checkbox" class="ms-av-campo" data-campo="creador" ${c.creador ? 'checked' : ''}${off} /><span>Avisar</span></label></td>
        <td><input type="text" class="ms-av-campo ms-av-buzones" data-campo="buzones" value="${esc((c.buzones || []).join(', '))}" placeholder="nadie más" title="E-mails separados por comas"${off} /></td>
        <td class="ms-avisos-asunto">${esc(f.asunto)}</td>
      </tr>`;
    }).join('');
    $('an-avisos-quien-manda').textContent = editable
      ? 'Los cambios se guardan solos.'
      : 'Solo un administrador puede cambiar los destinatarios.';
    $('an-avisos-reset').hidden = !editable || !filas.some(f => filaCambiada(f.clave));
  }

  async function guardarAviso(el) {
    const tr = el.closest('tr');
    const clave = tr.dataset.clave, campo = el.dataset.campo;
    const valor = campo === 'creador' ? el.checked
      : campo === 'buzones' ? el.value.split(/[,;\s]+/).filter(Boolean) : el.value;
    el.classList.remove('saved-ok', 'saved-err');
    el.classList.add('saving');
    try {
      const d = await api('/api/muestras/avisos/config', { method: 'PUT', body: { [clave]: { [campo]: valor } } });
      AVISOS.config = d.config;
      el.classList.remove('saving');
      el.classList.add('saved-ok');
      setTimeout(() => el.classList.remove('saved-ok'), 1400);
      // la marca de "cambiado" y el botón de fábrica dependen de la fila entera
      const c = AVISOS.config[clave] || {};
      if (campo === 'buzones') el.value = (c.buzones || []).join(', ');
      tr.querySelector('.ms-av-cambiado')?.remove();
      if (filaCambiada(clave)) {
        tr.querySelector('td').insertAdjacentHTML('afterbegin',
          '<span class="ms-av-cambiado" title="Cambiado respecto al valor de fábrica">cambiado</span>');
      }
      $('an-avisos-reset').hidden = !AVISOS.filas.some(f => filaCambiada(f.clave));
    } catch (e) {
      el.classList.remove('saving');
      el.classList.add('saved-err');
      await window.mostrarAlerta({ titulo: 'No se pudo guardar', mensaje: e.message, tipo: 'danger' });
      pintarAvisosConfig();
    }
  }

  $('an-avisos-filas').addEventListener('change', (e) => {
    const el = e.target.closest('.ms-av-campo');
    if (el && !el.disabled) guardarAviso(el);
  });

  $('an-avisos-reset').addEventListener('click', async () => {
    const r = await window.mostrarConfirmacion({
      titulo: 'Volver a los valores de fábrica',
      mensaje: 'Los destinatarios de todas las etapas vuelven a como venían de serie. Lo que hayas cambiado se pierde.',
      textoConfirmar: 'Restablecer',
    });
    if (!r.ok) return;
    try {
      const d = await api('/api/muestras/avisos/config', { method: 'PUT', body: AVISOS.por_defecto });
      AVISOS.config = d.config;
      pintarAvisosConfig();
    } catch (e) {
      await window.mostrarAlerta({ titulo: 'No se pudo restablecer', mensaje: e.message, tipo: 'danger' });
    }
  });

  $('an-avisos-prueba').addEventListener('click', async () => {
    const b = $('an-avisos-prueba');
    b.disabled = true;
    $('an-avisos-res').textContent = 'Enviando…';
    try {
      const r = await api('/api/muestras/avisos/prueba', { method: 'POST', body: {} });
      $('an-avisos-res').textContent = r.ok ? `Enviado a ${r.email}${r.via ? ' por ' + r.via : ''}. Mira tu bandeja (y el correo no deseado).` : `No se pudo enviar: ${r.error}`;
    } catch (e) {
      $('an-avisos-res').textContent = 'Error: ' + e.message;
    } finally {
      b.disabled = false;
    }
  });
  $('an-anio').addEventListener('change', cargarAnalisis);

  // Escala "limpia" para el eje: máximo redondeado a un paso cómodo (2, 5, 10, 20…)
  function escalaBonita(max) {
    const pasos = [1, 2, 5, 10, 20, 25, 50, 100, 200, 500];
    const bruto = Math.max(1, max) / 4;
    const paso = pasos.find(p => p >= bruto) || pasos[pasos.length - 1];
    return { paso, max: Math.max(paso, Math.ceil(Math.max(1, max) / paso) * paso) };
  }

  const MESES_LARGO = ['enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio', 'julio', 'agosto', 'septiembre', 'octubre', 'noviembre', 'diciembre'];

  // Columnas agrupadas: año actual (ámbar) frente al anterior (azul), con
  // rejilla, valores sobre el año actual, mes en curso resaltado y meses
  // futuros vacíos. La tabla gemela lleva todos los valores.
  function pintarMeses(d) {
    const anios = Object.keys(d.por_mes || {}).map(Number).sort((a, b) => b - a);
    const actual = anios[0], prev = anios[1];
    const va = (d.por_mes && d.por_mes[String(actual)]) || [], vp = (d.por_mes && d.por_mes[String(prev)]) || [];
    const hoy = new Date();
    const mesHoy = (hoy.getFullYear() === actual) ? hoy.getMonth() : 11;
    const esc_ = escalaBonita(Math.max(...va, ...vp, 1));
    const pct = v => Math.max(0, Math.min(100, (v / esc_.max) * 100));
    // Rejilla + eje
    const ticks = [];
    for (let t = 0; t <= esc_.max; t += esc_.paso) ticks.push(t);
    $('an-chart-y').innerHTML = ticks.map(t => `<span style="bottom:${pct(t)}%">${fmtNum(t)}</span>`).join('');
    const grid = ticks.filter(t => t > 0).map(t => `<div class="ms-chart-grid" style="bottom:${pct(t)}%"></div>`).join('');
    // Columnas
    const cols = MESES.map((m, i) => {
      const p = vp[i] || 0, a = va[i] || 0;
      const futuro = i > mesHoy;
      const tPrev = `${MESES_LARGO[i]} ${prev}: ${fmtNum(p)} solicitud${p === 1 ? '' : 'es'}`;
      const tAct = `${MESES_LARGO[i]} ${actual}: ${fmtNum(a)} solicitud${a === 1 ? '' : 'es'}`;
      const barPrev = `<div class="ms-col prev ${p ? '' : 'cero'}" style="height:${pct(p)}%" title="${esc(tPrev)}"><span class="val">${fmtNum(p)}</span></div>`;
      const barAct = futuro ? '' : `<div class="ms-col act ${a ? '' : 'cero'}" style="height:${pct(a)}%" title="${esc(tAct)}"><span class="val">${fmtNum(a)}</span></div>`;
      return `<div class="ms-mes ${i === mesHoy ? 'actual' : ''}">${barPrev}${barAct}</div>`;
    }).join('');
    $('an-meses').innerHTML = grid + cols;
    $('an-chart-x').innerHTML = MESES.map((m, i) => `<span class="${i === mesHoy ? 'actual' : (i > mesHoy ? 'futuro' : '')}">${m}</span>`).join('');
    // Leyenda con totales
    const totA = va.reduce((s, x) => s + x, 0), totP = vp.reduce((s, x) => s + x, 0);
    const totPHasta = vp.slice(0, mesHoy + 1).reduce((s, x) => s + x, 0);
    $('an-leyenda').innerHTML = `<span><i class="act"></i>${actual} · ${fmtNum(totA)}</span><span><i class="prev"></i>${prev} · ${fmtNum(totP)}</span>`;
    const dif = totA - totPHasta;
    $('an-chart-nota').textContent = mesHoy < 11
      ? `Hasta ${MESES_LARGO[mesHoy]}: ${fmtNum(totA)} en ${actual} frente a ${fmtNum(totPHasta)} en ${prev} (${dif >= 0 ? '+' : '−'}${fmtNum(Math.abs(dif))}) · los meses en gris aún no han llegado`
      : `${fmtNum(totA)} en ${actual} frente a ${fmtNum(totP)} en ${prev} (${dif >= 0 ? '+' : '−'}${fmtNum(Math.abs(dif))})`;
    // Tabla gemela
    $('an-th-prev').textContent = prev; $('an-th-act').textContent = actual;
    $('an-tabla-body').innerHTML = MESES.map((m, i) => {
      const p = vp[i] || 0, a = va[i] || 0, futuro = i > mesHoy, df = a - p;
      return `<tr><td>${MESES_LARGO[i]}</td><td class="num">${fmtNum(p)}</td><td class="num">${futuro ? '<span class="ms-mudo">—</span>' : fmtNum(a)}</td>` +
             `<td class="num ${futuro ? '' : (df > 0 ? 'pos' : (df < 0 ? 'neg' : ''))}">${futuro ? '<span class="ms-mudo">—</span>' : (df > 0 ? '+' : '') + fmtNum(df)}</td></tr>`;
    }).join('');
  }
  $('an-tabla-btn').addEventListener('click', () => {
    const w = $('an-tabla-wrap');
    w.hidden = !w.hidden;
    $('an-tabla-btn').textContent = w.hidden ? 'Ver como tabla' : 'Ocultar tabla';
  });

  // ------------------------------------------------------------
  // NUEVA MUESTRA (modal)
  // ------------------------------------------------------------
  const modal = $('ms-modal-nueva');
  let tipoNuevo = 'cliente';
  // Cliente elegido de Navision (código); se pierde si se edita el texto
  let clienteNav = null;
  function pintarNavLink() {
    $('ms-n-nav').hidden = !clienteNav;
    $('ms-n-nav-no').textContent = clienteNav || '';
  }
  montarBuscadorCliente($('ms-n-cliente'), {
    clientesUsados: () => (ST.catalogos && ST.catalogos.clientes) || [],
    onElegir: (it) => { clienteNav = it.no || null; pintarNavLink(); },
    onTexto: () => { if (clienteNav) { clienteNav = null; pintarNavLink(); } },
  });
  $('ms-n-nav-quitar').addEventListener('click', () => { clienteNav = null; pintarNavLink(); });
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
  const tablaMaterias = montarTablaMaterias($('ms-n-materias'), { listaMateriales: 'ms-materiales', listaColoridos: 'ms-coloridos' });

  function abrirNueva() {
    ponerTipoNuevo('cliente');
    const c = ST.catalogos || { personas_activas: [], telares: [] };
    const u = window.__rolsUser || {};
    // Por defecto, quien está logueado (si tiene acceso a muestras)
    llenarSelectPersonas($('ms-n-persona'), c.personas_activas, { vacio: '— quién la encarga —', usuario: u.username || '' });
    llenarSelect($('ms-n-telar'), c.telares_alta || c.telares, { vacio: '— telar / técnica —', valor: '' });
    $('ms-n-telar').dataset.vacio = '— telar / técnica —';
    // Datos técnicos: solo con telar de varilla
    $('ms-materiales').innerHTML = (c.materiales || []).map(x => `<option value="${esc(x)}"></option>`).join('');
    $('ms-coloridos').innerHTML = (c.coloridos || []).map(x => `<option value="${esc(x)}"></option>`).join('');
    ['ms-n-ref', 'ms-n-pasadas', 'ms-n-altura', 'ms-n-cuerpos', 'ms-n-acabado'].forEach(id => { $(id).value = ''; });
    tablaMaterias.pintar([]);
    modal.querySelectorAll('.ms-falta').forEach(el => el.classList.remove('ms-falta'));
    pintarTecnicaAlta('');   // alta nueva: sin construcción arrastrada de la anterior
    $('ms-n-cliente').value = ''; $('ms-n-desc').value = ''; $('ms-n-prio').value = '2';
    clienteNav = null; pintarNavLink();
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
  // El bloque técnico (y las construcciones que ofrece) dependen del telar
  function pintarTecnicaAlta(valorPelo) {
    const telar = $('ms-n-telar').value;
    const cfg = configTecnica(telar);
    $('ms-n-tecnica').hidden = !esTecnico(telar);
    $('ms-n-tecnica-telar').textContent = (cfg.esTelar ? 'telar ' : '') + telar;
    // Pompón no teje: solo lleva materias
    $('ms-n-tecnica').querySelectorAll('.tejeduria').forEach(el => { el.hidden = !cfg.tejeduria; });
    $('ms-n-materias-sub').firstChild.textContent = 'Datos de materias ';
    $('ms-n-materias-sub').querySelector('.ms-hint').textContent = `una fila por ${cfg.etiquetaCuerpo.toLowerCase()}`;
    $('ms-n-cuerpos-lbl').textContent = cfg.etiquetaN;
    const actual = valorPelo === undefined ? $('ms-n-pelo').value : valorPelo;
    pintarConstruccion($('ms-n-pelo'), telar, actual || '', $('ms-n-pelo-fijo'));
    tablaMaterias.configurar({ etiquetaCuerpo: cfg.etiquetaCuerpo, conHilos: cfg.hilosPua });
  }

  // Al escribir en un campo que faltaba, se le quita la marca de rojo
  ['input', 'change'].forEach(ev => $('ms-n-tecnica').addEventListener(ev, (e) => {
    if (e.target.matches('input, select')) e.target.classList.remove('ms-falta');
  }));

  // Una muestra de varilla se da de alta con sus datos técnicos rellenos: lo
  // que todavía no se sepa se escribe «Pdte» (o «Pendiente» en los dos selectores).
  function faltanTecnicos(telar) {
    const cfg = configTecnica(telar);
    const tejeduria = [['ms-n-pasadas', 'Pasadas'], ['ms-n-altura', 'Altura felpa'],
      ['ms-n-cuerpos', cfg.etiquetaN], ['ms-n-pelo', 'Construcción'], ['ms-n-acabado', 'Acabado']];
    const faltan = [];
    tejeduria.forEach(([id, etiqueta]) => {
      const el = $(id);
      const vacio = cfg.tejeduria && !el.value.trim();
      el.classList.toggle('ms-falta', vacio);
      if (vacio) faltan.push(etiqueta);
    });
    // Una fila cuenta cuando dice algo de la materia (igual que en el servidor):
    // la que solo lleva el nº de cuerpo propuesto está sin usar y no estorba.
    const filas = [...$('ms-n-materias').querySelectorAll('.ms-materia')];
    const usada = f => ['.materia', '.hilos', '.colorido'].some(s => f.querySelector(s).value.trim());
    const usadas = filas.filter(usada);
    let incompletas = 0;
    filas.forEach(f => {
      const cuenta = usadas.includes(f) || (!usadas.length && f === filas[0]);
      f.querySelectorAll('input').forEach(inp => {
        const vacio = cuenta && !inp.value.trim();
        inp.classList.toggle('ms-falta', vacio);
        if (vacio) incompletas++;
      });
    });
    if (incompletas) {
      const cols = [cfg.etiquetaCuerpo.toLowerCase(), 'materia']
        .concat(cfg.hilosPua ? ['hilos púa'] : []).concat(['colorido']);
      faltan.push(`las materias (${cols.join(', ')})`);
    }
    return faltan;
  }

  $('ms-n-telar').addEventListener('change', () => pintarTecnicaAlta());
  // Escribir en un campo de número selecciona su opción
  $('ms-n-variante').addEventListener('focus', () => { modal.querySelector('input[name="ms-n-tipo"][value="variante"]').checked = true; });
  $('ms-n-manual').addEventListener('focus', () => { modal.querySelector('input[name="ms-n-tipo"][value="manual"]').checked = true; });

  $('ms-n-crear').addEventListener('click', async () => {
    const err = $('ms-n-error');
    const fallo = (msg) => { err.textContent = msg; err.classList.add('show'); };
    err.classList.remove('show');
    const cliente = $('ms-n-cliente').value.trim();
    if (tipoNuevo === 'cliente' && !cliente) return fallo('Indica el cliente, o marca la muestra como interna.');
    const telarNuevo = $('ms-n-telar').value;
    if (esTecnico(telarNuevo)) {
      const faltan = faltanTecnicos(telarNuevo);
      if (faltan.length) {
        $('ms-n-tecnica').scrollIntoView({ block: 'center', behavior: 'smooth' });
        return fallo(`Una muestra de ${telarNuevo} se da de alta con sus datos técnicos. Falta: ${faltan.join(', ')}. Si todavía no se sabe, escribe «Pdte».`);
      }
    }
    const tipo = modal.querySelector('input[name="ms-n-tipo"]:checked').value;
    const body = {
      cliente, tipo: tipoNuevo, cliente_navision: clienteNav || '', referencia: $('ms-n-ref').value.trim(), descripcion: $('ms-n-desc').value.trim(),
      encargada_por: $('ms-n-persona').value,
      telar: telarNuevo,
      prioridad: Number($('ms-n-prio').value), fecha_solicitud: $('ms-n-fecha').value || undefined,
      materias: tablaMaterias.utiles(),
    };
    // La tejeduría solo va en los telares que la llevan: así un telar sin ella
    // (Pompón) no se lleva lo que quedara escrito de otro telar.
    if (configTecnica(telarNuevo).tejeduria) {
      Object.assign(body, {
        pasadas: $('ms-n-pasadas').value.trim(), altura_felpa: $('ms-n-altura').value.trim(),
        n_cuerpos: $('ms-n-cuerpos').value.trim(),
        pelo: $('ms-n-pelo').value, acabado: $('ms-n-acabado').value,
      });
    }
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
