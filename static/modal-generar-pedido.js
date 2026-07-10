/* ===========================================================================
   Modal "Generar pedido a proveedor" — compartido entre el listado de
   Materias primas (tab Compras) y la ficha individual de materia prima.

   Antes habia DOS implementaciones casi identicas, una en cada plantilla
   (~400 LOC cada una). Cualquier bug/feature habia que copiarla. Ahora
   este modulo es la unica fuente.

   API:
     window.abrirModalPedidoGenerar({
       variantes,        // [{id, proveedor, nombre, kg_a_pedir,
                         //   precio_2026, precio_2025}, ...]
       onCreated,        // callback(refPedido, fullResponse) tras success
       onClose,          // callback() opcional al cerrar el modal
       modalCardOpts,    // {minWidth, maxWidth} opcionales
     });

   Requiere ui-modales.css (tiene los estilos del modal generico).
   Reutiliza CSS de las clases .ped-modal-card, .ped-prov-grupo, etc.
   que ya estan definidos en materias-primas.css y/o materia-prima-detalle.css.
   =========================================================================== */
(function () {
  if (window.__mgpReady) return;
  window.__mgpReady = true;

  const MODAL_ID = 'mgp-modal';

  function _escapeHtml(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, c =>
      ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  }
  function _fmtNum(n, dec = 0) {
    if (n == null || isNaN(n)) return '';
    return Number(n).toLocaleString('es-ES', {
      minimumFractionDigits: dec, maximumFractionDigits: dec,
      useGrouping: 'always',
    });
  }

  // Inyecta la estructura del modal una vez (idempotente).
  function _makeModal(opts) {
    let modal = document.getElementById(MODAL_ID);
    if (modal) return modal;
    const minW = (opts && opts.minWidth) || '';
    const maxW = (opts && opts.maxWidth) || '';
    const style = (minW || maxW)
      ? `style="${minW ? 'min-width:' + minW + ';' : ''}${maxW ? 'max-width:' + maxW + ';' : ''}"`
      : '';
    const html = `
      <div class="modal-backdrop" id="${MODAL_ID}">
        <div class="ped-modal-card" ${style} style="position:relative; ${minW ? 'min-width:' + minW + ';' : ''}${maxW ? 'max-width:' + maxW + ';' : ''}">
          <button type="button" id="mgp-close-x"
                  title="Cerrar"
                  aria-label="Cerrar"
                  style="position:absolute; top:0.8rem; right:0.9rem;
                         width:30px; height:30px; padding:0; line-height:1;
                         font-size:1.3rem; font-weight:300; color:#7a7a7a;
                         background:transparent; border:none; cursor:pointer;
                         border-radius:50%; transition:background 0.12s, color 0.12s;">×</button>
          <h3>Generar pedido a proveedor</h3>
          <p class="ped-sub">Se generará un PDF por cada proveedor. Edita los kg y el precio antes de confirmar.</p>
          <div class="ped-error" id="mgp-error"></div>
          <div class="ped-success" id="mgp-success"></div>
          <div id="mgp-grupos"></div>
          <div style="margin-top:0.9rem">
            <label style="font-size:0.78rem; font-weight:600; color:#4d4d4d; display:block; margin-bottom:0.3rem">
              Nota (se incluye en el PDF de todos los proveedores)
            </label>
            <textarea class="ped-nota" id="mgp-nota" maxlength="300"
                      placeholder="Ej. Confirmar disponibilidad y plazo de entrega. Gracias."></textarea>
          </div>
          <div class="ped-modal-actions">
            <button type="button" class="btn-pedido-ghost" id="mgp-cancelar">Cancelar</button>
            <button type="button" class="btn-pedido-ghost" id="mgp-confirmar-sinpdf"
                    title="Registra el pedido sin abrir PDFs (puedes descargarlos después desde el enlace que aparece arriba)">
              Confirmar
            </button>
            <button type="button" class="btn-pedido" id="mgp-confirmar">Confirmar y descargar PDFs</button>
          </div>
        </div>
      </div>`;
    document.body.insertAdjacentHTML('beforeend', html);
    modal = document.getElementById(MODAL_ID);
    _bind(modal);
    return modal;
  }

  let _ctx = null;   // { variantes, onCreated, onClose }

  // Cablea handlers UNA SOLA VEZ (al crear el modal).
  function _bind(modal) {
    const cont = modal.querySelector('#mgp-grupos');
    const btnCancelar     = modal.querySelector('#mgp-cancelar');
    const btnConfirmar    = modal.querySelector('#mgp-confirmar');
    const btnConfirmarSPDF = modal.querySelector('#mgp-confirmar-sinpdf');
    const btnCloseX       = modal.querySelector('#mgp-close-x');

    btnCancelar.addEventListener('click', _cerrar);
    btnCloseX.addEventListener('click', _cerrar);
    // Hover sutil sobre el ×
    btnCloseX.addEventListener('mouseenter', () => {
      btnCloseX.style.background = '#faf3e3';
      btnCloseX.style.color = '#2a2a2a';
    });
    btnCloseX.addEventListener('mouseleave', () => {
      btnCloseX.style.background = 'transparent';
      btnCloseX.style.color = '#7a7a7a';
    });
    modal.addEventListener('click', (e) => {
      if (e.target === modal) _cerrar();
    });
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape' && modal.classList.contains('open')) _cerrar();
    });

    // Recalcular importes al editar inputs (delegacion)
    cont.addEventListener('input', _recalcImportes);

    // Botones de confirmacion globales
    btnConfirmar.addEventListener('click', (e) =>
      _enviar({ btnEl: e.currentTarget, sinDescargar: false }));
    btnConfirmarSPDF.addEventListener('click', (e) =>
      _enviar({ btnEl: e.currentTarget, sinDescargar: true }));

    // Botones "Generar solo <prov>" (delegacion sobre los grupos)
    cont.addEventListener('click', (e) => {
      const btn = e.target.closest('.btn-prov-solo');
      if (!btn) return;
      const grupo = btn.closest('.ped-prov-grupo');
      _enviar({
        proveedorScope: btn.dataset.provSolo,
        btnEl: btn,
        grupoEl: grupo,
        sinDescargar: false,
      });
    });
  }

  function _cerrar() {
    const modal = document.getElementById(MODAL_ID);
    if (modal) modal.classList.remove('open');
    if (_ctx && typeof _ctx.onClose === 'function') {
      try { _ctx.onClose(); } catch (_) {}
    }
    _ctx = null;
  }

  // Recalcula los importes (kg * €/kg) y subtotales por proveedor.
  function _recalcImportes() {
    document.querySelectorAll(`#${MODAL_ID} #mgp-grupos .ped-prov-grupo`).forEach(grupo => {
      let subtotal = 0;
      grupo.querySelectorAll('tbody tr').forEach(tr => {
        const kg  = Number(tr.querySelector('.ped-kg').value) || 0;
        const eur = Number(tr.querySelector('.ped-eur-kg').value) || 0;
        const imp = kg * eur;
        const cellImp = tr.querySelector('.ped-importe');
        if (cellImp) cellImp.textContent = imp > 0 ? _fmtNum(imp, 2) + ' €' : '—';
        subtotal += imp;
      });
      const subEl = grupo.querySelector('.ped-prov-subtotal');
      if (subEl) subEl.textContent = subtotal > 0 ? _fmtNum(subtotal, 2) + ' €' : '—';
    });
  }

  // Renderiza los grupos por proveedor con las variantes recibidas.
  function _pintarGrupos(variantes) {
    const porProv = {};
    variantes.forEach(v => {
      const prov = v.proveedor || '(sin proveedor)';
      (porProv[prov] = porProv[prov] || []).push(v);
    });
    const nProvs = Object.keys(porProv).length;
    const cont = document.querySelector(`#${MODAL_ID} #mgp-grupos`);
    cont.innerHTML = Object.entries(porProv).map(([prov, items]) => `
      <div class="ped-prov-grupo" data-prov="${_escapeHtml(prov)}">
        <div class="ped-prov-titulo">
          ${_escapeHtml(prov)}
          <small>${items.length} ${items.length === 1 ? 'variante' : 'variantes'}</small>
        </div>
        <table class="ped-tabla">
          <thead>
            <tr>
              <th>Calidad</th>
              <th>Partido <small style="font-weight:400; text-transform:none">(opcional)</small></th>
              <th class="num">kg a pedir</th>
              <th class="num">€/kg</th>
              <th class="num">Importe</th>
            </tr>
          </thead>
          <tbody>
            ${items.map(v => {
              const kg  = Number(v.kg_a_pedir) || 0;
              // Sugerencia de eur_kg: prioridad a la tarifa actual editable
              // (mantenida desde la ficha del proveedor) → precio_2026 →
              // precio_2025 como fallbacks legacy.
              const eur = Number(v.tarifa_actual_eur_kg)
                       || Number(v.precio_2026)
                       || Number(v.precio_2025)
                       || 0;
              return `
                <tr data-vid="${_escapeHtml(v.id)}">
                  <td>${_escapeHtml(v.nombre || '')}</td>
                  <td><input class="ped-input ped-partido" type="text" maxlength="40"
                             placeholder="Si lo sabes ya" style="text-align:left; width:110px" /></td>
                  <td class="num"><input class="ped-input ped-kg"     type="number" step="1"    min="1"   value="${kg || ''}" /></td>
                  <td class="num"><input class="ped-input ped-eur-kg" type="number" step="0.01" min="0"   value="${eur || ''}" /></td>
                  <td class="num ped-importe">—</td>
                </tr>`;
            }).join('')}
          </tbody>
        </table>
        <div class="ped-prov-bottom">
          <div class="ped-prov-total">Subtotal <strong class="ped-prov-subtotal">—</strong></div>
          ${nProvs > 1 ? `
            <button type="button" class="btn-pedido btn-prov-solo" data-prov-solo="${_escapeHtml(prov)}">
              Generar solo ${_escapeHtml(prov)} →
            </button>` : ''}
        </div>
        <div class="ped-prov-feedback"></div>
      </div>
    `).join('');
    _recalcImportes();
  }

  // Recoge las lineas con kg>0 de los grupos no enviados (filtrable por proveedor).
  function _recolectarLineas(soloProveedor) {
    const lineas = [];
    document.querySelectorAll(`#${MODAL_ID} #mgp-grupos .ped-prov-grupo`).forEach(grupo => {
      if (grupo.classList.contains('enviado')) return;
      if (soloProveedor && grupo.dataset.prov !== soloProveedor) return;
      grupo.querySelectorAll('tbody tr').forEach(tr => {
        const vid = tr.dataset.vid;
        const kg  = Number(tr.querySelector('.ped-kg').value) || 0;
        const eur = Number(tr.querySelector('.ped-eur-kg').value) || null;
        const partido = (tr.querySelector('.ped-partido')?.value || '').trim();
        if (kg > 0) {
          const ln = { variante_id: vid, kg };
          if (eur != null && eur > 0) ln.eur_kg = eur;
          if (partido) ln.partido = partido;
          lineas.push(ln);
        }
      });
    });
    return lineas;
  }

  // POSTea el pedido. `proveedorScope` opcional limita a un grupo.
  async function _enviar({ proveedorScope, btnEl, grupoEl, sinDescargar }) {
    const lineas = _recolectarLineas(proveedorScope);
    const errGlobal = document.getElementById('mgp-error');
    const okGlobal  = document.getElementById('mgp-success');
    const errLocal  = grupoEl ? grupoEl.querySelector('.ped-prov-feedback') : null;
    if (errLocal) errLocal.className = 'ped-prov-feedback';
    errGlobal.classList.remove('show');

    if (!lineas.length) {
      const msg = 'No hay líneas con kg > 0 para enviar.';
      if (errLocal) { errLocal.textContent = msg; errLocal.classList.add('err'); }
      else          { errGlobal.textContent = msg; errGlobal.classList.add('show'); }
      return;
    }
    const nota = document.getElementById('mgp-nota').value.trim();
    const txtOriginal = btnEl.textContent;
    btnEl.disabled = true;
    btnEl.textContent = 'Generando…';
    try {
      const r = await fetch('/api/compras/generar-pedido', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ lineas, nota }),
      });
      const ct = r.headers.get('content-type') || '';
      if (!ct.includes('application/json')) {
        throw new Error(`El servidor no reconoce este endpoint (HTTP ${r.status}). ` +
                        `Reinicia "Iniciar Rols One.bat".`);
      }
      const d = await r.json();
      if (!r.ok) throw new Error(d.error || 'HTTP ' + r.status);

      // Si sinDescargar=true (boton "Confirmar"): no abrimos los PDFs
      // automaticamente. Los enlaces quedan disponibles en el mensaje
      // de exito para descargarlos despues.
      const links = Object.entries(d.urls_pdf || {}).map(([prov, url]) => {
        if (!sinDescargar) {
          try { window.open(url, '_blank', 'noopener'); } catch (_) {}
        }
        return `<a href="${_escapeHtml(url)}" target="_blank">PDF ${_escapeHtml(prov)}</a>`;
      }).join(' ');

      if (proveedorScope && grupoEl) {
        // Marcar el grupo como enviado y dejar el modal abierto para seguir
        grupoEl.classList.add('enviado');
        if (errLocal) {
          errLocal.classList.add('ok');
          errLocal.innerHTML = `Pedido <strong>${_escapeHtml(d.ref)}</strong> enviado. ${links}`;
        }
        // El boton "Generar solo X" se convierte en "✓ Generado" disabled
        // (en lugar de ocultarse). Asi el usuario ve el feedback de que
        // ese proveedor ya esta hecho aunque el modal siga abierto.
        if (btnEl) {
          btnEl.disabled = true;
          btnEl.classList.add('btn-generado');
          btnEl.textContent = '✓ Generado';
          btnEl.title = `Pedido ${d.ref} ya generado`;
        }
        // NO autocerramos el modal aunque no queden grupos pendientes:
        // el usuario decide cuando cerrar via X o Cancelar/Cerrar.
      } else {
        okGlobal.innerHTML = `Pedido <strong>${_escapeHtml(d.ref)}</strong> creado. ${links}`;
        okGlobal.classList.add('show');
        // Estado post-exito: ocultar botones de confirmar y cambiar Cancelar → Cerrar
        const btnCerrar = document.getElementById('mgp-cancelar');
        const btnConfirmar = document.getElementById('mgp-confirmar');
        const btnConfirmarSinPdf = document.getElementById('mgp-confirmar-sinpdf');
        btnCerrar.textContent = 'Cerrar';
        btnCerrar.classList.remove('btn-pedido-ghost');
        btnCerrar.classList.add('btn-pedido');
        btnConfirmar.style.display = 'none';
        if (btnConfirmarSinPdf) btnConfirmarSinPdf.style.display = 'none';
      }
      // Callback con el ref del pedido creado (para que la pagina refresque
      // su tabla, su ficha, etc.).
      if (_ctx && typeof _ctx.onCreated === 'function') {
        try { _ctx.onCreated(d.ref, d); } catch (_) {}
      }
    } catch (err) {
      const msg = 'Error: ' + err.message;
      if (errLocal) { errLocal.textContent = msg; errLocal.classList.add('err'); }
      else          { errGlobal.textContent = msg; errGlobal.classList.add('show'); }
    } finally {
      btnEl.disabled = false;
      btnEl.textContent = txtOriginal;
    }
  }

  // Reset de UI al abrir (por si el modal se habia dejado en estado post-exito).
  function _resetUI() {
    const errEl  = document.getElementById('mgp-error');
    const okEl   = document.getElementById('mgp-success');
    const notaEl = document.getElementById('mgp-nota');
    const btnCerrar = document.getElementById('mgp-cancelar');
    const btnConfirmar = document.getElementById('mgp-confirmar');
    const btnConfirmarSinPdf = document.getElementById('mgp-confirmar-sinpdf');
    if (errEl) { errEl.classList.remove('show'); errEl.textContent = ''; }
    if (okEl)  { okEl.classList.remove('show');  okEl.innerHTML = ''; }
    if (notaEl) notaEl.value = '';
    if (btnCerrar) {
      btnCerrar.textContent = 'Cancelar';
      btnCerrar.classList.remove('btn-pedido');
      btnCerrar.classList.add('btn-pedido-ghost');
    }
    if (btnConfirmar) {
      btnConfirmar.style.display = '';
      btnConfirmar.disabled = false;
    }
    if (btnConfirmarSinPdf) {
      btnConfirmarSinPdf.style.display = '';
      btnConfirmarSinPdf.disabled = false;
    }
  }

  // ===== API publica =====
  window.abrirModalPedidoGenerar = function ({
    variantes, onCreated, onClose, modalCardOpts,
  }) {
    if (!Array.isArray(variantes) || !variantes.length) {
      if (window.mostrarAlerta) {
        window.mostrarAlerta({
          titulo: 'Sin variantes',
          mensaje: 'No hay variantes seleccionadas para generar pedido.',
          tipo: 'warn',
        });
      }
      return;
    }
    _makeModal(modalCardOpts);
    _ctx = { variantes, onCreated, onClose };
    _resetUI();
    _pintarGrupos(variantes);
    document.getElementById(MODAL_ID).classList.add('open');
  };
})();
