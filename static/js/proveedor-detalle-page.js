let _PROV = null;  // proveedor actual cacheado

function currentUsuario() {
  try { return (window.__rolsUser && window.__rolsUser.username) || ''; }
  catch (_) { return ''; }
}
function escapeHtml(s) {
  return String(s == null ? '' : s).replace(/[&<>"']/g, c =>
    ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}
function fmtNum(n, dec = 0) {
  if (n == null || isNaN(n)) return '—';
  return Number(n).toLocaleString('es-ES', {
    minimumFractionDigits: dec, maximumFractionDigits: dec, useGrouping: 'always',
  });
}
function fmtKg(n)  { return n == null || isNaN(n) ? '—' : fmtNum(n, 0) + ' kg'; }
function fmtEur(n) { return n == null || isNaN(n) ? '—' : fmtNum(n, 2) + ' €/kg'; }
function fmtImporte(n) { return n == null || isNaN(n) ? '—' : fmtNum(n, 2) + ' €'; }
function fmtFecha(s) {
  if (!s) return '—';
  const d = new Date(s);
  if (isNaN(d.getTime())) return s;
  return d.toLocaleDateString('es-ES');
}

async function cargar() {
  try {
    const r = await fetch(`/api/proveedor/${encodeURIComponent(PROV_ID)}/detalle`);
    if (r.status === 404) {
      document.querySelector('main').innerHTML =
        '<div class="pv-empty" style="margin-top:3rem">Proveedor no encontrado.</div>';
      return;
    }
    const d = await r.json();
    if (!r.ok) throw new Error(d.error || 'HTTP ' + r.status);
    _PROV = d.proveedor;
    pintarHero(d);
    pintarKpis(d);
    pintarPedidosAbiertos(d.pedidos_abiertos || []);
    pintarPedidosRecientes(d.pedidos_recientes || []);
    pintarCalidades(d.variantes || []);
    pintarFicha(d.proveedor);
  } catch (err) {
    await mostrarAlerta({titulo: 'Error', mensaje: err.message, tipo: 'danger'});
  }
}

function pintarHero(d) {
  const p = d.proveedor;
  const alias = (p.alias || p.nombre || '').trim();
  const nombre = (p.nombre || '').trim();
  // H1: ALIAS  nombre comercial (si distinto)  CHIP
  // Sin alias ni nombre aun (ficha recien creada), mostramos el identificador
  // interno (PROV_ID) en vez de un guion: que siempre se sepa QUIEN es.
  document.getElementById('pv-alias').textContent = alias || PROV_ID;
  document.getElementById('pv-nombre').textContent =
    (nombre && nombre.toUpperCase() !== alias.toUpperCase()) ? nombre : '';
  document.getElementById('pv-bread-alias').textContent = alias || PROV_ID;
  document.title = `${alias || PROV_ID} — Proveedor — Rols ERP Producción`;
  // Subtitle: contacto + telefono o email si los hay
  const partes = [];
  if (p.contacto_persona) partes.push(p.contacto_persona);
  if (p.contacto_email)   partes.push(p.contacto_email);
  if (p.contacto_telefono) partes.push(p.contacto_telefono);
  document.getElementById('pv-hero-sub').textContent =
    partes.length ? partes.join(' · ') : 'Sin datos de contacto todavía';
  // Estado chip
  const chip = document.getElementById('pv-estado');
  if (p.activo) {
    chip.className = 'pv-chip-estado pv-chip-activo';
    chip.textContent = 'Activo';
    document.getElementById('pv-btn-toggle').textContent = 'Desactivar';
  } else {
    chip.className = 'pv-chip-estado pv-chip-inactivo';
    chip.textContent = 'Inactivo';
    document.getElementById('pv-btn-toggle').textContent = 'Reactivar';
  }
  // Boton borrar: deshabilitado si hay calidades vinculadas
  const btnBorrar = document.getElementById('pv-btn-borrar');
  const nCal = (d.kpis && d.kpis.n_calidades) || 0;
  btnBorrar.disabled = nCal > 0;
  btnBorrar.title = nCal > 0
    ? `Tiene ${nCal} calidad(es) vinculadas — desactívalo en lugar de borrarlo`
    : 'Borrar definitivamente este proveedor';
}

function pintarKpis(d) {
  const k = d.kpis || {};
  document.getElementById('pv-kpi-calidades').textContent = k.n_calidades || 0;
  document.getElementById('pv-kpi-stock').textContent = fmtKg(k.stock_total_kg || 0);
  document.getElementById('pv-kpi-pedidos').textContent =
    (k.n_pedidos_abiertos || 0) + ' ' + ((k.n_pedidos_abiertos || 0) === 1 ? 'pedido' : 'pedidos');
  const plazo = d.proveedor && d.proveedor.plazo_entrega_dias;
  document.getElementById('pv-kpi-plazo').textContent = plazo
    ? `${plazo} día${plazo === 1 ? '' : 's'}`
    : '—';
}

function pintarPedidosAbiertos(peds) {
  document.getElementById('pv-ab-count').textContent = peds.length;
  const tb = document.getElementById('pv-ab-tbody');
  if (!peds.length) {
    tb.innerHTML = '<tr><td colspan="9" class="pv-empty">No hay pedidos en camino con este proveedor.</td></tr>';
    return;
  }
  tb.innerHTML = peds.map(p => `
    <tr>
      <td><strong>${escapeHtml(p.ref || '—')}</strong></td>
      <td>
        <a href="/materia-prima/${encodeURIComponent(p.calidad_id || '')}"
           class="pv-link" title="Abrir ficha de la materia prima">
          ${escapeHtml(p.calidad_nombre || '—')}
        </a>
      </td>
      <td class="num"><strong>${fmtKg(p.kg)}</strong></td>
      <td class="num">${p.eur_kg != null ? fmtEur(p.eur_kg) : '—'}</td>
      <td class="num">${fmtImporte(p.importe)}</td>
      <td>${escapeHtml(p.partido_previsto || '—')}</td>
      <td>${fmtFecha(p.fecha)}</td>
      <td>${p.fecha_estimada
            ? `<span style="color:#1e40af">${fmtFecha(p.fecha_estimada)}</span>`
            : '—'}</td>
      <td><span class="ped-chip ped-chip-abierto">🚚 EN CAMINO</span></td>
    </tr>
  `).join('');
}

function pintarPedidosRecientes(peds) {
  // Solo mostramos pedidos cuya mercancia ya esta fisicamente en el
  // almacen Rols. Los anulados se filtran fuera; siguen registrados
  // en el historico de movimientos para auditoria.
  const recibidos = (peds || []).filter(p => p.estado === 'recibido');
  document.getElementById('pv-rec-count').textContent = recibidos.length;
  const tb = document.getElementById('pv-rec-tbody');
  if (!recibidos.length) {
    tb.innerHTML = '<tr><td colspan="8" class="pv-empty">Sin pedidos recibidos todavía.</td></tr>';
    return;
  }
  tb.innerHTML = recibidos.map(p => `
    <tr>
      <td><strong>${escapeHtml(p.ref || '—')}</strong></td>
      <td>
        <a href="/materia-prima/${encodeURIComponent(p.calidad_id || '')}"
           class="pv-link" title="Abrir ficha de la materia prima">
          ${escapeHtml(p.calidad_nombre || '—')}
        </a>
      </td>
      <td class="num">${fmtKg(p.kg)}</td>
      <td class="num">${p.eur_kg != null ? fmtEur(p.eur_kg) : '—'}</td>
      <td>${escapeHtml(p.partido_previsto || '—')}</td>
      <td>${fmtFecha(p.fecha)}</td>
      <td>${fmtFecha(p.fecha_recibido)}</td>
      <td><span class="ped-chip ped-chip-recibido">✓ En almacén</span></td>
    </tr>`).join('');
}

// Cache de variantes para que el handler de expansion pueda acceder al historico
let _pvVariantesCache = [];

function pintarCalidades(variantes) {
  _pvVariantesCache = variantes || [];
  document.getElementById('pv-cal-count').textContent = variantes.length;
  const tb = document.getElementById('pv-cal-tbody');
  if (!variantes.length) {
    tb.innerHTML = `<tr><td colspan="7" class="pv-empty">
      Sin calidades vinculadas todavía. Para añadir, ve a la ficha de la materia prima y usa "+ Añadir proveedor".
    </td></tr>`;
    return;
  }
  tb.innerHTML = variantes.map(v => {
    const precio = v.precio_actual;
    const fecha = v.fecha_precio_actual || '';
    const dEur = v.delta_precio_eur;
    const dPct = v.delta_precio_pct;
    let deltaCell = '<span style="color:#9a9a9a">—</span>';
    if (dEur != null && dPct != null) {
      const sube = dEur > 0;
      const baja = dEur < 0;
      const col = sube ? '#9b1c1c' : (baja ? '#2f6b29' : '#7a7a7a');
      const sig = sube ? '+' : (baja ? '−' : '');
      deltaCell = `<span style="color:${col}; font-weight:600">${sig}${fmtEur(Math.abs(dEur))} (${sig}${Math.abs(dPct).toFixed(1)}%)</span>`;
    }
    // Tarifa editable: input numerico + fecha debajo. Si la fuente NO es
    // manual (viene de precio_2026/precio_2025 legacy), mostramos hint.
    const tarifaVal = v.tarifa_eur_kg;
    const tarifaInput = tarifaVal != null
      ? Number(tarifaVal).toLocaleString('es-ES', { minimumFractionDigits: 2, maximumFractionDigits: 4 })
      : '';
    const tarifaFecha = v.tarifa_fecha || '';
    const tarifaFuente = v.tarifa_fuente || 'manual';
    const tarifaHint = tarifaFecha
      ? `<small style="display:block; color:#9a9a9a; font-size:0.7rem; margin-top:0.1rem">${escapeHtml(tarifaFecha)}</small>`
      : (tarifaFuente !== 'manual' && tarifaVal != null
          ? `<small style="display:block; color:#9a9a9a; font-style:italic; font-size:0.7rem; margin-top:0.1rem">desde ${escapeHtml(tarifaFuente)}</small>`
          : '<small style="display:block; color:#c0c0c0; font-size:0.7rem; margin-top:0.1rem">sin fecha</small>');

    const nRefs = (v.historico_precios || []).length;
    return `
    <tr class="pv-cal-row pv-cal-row-expandable" data-vid="${escapeHtml(v.id)}">
      <td>
        <span class="pv-cal-caret">▸</span>
        <strong>${escapeHtml(v.nombre || v.id)}</strong>
        ${nRefs > 1 ? `<span class="pv-cal-histcount" title="${nRefs} entradas de precio">${nRefs}</span>` : ''}
      </td>
      <td class="num">${fmtKg(v.total_kg)}</td>
      <td class="num" onclick="event.stopPropagation()">
        <input type="number" step="0.01" min="0"
               class="pv-tarifa-input"
               data-vid="${escapeHtml(v.id)}"
               value="${tarifaVal != null ? tarifaVal : ''}"
               placeholder="—"
               title="Precio tarifa €/kg (editable). Se sugiere al hacer un pedido nuevo." />
        ${tarifaHint}
      </td>
      <td class="num"><strong>${precio != null ? fmtEur(precio) : '—'}</strong></td>
      <td class="num">${deltaCell}</td>
      <td>${escapeHtml(fecha || '—')}</td>
      <td style="text-align:right">
        <a href="/materia-prima/${encodeURIComponent(v.calidad_id)}"
           class="pv-link" title="Abrir ficha de la materia prima"
           onclick="event.stopPropagation()">
          Abrir →
        </a>
      </td>
    </tr>`;
  }).join('');
}

// Guardar la tarifa al perder el foco. Reusa el endpoint de campo de
// lana_inventario (PUT /api/lanas-inventario/<vid>/campo).
document.getElementById('pv-cal-tbody')?.addEventListener('change', async (e) => {
  const inp = e.target.closest('input.pv-tarifa-input');
  if (!inp) return;
  const vid = inp.dataset.vid;
  const valor = inp.value.trim();
  inp.disabled = true;
  inp.classList.remove('saved-ok', 'saved-err');
  inp.classList.add('saving');
  try {
    const r = await fetch(`/api/lanas-inventario/${encodeURIComponent(vid)}/campo`, {
      method: 'PUT',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({campo: 'tarifa_actual_eur_kg', valor: valor || null}),
    });
    const d = await r.json();
    if (!r.ok) throw new Error(d.error || 'HTTP ' + r.status);
    inp.classList.remove('saving');
    inp.classList.add('saved-ok');
    setTimeout(() => inp.classList.remove('saved-ok'), 800);
    // Actualizar cache local + fecha visible debajo del input
    const cache = _pvVariantesCache.find(v => v.id === vid);
    if (cache) {
      cache.tarifa_eur_kg = valor ? Number(valor) : null;
      cache.tarifa_fecha = valor ? new Date().toISOString().slice(0, 10) : null;
      cache.tarifa_fuente = 'manual';
      // Repintar la hint debajo
      const small = inp.parentElement.querySelector('small');
      if (small) {
        small.textContent = cache.tarifa_fecha || 'sin fecha';
        small.style.color = '#9a9a9a';
        small.style.fontStyle = 'normal';
      }
    }
  } catch (err) {
    inp.classList.remove('saving');
    inp.classList.add('saved-err');
    alert('No se pudo guardar la tarifa: ' + err.message);
  } finally {
    inp.disabled = false;
  }
});

// Click en una fila de calidad: expande/colapsa el historico de precios
document.getElementById('pv-cal-tbody')?.addEventListener('click', (e) => {
  const tr = e.target.closest('tr.pv-cal-row-expandable');
  if (!tr) return;
  // Si el click viene de un link (Abrir ficha), no interceptar
  if (e.target.closest('a')) return;
  const vid = tr.dataset.vid;
  const v = _pvVariantesCache.find(x => x.id === vid);
  if (!v) return;
  // Colapsar si ya esta expandido
  const next = tr.nextElementSibling;
  if (next && next.classList.contains('pv-cal-detail-row') && next.dataset.vid === vid) {
    next.remove();
    tr.classList.remove('pv-cal-row-expanded');
    return;
  }
  tr.classList.add('pv-cal-row-expanded');
  const detail = document.createElement('tr');
  detail.className = 'pv-cal-detail-row';
  detail.dataset.vid = vid;
  const hist = v.historico_precios || [];
  let body;
  if (!hist.length) {
    body = '<div style="color:#9a9a9a; font-style:italic; padding:0.4rem">Sin histórico de precios todavía. Aparecerá cuando se reciban partidos con coste definido.</div>';
  } else {
    body = `
      <table class="pv-cal-detail-tabla">
        <thead>
          <tr>
            <th>Fecha</th>
            <th>Partido</th>
            <th class="num">Cantidad</th>
            <th class="num">€/kg</th>
            <th class="num">Δ vs anterior</th>
          </tr>
        </thead>
        <tbody>${hist.map(h => {
          const dE = h.delta_eur;
          const dP = h.delta_pct;
          let dCell = '<span style="color:#9a9a9a">—</span>';
          if (dE != null && dP != null) {
            const col = dE > 0 ? '#9b1c1c' : (dE < 0 ? '#2f6b29' : '#7a7a7a');
            const sig = dE > 0 ? '+' : (dE < 0 ? '−' : '');
            dCell = `<span style="color:${col}">${sig}${fmtEur(Math.abs(dE))} (${sig}${Math.abs(dP).toFixed(1)}%)</span>`;
          }
          return `
            <tr>
              <td style="white-space:nowrap; font-size:0.8rem; color:#4d4d4d">${escapeHtml(h.fecha || '—')}</td>
              <td><strong>${escapeHtml(h.partido || '—')}</strong></td>
              <td class="num">${fmtKg(h.kg_inicial)}</td>
              <td class="num"><strong>${fmtEur(h.coste_kg)}</strong></td>
              <td class="num">${dCell}</td>
            </tr>`;
        }).join('')}</tbody>
      </table>`;
  }
  detail.innerHTML = `<td colspan="7">
    <div class="pv-cal-detail-inner">
      <div class="pv-cal-detail-titulo">Histórico de precios — ${escapeHtml(v.nombre || v.id)}</div>
      ${body}
    </div>
  </td>`;
  tr.parentNode.insertBefore(detail, tr.nextSibling);
});

// Ficha editable — los campos guardan onBlur con PUT /api/proveedor/<id>
function pintarFicha(p) {
  const campo = (label, key, type='text', extra='') => {
    const val = (p[key] != null ? String(p[key]) : '');
    return `<div class="pv-campo">
       <label>${escapeHtml(label)}</label>
       <input type="${type}" data-prov-campo="${escapeHtml(key)}"
              value="${escapeHtml(val)}" ${extra} />
     </div>`;
  };
  const grid = document.getElementById('pv-ficha-grid');
  grid.innerHTML = `
    <div class="pv-bloque">
      <h4>Identificador</h4>
      ${campo('Alias interno', 'alias', 'text', 'placeholder="Nombre corto que aparece en tablas"')}
      ${campo('Nombre comercial', 'nombre')}
      ${campo('Razón social', 'razon_social')}
      ${campo('CIF / NIF', 'cif')}
    </div>
    <div class="pv-bloque">
      <h4>Dirección</h4>
      ${campo('Dirección', 'direccion')}
      ${campo('CP', 'cp')}
      ${campo('Ciudad', 'ciudad')}
      ${campo('Provincia', 'provincia')}
      ${campo('País', 'pais')}
    </div>
    <div class="pv-bloque">
      <h4>Contacto</h4>
      ${campo('Persona', 'contacto_persona')}
      ${campo('Email', 'contacto_email', 'email')}
      ${campo('Teléfono', 'contacto_telefono')}
    </div>
    <div class="pv-bloque">
      <h4>Comercial</h4>
      ${campo('Plazo de entrega (días)', 'plazo_entrega_dias', 'number')}
      ${campo('Pedido mínimo (kg)', 'pedido_minimo_kg', 'number')}
      ${campo('Pedido mínimo (€)', 'pedido_minimo_eur', 'number')}
    </div>
    <div class="pv-bloque">
      <h4>Pago y portes</h4>
      ${campo('Condiciones de pago', 'condiciones_pago')}
      ${campo('Portes', 'portes')}
    </div>
    <div class="pv-bloque">
      <h4>Notas internas</h4>
      <div class="pv-campo">
        <label>Comentarios (solo internos)</label>
        <textarea data-prov-campo="notas" placeholder="Notas para el equipo">${escapeHtml(p.notas || '')}</textarea>
      </div>
    </div>`;
}

// Guardado inline en blur de cualquier campo de la ficha
document.addEventListener('blur', async (e) => {
  const el = e.target;
  if (!el || !el.dataset || !el.dataset.provCampo) return;
  const campo = el.dataset.provCampo;
  let valor = (el.value != null ? el.value : '').trim();
  // Numericos: convertir a number (o null si vacio)
  if (el.type === 'number') {
    valor = valor === '' ? null : Number(valor);
    if (valor != null && isNaN(valor)) return;
  }
  el.classList.remove('saved-ok');
  el.classList.add('saving');
  try {
    const r = await fetch(`/api/proveedor/${encodeURIComponent(PROV_ID)}`, {
      method: 'PUT',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({[campo]: valor}),
    });
    const d = await r.json();
    if (!r.ok) throw new Error(d.error || 'HTTP ' + r.status);
    el.classList.remove('saving');
    el.classList.add('saved-ok');
    setTimeout(() => el.classList.remove('saved-ok'), 700);
    // Si cambio el alias o el nombre, actualizar el H1
    if (campo === 'alias' || campo === 'nombre') {
      if (d.proveedor) {
        _PROV = d.proveedor;
        pintarHero({proveedor: d.proveedor, kpis: {n_calidades: 0}});
        // Recargar para coger los kpis frescos (el alias afecta al matcheo)
        cargar();
      }
    }
  } catch (err) {
    el.classList.remove('saving');
    await mostrarAlerta({titulo: 'Error guardando ' + campo,
                         mensaje: err.message, tipo: 'danger'});
  }
}, true);

// Toggle activo/inactivo
document.getElementById('pv-btn-toggle').addEventListener('click', async () => {
  if (!_PROV) return;
  try {
    const r = await fetch(`/api/proveedor/${encodeURIComponent(PROV_ID)}`, {
      method: 'PUT',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({activo: !_PROV.activo}),
    });
    const d = await r.json();
    if (!r.ok) throw new Error(d.error || 'HTTP ' + r.status);
    cargar();
  } catch (err) {
    await mostrarAlerta({titulo: 'Error', mensaje: err.message, tipo: 'danger'});
  }
});

// Borrar (solo si no tiene calidades vinculadas)
document.getElementById('pv-btn-borrar').addEventListener('click', async () => {
  if (!_PROV) return;
  const { ok } = await mostrarConfirmacion({
    titulo: 'Borrar proveedor',
    mensaje: `Se borrará la ficha del proveedor "${_PROV.alias || _PROV.nombre}". ` +
             `Esta acción es definitiva.`,
    textoConfirmar: 'Borrar definitivamente',
    tipo: 'danger',
  });
  if (!ok) return;
  try {
    const r = await fetch(`/api/proveedor/${encodeURIComponent(PROV_ID)}`, {method: 'DELETE'});
    const d = await r.json();
    if (!r.ok) throw new Error(d.error || 'HTTP ' + r.status);
    window.location.href = '/materias-primas#proveedores';
  } catch (err) {
    await mostrarAlerta({titulo: 'No se pudo borrar', mensaje: err.message, tipo: 'danger'});
  }
});

cargar();
