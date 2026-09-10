// ============================================================
// Ficha de una muestra fabricada (/muestras-fabricadas/<id>):
// estado (stepper), ficha con autoguardado, diario del laboratorio,
// variantes e historial. Requiere muestras-common.js (window.MS).
// ============================================================
(function () {
  'use strict';
  const { esc, fmtFecha, fmtFechaHora, hoyISO, fmtNum, estadoPill, prioPill, tipoTag, colorearPrio, api,
          ESTADOS_LABEL, ESTADOS_FLUJO, esAdmin, llenarSelect, llenarSelectPersonas, gestionarOtro, montarBuscadorCliente } = window.MS;
  const $ = id => document.getElementById(id);
  const MID = window.MUESTRA_ID;
  const URL_API = '/api/muestras/' + encodeURIComponent(MID);
  const TERMINALES = ['terminada', 'cancelada', 'sin_seguimiento'];

  let M = null;      // la muestra (ficha completa)
  let CAT = null;    // catálogos

  // ------------------------------------------------------------
  // Carga
  // ------------------------------------------------------------
  async function cargar() {
    try {
      const [d, c] = await Promise.all([api(URL_API), CAT ? Promise.resolve(CAT) : api('/api/muestras/catalogos')]);
      M = d.muestra;
      CAT = c;
    } catch (e) {
      $('md-cliente').textContent = '';
      $('md-sub').textContent = e.status === 404 ? 'Esta muestra no existe.' : `No se pudo cargar: ${e.message}`;
      $('md-stepper').innerHTML = '';
      return;
    }
    pintarTodo();
  }

  function pintarTodo() {
    pintarHero();
    pintarStepper();
    pintarFicha();
    pintarDiario();
    pintarVariantes();
    pintarHistorial();
  }

  // ------------------------------------------------------------
  // Hero + acciones
  // ------------------------------------------------------------
  function pintarHero() {
    document.title = `M-${M.id} · ${M.cliente || ''} — Rols ERP Producción`;
    $('md-bread').textContent = `M-${M.id}`;
    $('md-titulo').textContent = `M-${M.id}`;
    const esInterna = M.tipo === 'interna';
    $('md-cliente').textContent = M.cliente || (esInterna ? 'Interna' : '—');
    let chips = tipoTag(M) + estadoPill(M.estado, M.estado_label) + ' ' + prioPill(M.prioridad);
    if (M.telar) chips += ` <span class="ms-estado" style="background:#f1ece4;color:#6b5323">${esc(M.telar)}</span>`;
    if (M.cliente_navision) chips += ` <span class="ms-estado" style="background:#dbeafe;color:#1e40af" title="Cliente vinculado a su ficha de Navision">Navision ${esc(M.cliente_navision)}</span>`;
    if (M.archivada && !TERMINALES.includes(M.estado)) chips += ' <span class="ms-tag-archivada">archivada</span>';
    $('md-chips').innerHTML = chips;

    const partes = [];
    if (M.fecha_solicitud) partes.push(`Solicitada el ${fmtFecha(M.fecha_solicitud)}${M.encargada_por ? ' por ' + esc(M.encargada_por) : ''}`);
    else if (M.encargada_por) partes.push(`Encargada por ${esc(M.encargada_por)}`);
    if (M.estado === 'terminada') {
      partes.push(M.fecha_lista ? `lista el ${fmtFecha(M.fecha_lista)}${M.dias != null ? ` (${fmtNum(M.dias)} días)` : ''}` : 'terminada');
    } else if (M.estado === 'cancelada') {
      partes.push('cancelada');
    } else if (M.estado === 'sin_seguimiento') {
      partes.push('sin hoja de seguimiento en el libro antiguo');
    } else if (M.dias != null) {
      partes.push(`<b>${fmtNum(M.dias)} días</b> en curso`);
    }
    if (M.sufijo && M.numero != null) partes.push(`variante de M-${M.numero}`);
    if (M.proximo_hito_fecha && !TERMINALES.includes(M.estado)) {
      partes.push(`<span class="${M.hito_vencido ? 'ms-hito-venc-inline' : ''}">próximo hito ${fmtFecha(M.proximo_hito_fecha)}${M.proximo_hito ? ' — ' + esc(M.proximo_hito) : ''}${M.hito_vencido ? ' (vencido)' : ''}</span>`);
    }
    $('md-sub').innerHTML = partes.join(' · ') || '—';

    $('md-btn-variante').hidden = M.numero == null;
    const activa = !TERMINALES.includes(M.estado);
    const bArch = $('md-btn-archivar');
    bArch.hidden = !activa && !M.archivada;
    bArch.textContent = M.archivada ? 'Devolver a «En curso»' : 'Archivar';
    bArch.title = M.archivada ? 'Vuelve a aparecer en el seguimiento' : 'La quita de «En curso» sin darla por terminada (como mover la fila a la hoja de terminadas)';
    $('md-btn-borrar').hidden = !esAdmin();
  }

  $('md-btn-variante').addEventListener('click', async () => {
    const r = await window.mostrarConfirmacion({
      titulo: `Nueva variante de M-${M.numero}`,
      mensaje: `Se crea una muestra nueva con la siguiente letra (${M.variantes && M.variantes.length ? 'después de las existentes' : 'B'}), mismo cliente, telar y quien la encarga. La descripción se rellena en su ficha.`,
      textoConfirmar: 'Crear variante',
    });
    if (!r.ok) return;
    try {
      const d = await api('/api/muestras', { method: 'POST', body: {
        variante_de: M.numero, cliente: M.cliente, tipo: M.tipo || 'cliente',
        encargada_por: M.encargada_por_usuario || '',
        telar: M.telar, prioridad: M.prioridad || 2, descripcion: '',
      } });
      location.href = '/muestras-fabricadas/' + encodeURIComponent(d.muestra.id);
    } catch (e) {
      await window.mostrarAlerta({ titulo: 'No se pudo crear la variante', mensaje: e.message, tipo: 'danger' });
    }
  });

  $('md-btn-archivar').addEventListener('click', async () => {
    const archivar = !M.archivada;
    const r = await window.mostrarConfirmacion({
      titulo: archivar ? `Archivar M-${M.id}` : `Devolver M-${M.id} a «En curso»`,
      mensaje: archivar
        ? `Deja de aparecer en el seguimiento pero conserva su estado (${M.estado_label}). Si de verdad está hecha, mejor márcala como terminada.`
        : 'Volverá a aparecer en el seguimiento con su estado actual.',
      textoConfirmar: archivar ? 'Archivar' : 'Devolver a En curso',
    });
    if (!r.ok) return;
    try {
      const d = await api(URL_API + '/archivar', { method: 'POST', body: { archivada: archivar } });
      M = d.muestra; pintarTodo();
    } catch (e) {
      await window.mostrarAlerta({ titulo: 'No se pudo', mensaje: e.message, tipo: 'danger' });
    }
  });

  $('md-btn-borrar').addEventListener('click', async () => {
    const r = await window.mostrarConfirmacion({
      titulo: `Borrar la muestra M-${M.id}`,
      mensaje: 'Se elimina la ficha, el diario y el historial. Es para altas por error: si la muestra existió, cancélala en lugar de borrarla. No se puede deshacer.',
      textoConfirmar: 'Borrar definitivamente', tipo: 'danger',
    });
    if (!r.ok) return;
    try {
      await api(URL_API, { method: 'DELETE' });
      location.href = '/muestras-fabricadas';
    } catch (e) {
      await window.mostrarAlerta({ titulo: 'No se pudo borrar', mensaje: e.message, tipo: 'danger' });
    }
  });

  // ------------------------------------------------------------
  // Stepper de estado
  // ------------------------------------------------------------
  function pintarStepper() {
    const idx = ESTADOS_FLUJO.indexOf(M.estado);
    $('md-stepper').innerHTML = ESTADOS_FLUJO.map((s, i) => {
      const cls = i === idx ? 'actual' : (idx >= 0 && i < idx ? 'hecho' : '');
      return `<div class="ms-step ${cls}" data-estado="${s}" title="${i === idx ? 'Estado actual' : 'Pasar a: ' + esc(ESTADOS_LABEL[s])}"><div class="dot"></div>${esc(ESTADOS_LABEL[s])}</div>`;
    }).join('');
    let txt, acciones = '';
    if (M.estado === 'cancelada') {
      txt = 'Muestra <b>cancelada</b>. Pulsa una etapa para reabrirla.';
    } else if (M.estado === 'terminada') {
      txt = `<b>Terminada</b>${M.fecha_lista ? ' el ' + fmtFecha(M.fecha_lista) : ''} · pulsa una etapa anterior si hay que reabrirla.`;
    } else if (M.estado === 'sin_seguimiento') {
      txt = 'Sin seguimiento (venía solo del registro de números). Pulsa una etapa si quieres empezar a seguirla.';
    } else {
      txt = `Ahora en <b>${esc(M.estado_label)}</b> · pulsa la siguiente etapa cuando avance.`;
      acciones = '<button type="button" class="ms-link danger" id="md-btn-cancelar">Cancelar muestra</button>';
    }
    $('md-estado-txt').innerHTML = txt;
    $('md-estado-acciones').innerHTML = acciones;
    const bc = $('md-btn-cancelar');
    if (bc) bc.addEventListener('click', cancelarMuestra);
  }

  $('md-stepper').addEventListener('click', async (e) => {
    const st = e.target.closest('.ms-step');
    if (!st) return;
    const nuevo = st.dataset.estado;
    if (nuevo === M.estado) return;
    let nota = '';
    const idxNuevo = ESTADOS_FLUJO.indexOf(nuevo), idxAct = ESTADOS_FLUJO.indexOf(M.estado);
    if (nuevo === 'terminada') {
      const r = await window.mostrarConfirmacion({
        titulo: `Marcar M-${M.id} como terminada`,
        mensaje: `Se fija ${M.fecha_lista ? 'su fecha de muestra lista (' + fmtFecha(M.fecha_lista) + ')' : 'hoy como fecha de muestra lista'} y pasa al histórico.`,
        textoConfirmar: 'Sí, terminada', conMotivo: true, placeholderMotivo: 'Apunte final para el diario (opcional)',
      });
      if (!r.ok) return;
      nota = r.motivo || '';
    } else if (TERMINALES.includes(M.estado) || (idxAct >= 0 && idxNuevo < idxAct)) {
      const r = await window.mostrarConfirmacion({
        titulo: TERMINALES.includes(M.estado) ? `Reabrir M-${M.id}` : `Volver a «${ESTADOS_LABEL[nuevo]}»`,
        mensaje: TERMINALES.includes(M.estado)
          ? `La muestra vuelve al seguimiento en «${ESTADOS_LABEL[nuevo]}»${M.estado === 'terminada' ? ' y se borra su fecha de muestra lista' : ''}.`
          : 'Retrocede una etapa. Si quieres, deja un apunte con el porqué.',
        textoConfirmar: 'Continuar', conMotivo: true, placeholderMotivo: 'Apunte para el diario (opcional)',
      });
      if (!r.ok) return;
      nota = r.motivo || '';
    }
    st.classList.add('saving');
    try {
      const d = await api(URL_API + '/estado', { method: 'POST', body: { estado: nuevo, nota } });
      M = d.muestra; pintarTodo();
    } catch (err) {
      st.classList.remove('saving');
      await window.mostrarAlerta({ titulo: 'No se pudo cambiar el estado', mensaje: err.message, tipo: 'danger' });
    }
  });

  async function cancelarMuestra() {
    const r = await window.mostrarConfirmacion({
      titulo: `Cancelar la muestra M-${M.id}`,
      mensaje: 'Pasa al histórico como cancelada. El motivo se guarda en el diario.',
      textoConfirmar: 'Cancelar muestra', tipo: 'danger', conMotivo: true, placeholderMotivo: 'Motivo (opcional)',
    });
    if (!r.ok) return;
    try {
      const d = await api(URL_API + '/estado', { method: 'POST', body: { estado: 'cancelada', nota: r.motivo || '' } });
      M = d.muestra; pintarTodo();
    } catch (e) {
      await window.mostrarAlerta({ titulo: 'No se pudo cancelar', mensaje: e.message, tipo: 'danger' });
    }
  }

  // ------------------------------------------------------------
  // Ficha con autoguardado
  // ------------------------------------------------------------
  function pintarFicha() {
    $('md-clientes').innerHTML = (CAT.clientes || []).map(x => `<option value="${esc(x)}"></option>`).join('');
    const esInterna = M.tipo === 'interna';
    $('md-f-tipo').value = esInterna ? 'interna' : 'cliente';
    $('md-f-cliente-lbl').textContent = esInterna ? 'Para quién / proyecto' : 'Cliente';
    $('md-f-cliente').placeholder = esInterna ? 'Ej. Marta · colección 2027' : 'Nombre del cliente';
    $('md-f-cliente').value = M.cliente || '';
    pintarNavLink();
    rellenarPersona();
    llenarSelect($('md-f-telar'), CAT.telares, { vacio: '—', otro: true, valor: M.telar || '' });
    $('md-f-prioridad').value = String(M.prioridad || 2);
    colorearPrio($('md-f-prioridad'));
    $('md-f-fecha').value = M.fecha_solicitud || '';
    $('md-f-lista').value = M.fecha_lista || '';
    $('md-f-hito-fecha').value = M.proximo_hito_fecha || '';
    $('md-f-hito-fecha').classList.toggle('vencido-campo', !!M.hito_vencido);
    $('md-f-hito').value = M.proximo_hito || '';
    $('md-f-desc').value = M.descripcion || '';
    $('md-f-resultado').value = M.resultado || '';
    const hayAnot = !!(M.anotacion_registro || '').trim();
    $('md-anotacion-wrap').hidden = !hayAnot;
    $('md-anotacion').textContent = M.anotacion_registro || '';
    const imp = M._import;
    let origen = '';
    if (imp) {
      origen = `Importada del Libro de muestras (Excel) · hoja «${esc(imp.hoja)}», fila ${imp.fila}`;
      if (imp.numero_raw) origen += ` · número tal como estaba escrito: «${esc(imp.numero_raw)}»`;
      if (imp.solo_registro) origen += ' · solo estaba en el registro de números (sin seguimiento)';
    } else if (M.creado_en) {
      origen = `Creada el ${fmtFechaHora(M.creado_en)}${(M.creado_por_nombre || M.creado_por) ? ' por ' + esc(M.creado_por_nombre || M.creado_por) : ''}`;
    }
    if (M.actualizado_en && !imp) origen += ` · última modificación ${fmtFechaHora(M.actualizado_en)}`;
    $('md-origen').innerHTML = origen;
  }

  function pintarNavLink() {
    $('md-nav-link').hidden = !M.cliente_navision;
    $('md-nav-no').textContent = M.cliente_navision || '';
  }

  // El cliente se escribe o se elige de Navision; al elegir se guarda el
  // nombre y el código; al editar el texto a mano se quita el vínculo.
  let clienteEditadoAMano = false;
  montarBuscadorCliente($('md-f-cliente'), {
    clientesUsados: () => (CAT && CAT.clientes) || [],
    onElegir: async (it) => {
      clienteEditadoAMano = false;
      const el = $('md-f-cliente');
      marcar(el, 'saving');
      try {
        const d = await api(URL_API, { method: 'PUT', body: { cliente: it.nombre, cliente_navision: it.no || '' } });
        M = d.muestra; marcar(el, 'saved-ok'); pintarHero(); pintarNavLink(); pintarHistorial();
      } catch (e) {
        marcar(el, 'saved-err');
        await window.mostrarAlerta({ titulo: 'No se pudo guardar', mensaje: e.message, tipo: 'danger' });
      }
    },
    onTexto: () => { clienteEditadoAMano = true; },
  });
  $('md-nav-quitar').addEventListener('click', async () => {
    try {
      const d = await api(URL_API, { method: 'PUT', body: { cliente_navision: '' } });
      M = d.muestra; pintarHero(); pintarNavLink(); pintarHistorial();
    } catch (e) {
      await window.mostrarAlerta({ titulo: 'No se pudo quitar el vínculo', mensaje: e.message, tipo: 'danger' });
    }
  });

  function rellenarPersona() {
    llenarSelectPersonas($('md-f-persona'), CAT.personas_activas,
      { vacio: '—', usuario: M.encargada_por_usuario || '', nombre: M.encargada_por || '' });
  }

  function marcar(el, cls) {
    el.classList.remove('saving', 'saved-ok', 'saved-err');
    if (cls) el.classList.add(cls);
    if (cls === 'saved-ok') setTimeout(() => el.classList.remove('saved-ok'), 1400);
  }

  async function guardarCampo(el) {
    const campo = el.dataset.campo;
    let valor = el.value;
    if (el.tagName === 'SELECT' && (valor === '__otro__' || valor === '__legacy__')) { marcar(el, null); return; }
    if (campo === 'encargada_por' && valor === (M.encargada_por_usuario || '')) { marcar(el, null); return; }
    if (campo === 'prioridad') valor = Number(valor);
    if (typeof valor === 'string') valor = valor.trim();
    const actual = M[campo] == null ? '' : M[campo];
    if (String(actual) === String(valor)) { marcar(el, null); return; }
    marcar(el, 'saving');
    const body = { [campo]: valor };
    if (campo === 'cliente' && clienteEditadoAMano && M.cliente_navision && valor !== (M.cliente || '')) body.cliente_navision = '';
    try {
      const d = await api(URL_API, { method: 'PUT', body });
      M = d.muestra;
      marcar(el, 'saved-ok');
      pintarHero(); pintarStepper(); pintarHistorial();
      if (campo === 'tipo') pintarFicha();
      if (campo === 'cliente') { clienteEditadoAMano = false; pintarNavLink(); }
      if (campo === 'cliente' || campo === 'encargada_por' || campo === 'telar') {
        // catálogos pueden haber crecido (valor nuevo)
        CAT = await api('/api/muestras/catalogos');
      }
    } catch (e) {
      marcar(el, 'saved-err');
      await window.mostrarAlerta({ titulo: 'No se pudo guardar', mensaje: e.message, tipo: 'danger' });
      if (campo === 'encargada_por') rellenarPersona();
      else el.value = (campo === 'prioridad') ? String(M.prioridad || 2) : (M[campo] || '');
      if (campo === 'prioridad') colorearPrio(el);
      marcar(el, null);
    }
  }
  document.querySelectorAll('[data-campo]').forEach(el => {
    if (el.tagName === 'SELECT') {
      el.addEventListener('change', async () => {
        if (el.value === '__otro__') {
          const tipo = el.dataset.campo === 'encargada_por' ? 'personas' : 'telares';
          const ok = await gestionarOtro(el, tipo, tipo === 'personas' ? 'nombre' : 'telar / técnica');
          if (!ok) { el.value = M[el.dataset.campo] || ''; return; }
        }
        if (el.dataset.campo === 'prioridad') colorearPrio(el);
        guardarCampo(el);
      });
    } else if (el.tagName === 'TEXTAREA') {
      el.addEventListener('blur', () => guardarCampo(el));
      el.addEventListener('keydown', (e) => { if (e.key === 'Enter' && e.ctrlKey) { e.preventDefault(); el.blur(); } });
    } else {
      el.addEventListener('change', () => guardarCampo(el));
    }
  });

  // ------------------------------------------------------------
  // Diario del laboratorio
  // ------------------------------------------------------------
  function pintarDiario() {
    const aps = M.apuntes || [];
    $('md-ap-count').textContent = fmtNum(aps.length);
    if (!$('md-ap-fecha').value) $('md-ap-fecha').value = hoyISO();
    if (!aps.length) {
      $('md-diario').innerHTML = '<div class="ms-ap-vacio">Todavía no hay apuntes. Cada envío a tintar, cada llegada de color, cada entrada a telar… aquí.</div>';
      return;
    }
    $('md-diario').innerHTML = aps.map(a => {
      const meta = [];
      if (a.editado_en) meta.push(`editado ${fmtFechaHora(a.editado_en)}${(a.editado_por_nombre || a.editado_por) ? ' por ' + esc(a.editado_por_nombre || a.editado_por) : ''}`);
      const autor = a.usuario_nombre || a.usuario || '';
      const quien = autor
        ? `<div class="ms-ap-quien" title="${esc(a.usuario || '')}">${esc(autor)}</div>`
        : '<div class="ms-ap-quien libro" title="Importado del Libro de muestras (Excel)">del libro</div>';
      return `<div class="ms-ap" data-aid="${esc(a.id)}">
        <div class="ms-ap-fecha ${a.fecha ? '' : 'sin'}">${a.fecha ? fmtFecha(a.fecha) : 'sin fecha'}${quien}</div>
        <div><div class="ms-ap-texto">${esc(a.texto)}</div>${meta.length ? `<div class="ms-ap-meta">${meta.join(' · ')}</div>` : ''}</div>
        <div class="ms-ap-acciones">
          <button type="button" class="ms-ico-btn" data-accion="editar" title="Editar el apunte">✎</button>
          <button type="button" class="ms-ico-btn danger" data-accion="borrar" title="Borrar el apunte">✕</button>
        </div>
      </div>`;
    }).join('');
  }

  async function anadirApunte() {
    const ta = $('md-ap-texto');
    const texto = ta.value.trim();
    if (!texto) { ta.focus(); return; }
    const btn = $('md-ap-add');
    btn.disabled = true;
    try {
      const d = await api(URL_API + '/apuntes', { method: 'POST', body: { texto, fecha: $('md-ap-fecha').value || undefined } });
      M = d.muestra;
      ta.value = '';
      pintarDiario(); pintarHero(); pintarHistorial();
      ta.focus();
    } catch (e) {
      await window.mostrarAlerta({ titulo: 'No se pudo añadir el apunte', mensaje: e.message, tipo: 'danger' });
    } finally {
      btn.disabled = false;
    }
  }
  $('md-ap-add').addEventListener('click', anadirApunte);
  $('md-ap-texto').addEventListener('keydown', (e) => { if (e.key === 'Enter' && e.ctrlKey) { e.preventDefault(); anadirApunte(); } });
  // El textarea crece con el texto
  $('md-ap-texto').addEventListener('input', function () { this.style.height = 'auto'; this.style.height = Math.min(220, this.scrollHeight) + 'px'; });

  $('md-diario').addEventListener('click', async (e) => {
    const b = e.target.closest('button[data-accion]');
    if (!b) return;
    const aid = b.closest('.ms-ap').dataset.aid;
    const ap = (M.apuntes || []).find(a => a.id === aid);
    if (!ap) return;
    if (b.dataset.accion === 'borrar') {
      const r = await window.mostrarConfirmacion({ titulo: 'Borrar apunte', mensaje: `«${ap.texto.slice(0, 120)}${ap.texto.length > 120 ? '…' : ''}»`, textoConfirmar: 'Borrar', tipo: 'danger' });
      if (!r.ok) return;
      try {
        const d = await api(`${URL_API}/apuntes/${encodeURIComponent(aid)}`, { method: 'DELETE' });
        M = d.muestra; pintarDiario(); pintarHero(); pintarHistorial();
      } catch (err) {
        await window.mostrarAlerta({ titulo: 'No se pudo borrar', mensaje: err.message, tipo: 'danger' });
      }
      return;
    }
    // Editar: texto (y fecha si no la tenía o quiere cambiarla)
    const r = await window.mostrarPrompt({ titulo: `Editar apunte${ap.fecha ? ' del ' + fmtFecha(ap.fecha) : ''}`, etiqueta: 'Texto', multilinea: true, valorDefecto: ap.texto, textoConfirmar: 'Guardar', validador: v => (!v ? 'El apunte no puede quedar vacío' : '') });
    if (!r.ok) return;
    const body = { texto: r.valor };
    if (!ap.fecha) {
      const f = await window.mostrarPrompt({ titulo: 'Fecha del apunte', mensaje: 'Este apunte no tenía fecha. Escríbela (AAAA-MM-DD) o déjala vacía.', etiqueta: 'Fecha', valorDefecto: '', tipoInput: 'date', textoConfirmar: 'Guardar' });
      if (f.ok && f.valor) body.fecha = f.valor;
    }
    try {
      const d = await api(`${URL_API}/apuntes/${encodeURIComponent(aid)}`, { method: 'PUT', body });
      M = d.muestra; pintarDiario(); pintarHero();
    } catch (err) {
      await window.mostrarAlerta({ titulo: 'No se pudo guardar', mensaje: err.message, tipo: 'danger' });
    }
  });

  // ------------------------------------------------------------
  // Variantes e historial
  // ------------------------------------------------------------
  function pintarVariantes() {
    const vs = M.variantes || [];
    $('md-variantes-wrap').hidden = !vs.length;
    $('md-var-count').textContent = fmtNum(vs.length);
    $('md-variantes').innerHTML = vs.map(v => `<a class="ms-variante" href="/muestras-fabricadas/${encodeURIComponent(v.id)}">
        <span class="ms-num"><span class="pre">M-</span>${esc(v.id)}</span>
        ${estadoPill(v.estado, v.estado_label)}
        <span class="d" title="${esc(v.descripcion)}">${esc(v.cliente)}${v.descripcion ? ' · ' + esc(v.descripcion) : ''}</span>
        <span class="ms-fecha ms-mudo">${fmtFecha(v.fecha_solicitud, false)}</span>
      </a>`).join('');
  }

  function textoHistorial(h) {
    const t = h.tipo;
    if (t === 'creacion') return h.texto || 'Alta de la muestra';
    if (t === 'estado') return `Estado: ${esc(ESTADOS_LABEL[h.de] || h.de || '—')} → <b>${esc(ESTADOS_LABEL[h.a] || h.a)}</b>${h.nota ? ' · «' + esc(h.nota) + '»' : ''}`;
    if (t === 'campo') {
      const nombres = { cliente: 'Cliente', descripcion: 'Descripción', encargada_por: 'Encargada por', prioridad: 'Prioridad', telar: 'Telar', fecha_solicitud: 'Fecha de solicitud', fecha_lista: 'Fecha muestra lista', resultado: 'Resultado', anotacion_registro: 'Anotación', tipo: 'Tipo', cliente_navision: 'Cliente Navision', proximo_hito_fecha: 'Próximo hito', proximo_hito: 'Qué se espera en el hito' };
      return `${esc(nombres[h.campo] || h.campo)}: «${esc(h.de || '—')}» → «${esc(h.a || '—')}»`;
    }
    if (t === 'archivo') return h.a === 'archivada' ? 'Archivada (fuera de En curso)' : 'Devuelta a En curso';
    if (t === 'apunte_borrado') return `Apunte borrado${h.fecha_apunte ? ' (' + fmtFecha(h.fecha_apunte) + ')' : ''}: «${esc(h.texto || '')}»`;
    if (t === 'importacion') return esc(h.texto || 'Importada del Libro de muestras');
    return esc(h.texto || t);
  }

  function pintarHistorial() {
    const hs = (M.historial || []).slice().reverse();
    $('md-hist-count').textContent = fmtNum(hs.length);
    $('md-historial').innerHTML = hs.length
      ? hs.map(h => `<li><span class="f">${fmtFechaHora(h.fecha)}</span>${(h.usuario_nombre || h.usuario) ? `<span class="f">${esc(h.usuario_nombre || h.usuario)}</span>` : ''}${textoHistorial(h)}</li>`).join('')
      : '<li class="ms-mudo">Sin cambios registrados.</li>';
  }

  cargar();
})();
