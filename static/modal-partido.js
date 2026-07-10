/* ===========================================================================
   Modal "Editar partido" — compartido entre la ficha de calidad y la
   tab Compras del Kanban.

   API:
     abrirModalPartido({
       vid,            // id de la variante (calidad+proveedor)
       calidad_id,     // id de la calidad (para el endpoint)
       proveedor,      // proveedor (para desambiguar)
       partido,        // dict con los datos actuales del partido:
                       //   { partido, kg, coste_kg, fecha_entrada,
                       //     estanteria, fecha_compra, observaciones }
       lanaLabel,      // texto para mostrar arriba (ej. "80/2C PAIS NORMAL")
       usuario,        // string opcional para auditoria
       onSaved,        // callback tras guardar (sin args)
       onDeleted,      // callback tras borrar (sin args)
     })

   Requiere ui-modales.js cargado antes (usa mostrarConfirmacion para
   confirmar el borrado).
   =========================================================================== */
(function () {
  if (window.__mpReady) return;
  window.__mpReady = true;

  function $make() {
    if (document.getElementById('mp-modal-backdrop')) return;
    const html = `
      <div class="mp-backdrop" id="mp-modal-backdrop">
        <div class="mp-modal" role="dialog" aria-modal="true">
          <h3>Editar partido</h3>
          <p class="mp-sub" id="mp-modal-info">—</p>
          <div class="mp-error" id="mp-modal-err"></div>
          <div class="mp-row">
            <label for="mp-modal-ref">Nº partido</label>
            <input type="text" id="mp-modal-ref" maxlength="60" autocomplete="off" />
          </div>
          <!-- Cantidad: en lugar de editar el valor absoluto, el usuario
               aplica un ajuste positivo (+) o negativo (-). Asi siempre
               queda registrado el motivo del cambio en el historico de
               movimientos (un negativo = consumo, un positivo = recuento
               manual / mercancia encontrada / correccion). -->
          <div class="mp-row">
            <label>Cantidad actual</label>
            <div class="mp-cant-actual" id="mp-modal-cant-actual">— kg</div>
          </div>
          <div class="mp-row">
            <label>Ajuste de cantidad</label>
            <div class="mp-ajuste-row">
              <div class="mp-ajuste-toggle" role="tablist" aria-label="Signo del ajuste">
                <button type="button" class="mp-ajuste-btn active" id="mp-aj-neg" data-signo="-1"
                        title="Salida de stock (consumo, merma...)">
                  − Negativo
                </button>
                <button type="button" class="mp-ajuste-btn"        id="mp-aj-pos" data-signo="+1"
                        title="Entrada manual (recuento, mercancia encontrada...)">
                  + Positivo
                </button>
              </div>
              <input type="number" id="mp-modal-ajuste" step="0.01" min="0"
                     placeholder="kg a ajustar" autocomplete="off" style="flex:1" />
              <span class="mp-ajuste-unit">kg</span>
            </div>
            <div class="mp-cant-resultado" id="mp-modal-resultado">
              Nuevo saldo: <strong id="mp-modal-resultado-valor">—</strong>
            </div>
          </div>
          <!-- kg que el proveedor sigue guardando en su almacen para
               nosotros. Esta reservado pero no llega fisicamente hasta
               que pidamos el traslado. Si lo cambias aqui, la diferencia
               se aplica con signo CONTRARIO al saldo de almacen Rols:
               quitar 50 kg del proveedor = sumar 50 kg al almacen
               (interpretacion: los has traido fisicamente). El total
               del partido (kg + kg_proveedor) se conserva. -->
          <div class="mp-row mp-row-2">
            <div>
              <label for="mp-modal-kg-prov">
                En almacén proveedor (kg)
                <small style="display:block; color:#7a7a7a; font-weight:400; font-size:0.7rem; margin-top:0.15rem">
                  La diferencia se mueve al almacén Rols (no cambia el total).
                </small>
              </label>
              <input type="number" id="mp-modal-kg-prov" step="0.01" min="0"
                     placeholder="0" autocomplete="off" />
              <div class="mp-cant-resultado" id="mp-modal-resultado-prov"
                   style="font-size:0.78rem; margin-top:0.3rem">
                Δ en proveedor: <strong id="mp-modal-resultado-prov-delta">0 kg</strong>
                · Δ en almacén Rols: <strong id="mp-modal-resultado-prov-rols">0 kg</strong>
              </div>
            </div>
            <div>
              <label for="mp-modal-coste">Coste (€/kg)</label>
              <input type="number" id="mp-modal-coste" step="0.01" min="0" autocomplete="off" />
            </div>
          </div>
          <div class="mp-row">
            <label for="mp-modal-estanteria">Estantería</label>
            <input type="text" id="mp-modal-estanteria" maxlength="40"
                   placeholder="Ej. E-3-A" autocomplete="off" />
          </div>
          <div class="mp-row mp-row-2">
            <div>
              <label for="mp-modal-fecha-compra">Fecha de compra</label>
              <input type="date" id="mp-modal-fecha-compra" autocomplete="off" />
            </div>
            <div>
              <label for="mp-modal-fecha">Fecha llegada al almacén</label>
              <input type="date" id="mp-modal-fecha" autocomplete="off" />
            </div>
          </div>
          <div class="mp-row">
            <label for="mp-modal-obs">Observaciones</label>
            <input type="text" id="mp-modal-obs" maxlength="300"
                   placeholder="—" autocomplete="off" />
          </div>
          <div class="mp-actions">
            <button type="button" class="mp-btn mp-btn-danger" id="mp-modal-borrar">Borrar partido</button>
            <span style="flex:1"></span>
            <button type="button" class="mp-btn mp-btn-ghost"   id="mp-modal-cancelar">Cancelar</button>
            <button type="button" class="mp-btn mp-btn-primary" id="mp-modal-guardar">Guardar</button>
          </div>
        </div>
      </div>`;
    document.body.insertAdjacentHTML('beforeend', html);
  }

  let _ctx = null;
  let _wired = false;

  function _bind() {
    if (_wired) return;
    _wired = true;
    const back   = document.getElementById('mp-modal-backdrop');
    const cancel = document.getElementById('mp-modal-cancelar');
    const save   = document.getElementById('mp-modal-guardar');
    const del    = document.getElementById('mp-modal-borrar');

    cancel.addEventListener('click', _cerrar);
    back.addEventListener('click', (e) => { if (e.target === back) _cerrar(); });
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape' && back.classList.contains('open')) _cerrar();
    });

    save.addEventListener('click', async () => {
      if (!_ctx) return;
      const err = document.getElementById('mp-modal-err');
      err.classList.remove('show'); err.textContent = '';
      const nuevoRef    = document.getElementById('mp-modal-ref').value.trim();
      // Calculamos la nueva cantidad como cantidad_actual + ajuste*signo.
      // Si el usuario no introduce ajuste, se mantiene el saldo actual
      // (es decir, el modal vale tambien para editar SOLO observaciones,
      // estanteria, fechas, coste, etc. sin tocar el stock).
      const kgActual    = Number(_ctx.kg_actual) || 0;
      const ajusteRaw   = document.getElementById('mp-modal-ajuste').value.trim();
      const signo       = (window.__mpAjusteSigno === '+1') ? 1 : -1;
      const ajusteMag   = ajusteRaw === '' ? 0 : parseFloat(ajusteRaw);
      const ajusteRols  = signo * (isNaN(ajusteMag) ? 0 : ajusteMag);
      const coste       = parseFloat(document.getElementById('mp-modal-coste').value);
      // kg en almacen proveedor — opcional. Si el campo esta vacio se
      // envia 0 (no null), para que un usuario que LIMPIE el campo
      // pueda dejarlo a cero conscientemente.
      const kgProvRaw   = document.getElementById('mp-modal-kg-prov').value.trim();
      const kgProv      = kgProvRaw === '' ? 0 : parseFloat(kgProvRaw);
      // Cascada: la diferencia en kg_proveedor se aplica con signo
      // CONTRARIO a kg (Rols). Quitar X del proveedor = sumar X a Rols.
      // De esta forma el total del partido (kg + kg_proveedor) se
      // conserva salvo que el usuario haga ademas un ajuste explicito
      // con el +/-.
      const kgProvPrev  = Number(_ctx.kg_proveedor_actual) || 0;
      const deltaProv   = kgProv - kgProvPrev;   // + si sube, - si baja
      const kg          = kgActual + ajusteRols - deltaProv;
      const fecha       = document.getElementById('mp-modal-fecha').value;
      const fechaCompra = document.getElementById('mp-modal-fecha-compra').value;
      const estanteria  = document.getElementById('mp-modal-estanteria').value.trim();
      const obs         = document.getElementById('mp-modal-obs').value;
      if (!nuevoRef) {
        err.textContent = 'El nº de partido no puede estar vacio.';
        err.classList.add('show'); return;
      }
      if (ajusteRaw !== '' && (isNaN(ajusteMag) || ajusteMag < 0)) {
        err.textContent = 'El ajuste debe ser un numero positivo. Usa el toggle - / + para indicar el signo.';
        err.classList.add('show'); return;
      }
      if (kg < 0) {
        err.textContent = `El ajuste deja el saldo de almacén Rols negativo (${kg.toFixed(2)} kg). ` +
                          `Reduce el ajuste o el aumento de kg en proveedor.`;
        err.classList.add('show'); return;
      }
      if (isNaN(kgProv) || kgProv < 0) {
        err.textContent = 'En almacén proveedor debe ser un número >= 0.';
        err.classList.add('show'); return;
      }
      save.disabled = true;
      try {
        const r = await fetch(
          `/api/materias-primas/lanas/${encodeURIComponent(_ctx.calidad_id)}/lotes/${encodeURIComponent(_ctx.partido_ref_original)}`,
          {
            method: 'PUT',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
              lote: nuevoRef,
              cantidad_disponible_kg: kg,
              kg_proveedor:  kgProv,
              coste_kg:      isNaN(coste) ? null : coste,
              fecha_entrada: fecha || null,
              fecha_compra:  fechaCompra || null,
              estanteria:    estanteria || null,
              observaciones: obs,
              proveedor:     _ctx.proveedor,
              usuario:       _ctx.usuario || '',
            }),
          }
        );
        const ct = r.headers.get('content-type') || '';
        if (!ct.includes('application/json')) {
          throw new Error(`El servidor no reconoce este endpoint (HTTP ${r.status}). ` +
                          `Reinicia "Iniciar Rols One.bat".`);
        }
        const d = await r.json();
        if (!r.ok) throw new Error(d.error || 'HTTP ' + r.status);
        const cb = _ctx.onSaved;
        _cerrar();
        if (cb) cb();
      } catch (e) {
        err.textContent = e.message;
        err.classList.add('show');
      } finally {
        save.disabled = false;
      }
    });

    del.addEventListener('click', async () => {
      if (!_ctx) return;
      const {ok} = await (window.mostrarConfirmacion || (async (o) => ({ok: confirm(o.mensaje)})))({
        titulo: 'Borrar partido',
        mensaje: `Se borrará el partido ${_ctx.partido_ref_original} de ${_ctx.lana_label}. ` +
                 `El stock total de la variante bajará. Esta acción queda registrada en el histórico.`,
        textoConfirmar: 'Borrar partido',
        tipo: 'danger',
      });
      if (!ok) return;
      del.disabled = true;
      try {
        const qs = `usuario=${encodeURIComponent(_ctx.usuario || '')}&proveedor=${encodeURIComponent(_ctx.proveedor || '')}`;
        const r = await fetch(
          `/api/materias-primas/lanas/${encodeURIComponent(_ctx.calidad_id)}/lotes/${encodeURIComponent(_ctx.partido_ref_original)}?${qs}`,
          { method: 'DELETE' }
        );
        const ct = r.headers.get('content-type') || '';
        if (!ct.includes('application/json')) {
          throw new Error(`El servidor no reconoce este endpoint (HTTP ${r.status}). ` +
                          `Reinicia "Iniciar Rols One.bat".`);
        }
        const d = await r.json();
        if (!r.ok) throw new Error(d.error || 'HTTP ' + r.status);
        const cb = _ctx.onDeleted || _ctx.onSaved;
        _cerrar();
        if (cb) cb();
      } catch (e) {
        const err = document.getElementById('mp-modal-err');
        err.textContent = e.message;
        err.classList.add('show');
      } finally {
        del.disabled = false;
      }
    });
  }

  function _cerrar() {
    document.getElementById('mp-modal-backdrop')?.classList.remove('open');
    _ctx = null;
  }

  function _escapeHtml(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, c =>
      ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  }

  window.abrirModalPartido = function ({vid, calidad_id, proveedor, partido,
                                         lanaLabel, usuario, onSaved, onDeleted}) {
    $make();
    _bind();
    const kgActual = Number(partido?.kg) || 0;
    const kgProvActual = Number(partido?.kg_proveedor) || 0;
    _ctx = {
      vid, calidad_id, proveedor,
      partido_ref_original: partido?.partido || '',
      kg_actual: kgActual,
      kg_proveedor_actual: kgProvActual,
      lana_label: lanaLabel || '',
      usuario, onSaved, onDeleted,
    };
    const info = document.getElementById('mp-modal-info');
    const pkey = (proveedor || '').split('/')[0].trim().toUpperCase();
    info.innerHTML = `<strong>${_escapeHtml(lanaLabel || '')}</strong>` +
      ` &middot; <span class="prov-pill prov-${_escapeHtml(pkey)}">${_escapeHtml(proveedor || '—')}</span>`;
    document.getElementById('mp-modal-err').classList.remove('show');
    document.getElementById('mp-modal-ref').value          = partido?.partido || '';
    document.getElementById('mp-modal-cant-actual').textContent = _fmtKg(kgActual);
    document.getElementById('mp-modal-ajuste').value       = '';
    // Toggle - / +: por defecto arrancamos en "-" (caso mas comun: consumo)
    window.__mpAjusteSigno = '-1';
    document.getElementById('mp-aj-neg').classList.add('active');
    document.getElementById('mp-aj-pos').classList.remove('active');
    _refrescarResultado();
    // kg_proveedor del partido (vacio si 0/null para no mostrar "0" siempre)
    const kgProv = Number(partido?.kg_proveedor) || 0;
    document.getElementById('mp-modal-kg-prov').value      = kgProv > 0 ? kgProv : '';
    document.getElementById('mp-modal-coste').value        = partido?.coste_kg ?? '';
    document.getElementById('mp-modal-estanteria').value   = partido?.estanteria || '';
    document.getElementById('mp-modal-fecha-compra').value = partido?.fecha_compra || '';
    document.getElementById('mp-modal-fecha').value        = partido?.fecha_entrada || '';
    document.getElementById('mp-modal-obs').value          = partido?.observaciones || '';
    document.getElementById('mp-modal-backdrop').classList.add('open');
    setTimeout(() => document.getElementById('mp-modal-ajuste').focus(), 50);
  };

  // Helper: formatea kg con separadores ES
  function _fmtKg(n) {
    if (n == null || isNaN(n)) return '— kg';
    return Number(n).toLocaleString('es-ES', { maximumFractionDigits: 2 }) + ' kg';
  }

  // Refresca el texto "Nuevo saldo" en tiempo real al cambiar
  // ajuste/signo o kg_proveedor. El saldo de almacen Rols es:
  //   nuevo_kg = kg_actual + ajuste*signo - (kgProv_nuevo - kgProv_prev)
  // Asi, subir kgProv resta de Rols y bajar kgProv suma a Rols.
  function _refrescarResultado() {
    if (!_ctx) return;
    const ajusteRaw = document.getElementById('mp-modal-ajuste').value.trim();
    const ajusteMag = ajusteRaw === '' ? 0 : parseFloat(ajusteRaw);
    const signo = (window.__mpAjusteSigno === '+1') ? 1 : -1;
    const ajusteRols = signo * (isNaN(ajusteMag) ? 0 : ajusteMag);
    const kgProvRaw = document.getElementById('mp-modal-kg-prov').value.trim();
    const kgProvNuevo = kgProvRaw === '' ? 0 : parseFloat(kgProvRaw);
    const kgProvPrev = Number(_ctx.kg_proveedor_actual) || 0;
    const deltaProv = isNaN(kgProvNuevo) ? 0 : (kgProvNuevo - kgProvPrev);
    const nuevoKg = (Number(_ctx.kg_actual) || 0) + ajusteRols - deltaProv;
    // Preview de Rols
    const valEl = document.getElementById('mp-modal-resultado-valor');
    if (valEl) {
      valEl.textContent = _fmtKg(nuevoKg);
      valEl.classList.toggle('mp-resultado-neg', nuevoKg < 0);
      valEl.classList.toggle('mp-resultado-warn',
        nuevoKg >= 0 && nuevoKg < (Number(_ctx.kg_actual) || 0));
    }
    // Preview de los dos deltas (proveedor + cascada a Rols)
    const dpEl = document.getElementById('mp-modal-resultado-prov-delta');
    const drEl = document.getElementById('mp-modal-resultado-prov-rols');
    if (dpEl && drEl) {
      const fmtDelta = (d) => (d > 0 ? '+' : '') + _fmtKg(d);
      dpEl.textContent = fmtDelta(deltaProv);
      drEl.textContent = fmtDelta(-deltaProv);
      // Color rojo si negativo, verde si positivo, gris si 0
      const colorDelta = deltaProv === 0 ? '#7a7a7a' : (deltaProv > 0 ? '#2c5b8a' : '#9b1c1c');
      const colorRols  = deltaProv === 0 ? '#7a7a7a' : (deltaProv > 0 ? '#9b1c1c' : '#2f6b29');
      dpEl.style.color = colorDelta;
      drEl.style.color = colorRols;
    }
  }

  // Wire up del toggle - / + y del input de ajuste para preview en vivo.
  // Lo hacemos dentro de un init diferido para que los elementos existan
  // (el modal se inyecta la primera vez que se abre).
  document.addEventListener('click', (e) => {
    const btn = e.target.closest('.mp-ajuste-btn');
    if (!btn) return;
    document.querySelectorAll('.mp-ajuste-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    window.__mpAjusteSigno = btn.dataset.signo;
    _refrescarResultado();
  });
  document.addEventListener('input', (e) => {
    if (e.target && (e.target.id === 'mp-modal-ajuste' ||
                     e.target.id === 'mp-modal-kg-prov')) {
      _refrescarResultado();
    }
  });
})();
