/* ===========================================================================
   Modales reutilizables de Rols One — drop-in replacement de confirm/
   prompt/alert nativos, con la paleta de la app.

     await mostrarConfirmacion({titulo, mensaje, conMotivo, textoConfirmar, tipo})
                       → {ok, motivo}
     await mostrarPrompt({titulo, mensaje, placeholder, textoConfirmar,
                          valorDefecto, validador, multilinea})
                       → {ok, valor}
     await mostrarAlerta({titulo, mensaje, tipo})       → undefined

   Inyecta el modal en el body al cargar (idempotente, solo una vez).
   Soporta Esc para cancelar, Enter para confirmar (excepto en textarea).
   =========================================================================== */
(function () {
  if (window.__uimReady) return;
  window.__uimReady = true;

  function $make() {
    if (document.getElementById('uim-backdrop')) return;
    const html = `
      <div class="uim-backdrop" id="uim-backdrop">
        <div class="uim-modal" role="dialog" aria-modal="true">
          <h3 id="uim-titulo">—</h3>
          <p class="uim-sub" id="uim-mensaje">—</p>
          <div class="uim-error" id="uim-error"></div>
          <div class="uim-row" id="uim-row-input" style="display:none">
            <label id="uim-input-label">Valor</label>
            <input type="text" id="uim-input" autocomplete="off" />
          </div>
          <div class="uim-row" id="uim-row-textarea" style="display:none">
            <label id="uim-textarea-label">Detalle</label>
            <textarea id="uim-textarea" rows="3"></textarea>
          </div>
          <div class="uim-actions">
            <button type="button" class="uim-btn uim-btn-ghost"  id="uim-btn-cancelar">Cancelar</button>
            <button type="button" class="uim-btn uim-btn-primary" id="uim-btn-confirmar">Aceptar</button>
          </div>
        </div>
      </div>`;
    document.body.insertAdjacentHTML('beforeend', html);
  }

  function _open(opts) {
    $make();
    const back = document.getElementById('uim-backdrop');
    const titulo = document.getElementById('uim-titulo');
    const mensaje = document.getElementById('uim-mensaje');
    const err = document.getElementById('uim-error');
    const rowInput = document.getElementById('uim-row-input');
    const rowTextarea = document.getElementById('uim-row-textarea');
    const inp = document.getElementById('uim-input');
    const inpLbl = document.getElementById('uim-input-label');
    const ta = document.getElementById('uim-textarea');
    const taLbl = document.getElementById('uim-textarea-label');
    const btnCancelar = document.getElementById('uim-btn-cancelar');
    const btnConfirmar = document.getElementById('uim-btn-confirmar');

    titulo.textContent = opts.titulo || '';
    mensaje.textContent = opts.mensaje || '';
    mensaje.style.display = opts.mensaje ? '' : 'none';
    err.classList.remove('show'); err.textContent = '';

    // Modo input simple (prompt)
    rowInput.style.display = opts.tipoCampo === 'input' ? '' : 'none';
    if (opts.tipoCampo === 'input') {
      inpLbl.textContent = opts.etiquetaCampo || 'Valor';
      inp.value = opts.valorDefecto || '';
      inp.placeholder = opts.placeholder || '';
      inp.type = opts.tipoInput || 'text';
    }

    // Modo textarea (confirm con motivo)
    rowTextarea.style.display = opts.tipoCampo === 'textarea' ? '' : 'none';
    if (opts.tipoCampo === 'textarea') {
      taLbl.textContent = opts.etiquetaCampo || 'Motivo';
      ta.value = opts.valorDefecto || '';
      ta.placeholder = opts.placeholder || '';
    }

    // Botones: cancelar visible salvo en alerta pura; confirmar siempre
    btnCancelar.style.display = opts.modoAlerta ? 'none' : '';
    btnCancelar.textContent = opts.textoCancelar || 'Cancelar';
    btnConfirmar.textContent = opts.textoConfirmar || 'Aceptar';
    // Tipo del boton de confirmar
    btnConfirmar.classList.remove('uim-btn-primary', 'uim-btn-danger');
    btnConfirmar.classList.add(opts.tipo === 'danger' ? 'uim-btn-danger' : 'uim-btn-primary');

    return new Promise((resolve) => {
      let cerrado = false;
      const valor = () => {
        if (opts.tipoCampo === 'input') return inp.value.trim();
        if (opts.tipoCampo === 'textarea') return ta.value.trim();
        return '';
      };
      const cerrar = (ok) => {
        if (cerrado) return; cerrado = true;
        back.classList.remove('open');
        btnCancelar.removeEventListener('click', onCancel);
        btnConfirmar.removeEventListener('click', onConfirm);
        back.removeEventListener('click', onBackdrop);
        document.removeEventListener('keydown', onKey);
        resolve({ok, valor: ok ? valor() : '', motivo: ok ? valor() : ''});
      };
      const onCancel = () => cerrar(false);
      const onConfirm = () => {
        // Validador opcional
        if (opts.validador) {
          const msg = opts.validador(valor());
          if (msg) { err.textContent = msg; err.classList.add('show'); return; }
        }
        cerrar(true);
      };
      const onBackdrop = (e) => { if (e.target === back) cerrar(false); };
      const onKey = (e) => {
        if (!back.classList.contains('open')) return;
        if (e.key === 'Escape') { e.preventDefault(); cerrar(false); }
        if (e.key === 'Enter' && document.activeElement !== ta) {
          e.preventDefault(); onConfirm();
        }
      };

      btnCancelar.addEventListener('click', onCancel);
      btnConfirmar.addEventListener('click', onConfirm);
      back.addEventListener('click', onBackdrop);
      document.addEventListener('keydown', onKey);

      back.classList.add('open');
      setTimeout(() => {
        if (opts.tipoCampo === 'input') inp.focus();
        else if (opts.tipoCampo === 'textarea') ta.focus();
        else btnConfirmar.focus();
      }, 50);
    });
  }

  window.mostrarConfirmacion = function (opts) {
    return _open({
      titulo: opts.titulo,
      mensaje: opts.mensaje,
      tipoCampo: opts.conMotivo ? 'textarea' : null,
      etiquetaCampo: 'Motivo',
      placeholder: opts.placeholderMotivo || 'Opcional',
      textoConfirmar: opts.textoConfirmar || 'Aceptar',
      tipo: opts.tipo,
    });
  };

  window.mostrarPrompt = function (opts) {
    return _open({
      titulo: opts.titulo,
      mensaje: opts.mensaje,
      tipoCampo: opts.multilinea ? 'textarea' : 'input',
      etiquetaCampo: opts.etiqueta || '',
      placeholder: opts.placeholder || '',
      valorDefecto: opts.valorDefecto || '',
      tipoInput: opts.tipoInput || 'text',
      textoConfirmar: opts.textoConfirmar || 'Aceptar',
      tipo: opts.tipo,
      validador: opts.validador,
    });
  };

  window.mostrarAlerta = function (opts) {
    return _open({
      titulo: opts.titulo || 'Aviso',
      mensaje: opts.mensaje,
      textoConfirmar: opts.textoConfirmar || 'Entendido',
      modoAlerta: true,
      tipo: opts.tipo,
    });
  };

  // ============================================================
  // Modal "Marcar mercancia recibida" — especifico para pedidos
  //
  // Devuelve { ok: bool, kg_a_rols: number|null }
  //   ok=false → usuario cancelo
  //   ok=true, kg_a_rols=null → todo llega a Rols (default)
  //   ok=true, kg_a_rols=N    → N kg llegan a Rols, resto se queda en proveedor
  //
  // Uso:
  //   const r = await mostrarModalRecibido({ref: 'PED-...', kgTotal: 3000});
  //   if (!r.ok) return;
  //   // POST con r.kg_a_rols (puede ser null o number)
  // ============================================================
  window.mostrarModalRecibido = function ({ ref, kgTotal }) {
    return new Promise((resolve) => {
      const MID = 'uim-recibido';
      // Reinyectar el modal LIMPIO en cada apertura: reutilizar el DOM
      // acumulaba los listeners de radios/labels/input de aperturas
      // anteriores, y el closure viejo (con el kgTotal del pedido previo)
      // corria primero y rellenaba el split con un default equivocado.
      document.getElementById(MID)?.remove();
      let back = document.getElementById(MID);
      if (!back) {
        document.body.insertAdjacentHTML('beforeend', `
          <div class="uim-backdrop" id="${MID}">
            <div class="uim-modal" role="dialog" aria-modal="true" style="min-width:440px; max-width:520px">
              <h3>Marcar mercancía recibida</h3>
              <p class="uim-sub" id="uim-rec-sub">—</p>
              <div style="margin:0.6rem 0 0.4rem; font-size:0.78rem; font-weight:600; color:#4d4d4d">
                ¿Dónde llega la mercancía?
              </div>
              <label style="display:flex; align-items:flex-start; gap:0.55rem; padding:0.55rem 0.7rem; border:1px solid var(--border); border-radius:8px; cursor:pointer; margin-bottom:0.4rem; background:#fff" id="uim-rec-opt1-label">
                <input type="radio" name="uim-rec-destino" id="uim-rec-opt1" value="todo-rols" checked style="margin-top:0.15rem; accent-color:var(--accent)" />
                <div style="flex:1">
                  <div style="font-weight:600; color:#2a2a2a">Todo llega al almacén Rols</div>
                  <div style="font-size:0.74rem; color:#7a7a7a">Los kg del pedido se registran completos en tu almacén.</div>
                </div>
              </label>
              <label style="display:flex; align-items:flex-start; gap:0.55rem; padding:0.55rem 0.7rem; border:1px solid var(--border); border-radius:8px; cursor:pointer; background:#fff" id="uim-rec-opt2-label">
                <input type="radio" name="uim-rec-destino" id="uim-rec-opt2" value="split" style="margin-top:0.15rem; accent-color:var(--accent)" />
                <div style="flex:1">
                  <div style="font-weight:600; color:#2a2a2a">Parte queda en el almacén del proveedor</div>
                  <div style="font-size:0.74rem; color:#7a7a7a">Indica cuántos kg llegan a tu almacén; el resto se queda reservado en el proveedor.</div>
                </div>
              </label>
              <div id="uim-rec-split-box" style="margin-top:0.5rem; padding:0.7rem 0.8rem; background:#faf6ee; border-radius:8px; display:none">
                <label for="uim-rec-kg-rols" style="font-size:0.74rem; font-weight:600; color:#4d4d4d; display:block; margin-bottom:0.3rem">
                  kg que llegan a tu almacén
                </label>
                <input type="number" id="uim-rec-kg-rols" step="0.01" min="0"
                       style="width:140px; padding:0.4rem 0.6rem; border:1px solid var(--border); border-radius:6px; font-size:0.9rem; font-family:inherit; background:#fff" />
                <div style="margin-top:0.4rem; font-size:0.78rem; color:#4d4d4d">
                  <span id="uim-rec-resumen">—</span>
                </div>
              </div>
              <div class="uim-error" id="uim-rec-error"></div>
              <div class="uim-actions">
                <button type="button" class="uim-btn uim-btn-ghost"  id="uim-rec-cancelar">Cancelar</button>
                <button type="button" class="uim-btn uim-btn-primary" id="uim-rec-confirmar">✓ Marcar recibido</button>
              </div>
            </div>
          </div>`);
        back = document.getElementById(MID);
      }
      // Reset estado
      const sub = back.querySelector('#uim-rec-sub');
      const opt1 = back.querySelector('#uim-rec-opt1');
      const opt2 = back.querySelector('#uim-rec-opt2');
      const splitBox = back.querySelector('#uim-rec-split-box');
      const inpKg = back.querySelector('#uim-rec-kg-rols');
      const resumen = back.querySelector('#uim-rec-resumen');
      const errBox = back.querySelector('#uim-rec-error');
      const btnCancelar = back.querySelector('#uim-rec-cancelar');
      const btnConfirmar = back.querySelector('#uim-rec-confirmar');
      sub.textContent = `Pedido ${ref} · ${Number(kgTotal).toLocaleString('es-ES')} kg`;
      opt1.checked = true;
      opt2.checked = false;
      splitBox.style.display = 'none';
      inpKg.value = '';
      resumen.textContent = '';
      errBox.classList.remove('show');
      errBox.textContent = '';

      const _resumen = () => {
        const v = parseFloat(inpKg.value);
        if (isNaN(v) || v < 0) {
          resumen.textContent = 'Introduce los kg que llegan';
          resumen.style.color = '#9b1c1c';
          return;
        }
        if (v > kgTotal) {
          resumen.textContent = `No puede ser mayor que el pedido (${kgTotal} kg)`;
          resumen.style.color = '#9b1c1c';
          return;
        }
        const resto = kgTotal - v;
        resumen.innerHTML = `→ <strong>${Number(v).toLocaleString('es-ES')} kg</strong> a Rols · <strong style="color:#6b46c1">${Number(resto).toLocaleString('es-ES')} kg</strong> quedan en proveedor`;
        resumen.style.color = '#4d4d4d';
      };
      const _onRadio = () => {
        if (opt2.checked) {
          splitBox.style.display = 'block';
          if (!inpKg.value) inpKg.value = String(Math.floor(kgTotal / 2));
          _resumen();
          setTimeout(() => inpKg.focus(), 50);
        } else {
          splitBox.style.display = 'none';
        }
      };
      opt1.addEventListener('change', _onRadio);
      opt2.addEventListener('change', _onRadio);
      // Click sobre el label entero también selecciona el radio
      back.querySelector('#uim-rec-opt1-label').addEventListener('click', () => { opt1.checked = true; _onRadio(); });
      back.querySelector('#uim-rec-opt2-label').addEventListener('click', () => { opt2.checked = true; _onRadio(); });
      inpKg.addEventListener('input', _resumen);

      let cerrado = false;
      const cerrar = (resultado) => {
        if (cerrado) return; cerrado = true;
        back.classList.remove('open');
        btnCancelar.removeEventListener('click', onCancel);
        btnConfirmar.removeEventListener('click', onConfirm);
        back.removeEventListener('click', onBackdrop);
        document.removeEventListener('keydown', onKey);
        resolve(resultado);
      };
      const onCancel = () => cerrar({ ok: false, kg_a_rols: null });
      const onConfirm = () => {
        if (opt2.checked) {
          const v = parseFloat(inpKg.value);
          if (isNaN(v) || v < 0 || v > kgTotal) {
            errBox.textContent = `Introduce un número entre 0 y ${kgTotal}`;
            errBox.classList.add('show');
            return;
          }
          cerrar({ ok: true, kg_a_rols: v });
        } else {
          cerrar({ ok: true, kg_a_rols: null });
        }
      };
      const onBackdrop = (e) => { if (e.target === back) cerrar({ ok: false, kg_a_rols: null }); };
      const onKey = (e) => {
        if (!back.classList.contains('open')) return;
        if (e.key === 'Escape') { e.preventDefault(); cerrar({ ok: false, kg_a_rols: null }); }
        if (e.key === 'Enter' && document.activeElement !== inpKg) {
          e.preventDefault(); onConfirm();
        }
      };
      btnCancelar.addEventListener('click', onCancel);
      btnConfirmar.addEventListener('click', onConfirm);
      back.addEventListener('click', onBackdrop);
      document.addEventListener('keydown', onKey);

      back.classList.add('open');
    });
  };
})();
