// ============================================================
// Muestras fabricadas — helpers comunes al listado y a la ficha.
// ============================================================
(function () {
  'use strict';

  const ESTADOS = [
    ['por_empezar', 'Por empezar'], ['en_diseno', 'En diseño'], ['en_hilatura', 'En hilatura'],
    ['en_tintoreria', 'En tintorería'], ['bobinando', 'Bobinando'], ['esperando_telar', 'Esperando a telar'],
    ['en_telar', 'En telar'], ['en_aprestos', 'En aprestos'], ['terminada', 'Terminada'],
    ['cancelada', 'Cancelada'], ['sin_seguimiento', 'Sin seguimiento'],
  ];
  const ESTADOS_LABEL = Object.fromEntries(ESTADOS);
  const ESTADOS_FLUJO = ESTADOS.slice(0, 9).map(e => e[0]);
  const PRIO_LABEL = { 1: 'Alta', 2: 'Media', 3: 'Baja' };

  function esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  function fmtFecha(iso, conAnio4) {
    if (!iso) return '';
    const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso);
    if (!m) return iso;
    return `${m[3]}/${m[2]}/${conAnio4 === false ? m[1].slice(2) : m[1]}`;
  }

  function fmtFechaHora(iso) {
    if (!iso) return '';
    const m = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/.exec(iso);
    if (!m) return fmtFecha(iso);
    return `${m[3]}/${m[2]}/${m[1]} ${m[4]}:${m[5]}`;
  }

  function hoyISO() {
    const d = new Date();
    const p = n => String(n).padStart(2, '0');
    return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
  }

  function fmtNum(n) {
    return Number(n || 0).toLocaleString('es-ES', { useGrouping: 'always' });
  }

  function numeroHtml(m) {
    // "M-5448-C": el prefijo en gris, el número en negrita; los ids raros
    // del libro antiguo (P.6776, PED.-7185) se enseñan tal cual.
    const id = m.id || '';
    const badge = (m.n_variantes || 0) > 1
      ? `<span class="var" title="${m.n_variantes} muestras con el número ${esc(m.numero)}">+${m.n_variantes - 1}</span>` : '';
    return `<span class="ms-num"><span class="pre">M-</span>${esc(id)}${badge}</span>`;
  }

  function estadoPill(slug, label) {
    const s = slug || '';
    return `<span class="ms-estado ms-estado-${esc(s || 'sin_seguimiento')}">${esc(label || ESTADOS_LABEL[s] || '—')}</span>`;
  }

  function prioPill(p) {
    const v = [1, 2, 3].includes(Number(p)) ? Number(p) : 0;
    return `<span class="ms-prio ms-prio-${v}">${v ? esc(PRIO_LABEL[v]) : '—'}</span>`;
  }

  // Etiqueta "Interna" (desarrollo propio) delante del cliente.
  function tipoTag(m) {
    return (m && m.tipo === 'interna')
      ? '<span class="ms-tag-interna" title="Muestra interna (desarrollo propio, no de un cliente)">Interna</span>' : '';
  }
  function clienteHtml(m) {
    const tag = tipoTag(m);
    const txt = esc((m && m.cliente) || '');
    if (!txt) return tag || '<span class="ms-mudo">—</span>';
    return tag + txt;
  }

  // El <select> de prioridad toma el color de su pill (1 rojo, 2 azul, 3 verde).
  function colorearPrio(sel) {
    if (!sel) return;
    sel.classList.remove('ms-prio-sel-0', 'ms-prio-sel-1', 'ms-prio-sel-2', 'ms-prio-sel-3');
    sel.classList.add('ms-prio-sel', 'ms-prio-sel-' + (['1', '2', '3'].includes(String(sel.value)) ? sel.value : '0'));
  }

  async function api(url, opts) {
    const init = Object.assign({ headers: {} }, opts || {});
    if (init.body && typeof init.body !== 'string') {
      init.body = JSON.stringify(init.body);
      init.headers['Content-Type'] = 'application/json';
    }
    const r = await fetch(url, init);
    let data = null;
    try { data = await r.json(); } catch (e) { data = null; }
    if (!r.ok) {
      const msg = (data && data.error) || `Error ${r.status}`;
      const err = new Error(msg);
      err.status = r.status;
      throw err;
    }
    return data;
  }

  function pintarUserChip(u) {
    const chip = document.getElementById('ms-user-chip');
    if (!chip || !u) return;
    const nombre = (u.nombre || u.username || '').trim();
    if (!nombre) return;
    document.getElementById('ms-user-nombre').textContent = nombre;
    document.getElementById('ms-user-avatar').textContent = nombre[0].toUpperCase();
    chip.style.display = '';
    // Enlaces del sidebar que exigen otro permiso (compras): se ocultan si
    // el usuario no lo tiene (p.ej. laboratorio solo con muestras).
    const perms = u.permisos || {};
    document.querySelectorAll('[data-permiso]').forEach(el => {
      const p = el.getAttribute('data-permiso');
      if (perms[p] !== undefined && !perms[p]) el.style.display = 'none';
    });
  }
  if (window.__rolsUser) pintarUserChip(window.__rolsUser);
  window.addEventListener('rols:sso-ok', (e) => pintarUserChip(e.detail));

  function esAdmin() {
    return !!(window.__rolsUser && window.__rolsUser.rol === 'admin');
  }

  // Rellena un <select> con opciones (value=label) + opción "Otro…" opcional.
  function llenarSelect(sel, valores, opts) {
    const o = opts || {};
    const actual = o.valor !== undefined ? o.valor : sel.value;
    sel.innerHTML = '';
    if (o.vacio !== undefined) sel.insertAdjacentHTML('beforeend', `<option value="">${esc(o.vacio)}</option>`);
    (valores || []).forEach(v => sel.insertAdjacentHTML('beforeend', `<option value="${esc(v)}">${esc(v)}</option>`));
    if (actual && ![...sel.options].some(op => op.value === actual)) {
      sel.insertAdjacentHTML('beforeend', `<option value="${esc(actual)}">${esc(actual)}</option>`);
    }
    if (o.otro) sel.insertAdjacentHTML('beforeend', `<option value="__otro__">Otro…</option>`);
    sel.value = actual || '';
  }

  // Select de "encargada por": solo usuarios de One (value = usuario, texto = nombre).
  // Si la muestra lleva un nombre antiguo sin usuario, se añade como opción
  // "(antiguo)" para que se vea, pero no se puede elegir para otras.
  function llenarSelectPersonas(sel, activas, opts) {
    const o = opts || {};
    const lista = activas || [];
    const usuarioSel = (o.usuario || '').toLowerCase();
    sel.innerHTML = '';
    if (o.vacio !== undefined) sel.insertAdjacentHTML('beforeend', `<option value="">${esc(o.vacio)}</option>`);
    lista.forEach(p => sel.insertAdjacentHTML('beforeend', `<option value="${esc(p.usuario)}">${esc(p.nombre)}</option>`));
    let valor = '';
    const hit = usuarioSel ? lista.find(p => (p.usuario || '').toLowerCase() === usuarioSel) : null;
    if (hit) {
      valor = hit.usuario;
    } else if (usuarioSel && o.nombre) {
      // usuario de One que hoy no tiene acceso a muestras: se enseña igual
      sel.insertAdjacentHTML('beforeend', `<option value="${esc(o.usuario)}">${esc(o.nombre)} (sin acceso a muestras)</option>`);
      valor = o.usuario;
    } else if (o.nombre) {
      sel.insertAdjacentHTML('beforeend', `<option value="__legacy__">${esc(o.nombre)} (antiguo)</option>`);
      valor = '__legacy__';
    }
    sel.value = valor;
  }

  // Al elegir "Otro…" en un select de catálogo: pide el valor, lo guarda y lo selecciona.
  async function gestionarOtro(sel, tipo, etiqueta) {
    if (sel.value !== '__otro__') return true;
    const r = await window.mostrarPrompt({ titulo: `Nuevo ${etiqueta}`, etiqueta: etiqueta, placeholder: '…',
      validador: v => (!v ? 'Escribe un valor' : '') });
    if (!r.ok) { sel.value = ''; return false; }
    try {
      const data = await api(`/api/muestras/catalogos/${tipo}`, { method: 'POST', body: { valor: r.valor } });
      llenarSelect(sel, data[tipo], { valor: r.valor, otro: true, vacio: sel.dataset.vacio });
      return true;
    } catch (e) {
      await window.mostrarAlerta({ titulo: 'No se pudo guardar', mensaje: e.message, tipo: 'danger' });
      sel.value = '';
      return false;
    }
  }

  window.MS = { ESTADOS, ESTADOS_LABEL, ESTADOS_FLUJO, PRIO_LABEL, esc, fmtFecha, fmtFechaHora, hoyISO, fmtNum,
    numeroHtml, estadoPill, prioPill, tipoTag, clienteHtml, colorearPrio, api, esAdmin, llenarSelect, llenarSelectPersonas, gestionarOtro };
})();
