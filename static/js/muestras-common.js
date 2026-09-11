// ============================================================
// Muestras fabricadas — helpers comunes al listado y a la ficha.
// ============================================================
(function () {
  'use strict';

  const ESTADOS = [
    ['por_empezar', 'Por empezar'],
    ['listo_diseno', 'Listo para empezar diseño'],       // telares y Print
    ['en_diseno', 'En diseño'],
    ['revision_diseno', 'Listo para revisión diseño'],   // telares y Print
    ['diseno_listo', 'Diseño listo'],                    // solo los telares
    ['en_hilatura', 'En hilatura'],
    ['en_tintoreria', 'En tintorería'],
    ['revisar_color', 'Revisar color'],                  // solo Pompón
    ['bobinando', 'Bobinando'], ['esperando_telar', 'Esperando a telar'],
    ['en_telar', 'En telar'], ['en_aprestos', 'En aprestos'], ['terminada', 'Terminada'],
    ['cancelada', 'Cancelada'], ['sin_seguimiento', 'Sin seguimiento'],
  ];
  const ESTADOS_LABEL = Object.fromEntries(ESTADOS);
  // Flujo textil completo; las de Print (solo diseño) llevan el suyo, más
  // corto, y los telares el textil con las etapas de diseño por delante.
  const ESTADOS_FLUJO = ['por_empezar', 'en_diseno', 'en_hilatura', 'en_tintoreria',
    'bobinando', 'esperando_telar', 'en_telar', 'en_aprestos', 'terminada'];
  const FLUJO_PRINT = ['por_empezar', 'listo_diseno', 'en_diseno', 'revision_diseno', 'terminada'];
  // Los telares llevan las etapas de diseño por delante del flujo textil
  const FLUJO_TELAR = ['por_empezar', 'listo_diseno', 'en_diseno', 'revision_diseno', 'diseno_listo',
    'en_hilatura', 'en_tintoreria', 'bobinando', 'esperando_telar', 'en_telar', 'en_aprestos', 'terminada'];
  // Pompones y festones no se tejen: tintorería, revisar el color a la vuelta y listo
  const FLUJO_POMPON = ['por_empezar', 'en_tintoreria', 'revisar_color', 'terminada'];
  const FLUJOS_PROPIOS = { 'Print': FLUJO_PRINT,
    'Varilla': FLUJO_TELAR, 'Colortec': FLUJO_TELAR, 'Lancetas': FLUJO_TELAR,
    'Rapier': FLUJO_TELAR, 'Tufting Bucle': FLUJO_TELAR, 'Tufting Corte': FLUJO_TELAR,
    'Pompón': FLUJO_POMPON, 'Festón': FLUJO_POMPON };
  function flujoDe(telar) {
    const k = sinAcentos(telar);
    const hit = Object.keys(FLUJOS_PROPIOS).sort((a, b) => b.length - a.length)
      .find(n => k.startsWith(sinAcentos(n)));
    return hit ? FLUJOS_PROPIOS[hit] : ESTADOS_FLUJO;
  }
  // Flujo con el que se pinta una muestra: el de su técnica y, si la etapa
  // actual no está en él (una Print histórica parada en etapa textil, o una
  // etapa de diseño con otro telar), el primero que SÍ la contiene.
  function flujoQueContiene(telar, estado) {
    const propio = flujoDe(telar);
    if (propio.includes(estado)) return propio;
    return [ESTADOS_FLUJO, ...Object.values(FLUJOS_PROPIOS)].find(f => f.includes(estado)) || propio;
  }
  // `telar` se mantiene por si alguna técnica vuelve a renombrar una etapa
  const etiquetaEstado = (slug, telar) => ESTADOS_LABEL[slug] || slug || '—';
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

  // Telares con datos técnicos y en qué se diferencian (espejo de
  // TECNICOS_POR_TELAR en muestras_fabricadas.py):
  //   esTelar        → si de verdad es un telar (Pompón, Kibby y Festón no lo son)
  //   tejeduria      → enseña el bloque de tejeduría
  //   pelos          → construcciones; si solo hay una, NO se elige
  //   etiquetaN      → cómo se llama `n_cuerpos` en ese telar
  //   etiquetaCuerpo → cómo se llama la columna `cuerpo` de las materias
  //   hilosPua       → si la tabla de materias lleva esa columna
  const PELOS_VARILLA = [['corte', 'Corte'], ['bucle', 'Bucle'], ['corte_bucle', 'Corte y bucle'],
    ['estructurado', 'Estructurado'], ['pendiente', 'Pendiente']];
  const PELOS_LANCETAS = [['bucle_sencillo', 'Bucle sencillo'], ['tejido_plano', 'Tejido plano'],
    ['bucle_saltillo', 'Bucle con saltillo'], ['pendiente', 'Pendiente']];
  const TEC_BASE = { esTelar: true, tejeduria: true, etiquetaN: 'Nº de cuerpos', etiquetaCuerpo: 'Cuerpo', hilosPua: true };
  // Pompón, Kibby y Festón no son telares: solo materias, por color y sin hilos púa
  const TEC_SOLO_MATERIAS = { esTelar: false, tejeduria: false, pelos: [], etiquetaN: 'Nº de colores',
    etiquetaCuerpo: 'Color', hilosPua: false };
  const TECNICOS_POR_TELAR = {
    'Varilla': Object.assign({}, TEC_BASE, { pelos: PELOS_VARILLA }),
    'Lancetas': Object.assign({}, TEC_BASE, { pelos: PELOS_LANCETAS }),
    'Rapier': Object.assign({}, TEC_BASE, { pelos: [['tejido_plano', 'Tejido plano']] }),
    'Colortec': Object.assign({}, TEC_BASE, { pelos: [['corte', 'Corte']] }),
    // Tufting son dos telares distintos; los cuerpos se cuentan como colores
    'Tufting Bucle': Object.assign({}, TEC_BASE, { pelos: [['bucle', 'Bucle']], etiquetaN: 'Nº de colores' }),
    'Tufting Corte': Object.assign({}, TEC_BASE, { pelos: [['corte', 'Corte']], etiquetaN: 'Nº de colores' }),
    // No son telares: solo materias (ver TEC_SOLO_MATERIAS)
    'Pompón': Object.assign({}, TEC_SOLO_MATERIAS),
    'Kibby': Object.assign({}, TEC_SOLO_MATERIAS),
    'Festón': Object.assign({}, TEC_SOLO_MATERIAS),
  };
  const PELO_LABEL = Object.fromEntries([].concat(...Object.values(TECNICOS_POR_TELAR).map(c => c.pelos)));
  const sinAcentos = (x) => String(x || '').normalize('NFD').replace(/[\u0300-\u036f]/g, '').trim().toLowerCase();
  // los nombres largos primero: "Tufting Bucle" no puede quedarse en "Tufting"
  const TELARES_TECNICOS = Object.keys(TECNICOS_POR_TELAR).sort((a, b) => b.length - a.length);
  function telarTecnico(telar) {
    const k = sinAcentos(telar);
    return TELARES_TECNICOS.find(t => k.startsWith(sinAcentos(t))) || '';
  }
  function esTecnico(telar) { return !!telarTecnico(telar); }
  function configTecnica(telar) { return TECNICOS_POR_TELAR[telarTecnico(telar)] || TEC_BASE; }
  function pelosDe(telar) {
    const p = configTecnica(telar).pelos;
    return (p && p.length) ? p : PELOS_VARILLA;
  }
  // Construcción única del telar (Rapier, Colortec, los dos Tufting) →
  // [valor, etiqueta]; null si se elige
  function peloFijo(telar) {
    const p = configTecnica(telar).pelos || [];
    return p.length === 1 ? p[0] : null;
  }
  // Pinta el <select> de construcción del telar; con telar de construcción
  // única lo deja con ese valor, oculto, y enseña el texto fijo de al lado.
  function pintarConstruccion(sel, telar, valor, elFijo) {
    const fijo = peloFijo(telar);
    sel.innerHTML = (fijo ? [] : [['', '—']]).concat(pelosDe(telar))
      .map(([v, l]) => `<option value="${esc(v)}">${esc(l)}</option>`).join('');
    sel.value = fijo ? fijo[0] : (pelosDe(telar).some(([v]) => v === valor) ? valor : '');
    sel.hidden = !!fijo;
    if (elFijo) {
      elFijo.hidden = !fijo;
      elFijo.textContent = fijo ? fijo[1] : '';
    }
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
    if (init.body && typeof init.body !== 'string' && !(init.body instanceof FormData)) {
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

  // Buscador de cliente sobre un <input>: sugiere clientes de Navision (copia
  // de Rols One) y nombres ya usados en muestras; el texto libre sigue valiendo
  // (prospectos). opts: { clientesUsados: () => [nombres], onElegir: (it) => {}, onTexto: () => {} }
  // it = { nombre, no (código Navision o null), ciudad }
  function montarBuscadorCliente(input, opts) {
    const o = opts || {};
    const box = document.createElement('div');
    box.className = 'ms-sug';
    box.hidden = true;
    input.insertAdjacentElement('afterend', box);
    let timer = null, items = [], activo = -1;
    function cerrar() { box.hidden = true; box.innerHTML = ''; items = []; activo = -1; }
    function marcar() {
      [...box.querySelectorAll('.ms-sug-it')].forEach((el, i) => el.classList.toggle('activo', i === activo));
    }
    function elegir(it) {
      if (!it) return;
      input.value = it.nombre;
      cerrar();
      if (o.onElegir) o.onElegir(it);
    }
    function pintar(nav, usados, q, disponible) {
      items = [];
      let html = '';
      const qk = q.toLowerCase();
      nav.forEach(c => {
        items.push({ nombre: c.nombre, no: c.no, ciudad: c.ciudad || '', alias: c.alias || '' });
        const alias = (c.alias && c.alias.toLowerCase() !== c.nombre.toLowerCase()) ? c.alias : '';
        // Si el texto no está en el nombre ni en el código, enseñamos por qué
        // ha salido (alias o e-mail de facturación) para que no parezca un error.
        const porEmail = c.email && c.email.toLowerCase().includes(qk) && !c.nombre.toLowerCase().includes(qk) && !(c.no || '').toLowerCase().includes(qk);
        const partes = [esc(c.no || '')];
        if (alias) partes.push(`alias <b>${esc(alias)}</b>`);
        if (c.ciudad) partes.push(esc(c.ciudad));
        if (porEmail) partes.push(`e-mail ${esc(c.email)}`);
        html += `<div class="ms-sug-it" data-i="${items.length - 1}"><span class="ms-sug-tag">Navision</span>` +
                `<span class="ms-sug-nom">${esc(c.nombre)}${alias ? ` <span class="ms-sug-alias">${esc(alias)}</span>` : ''}</span><span class="ms-sug-sub">${partes.join(' · ')}</span></div>`;
      });
      usados.forEach(n => {
        items.push({ nombre: n, no: null, ciudad: '' });
        html += `<div class="ms-sug-it" data-i="${items.length - 1}"><span class="ms-sug-tag usado">Ya usado</span><span class="ms-sug-nom">${esc(n)}</span></div>`;
      });
      html += `<div class="ms-sug-pie">${items.length ? '↑↓ y Intro para elegir · ' : ''}${disponible ? '' : 'Navision no responde ahora · '}se puede dejar «${esc(q)}» tal cual (prospecto)</div>`;
      box.innerHTML = html;
      box.hidden = false;
      activo = -1;
    }
    async function buscar() {
      const q = input.value.trim();
      if (q.length < 2) { cerrar(); return; }
      let nav = [], disponible = true;
      try {
        const d = await api('/api/muestras/clientes-navision?q=' + encodeURIComponent(q));
        nav = d.clientes || []; disponible = d.disponible !== false;
      } catch (e) { disponible = false; }
      if (input.value.trim() !== q || document.activeElement !== input) return;
      const qk = q.toLowerCase();
      const usados = (o.clientesUsados ? o.clientesUsados() : [])
        .filter(n => n.toLowerCase().includes(qk) && !nav.some(c => c.nombre.toLowerCase() === n.toLowerCase()))
        .slice(0, 6);
      pintar(nav.slice(0, 10), usados, q, disponible);
    }
    input.addEventListener('input', () => { clearTimeout(timer); if (o.onTexto) o.onTexto(); timer = setTimeout(buscar, 250); });
    input.addEventListener('focus', () => { if (input.value.trim().length >= 2) buscar(); });
    input.addEventListener('blur', () => setTimeout(cerrar, 150));
    input.addEventListener('keydown', (e) => {
      if (box.hidden || !items.length) return;
      if (e.key === 'ArrowDown') { e.preventDefault(); activo = Math.min(items.length - 1, activo + 1); marcar(); }
      else if (e.key === 'ArrowUp') { e.preventDefault(); activo = Math.max(0, activo - 1); marcar(); }
      else if (e.key === 'Enter' && activo >= 0) { e.preventDefault(); elegir(items[activo]); }
      else if (e.key === 'Escape') { cerrar(); }
    });
    box.addEventListener('mousedown', (e) => {
      const it = e.target.closest('.ms-sug-it');
      if (it) { e.preventDefault(); elegir(items[Number(it.dataset.i)]); }
    });
    return { cerrar, buscar };
  }

  // ---- Tabla de materias (una fila por cuerpo) --------------------------
  // Se usa igual en la ficha (autoguardado, opts.onCambio) y en el alta (se
  // lee al crear). El servidor tira las filas que no dicen nada de la materia.
  const MAX_MATERIAS = 12;
  function materiaUtil(f) {
    return !!((f.materia || '').trim() || (f.hilos_pua || '').trim() || (f.colorido || '').trim());
  }
  // Filas que vale la pena guardar, con las claves SIEMPRE en el mismo orden
  // (así comparar dos listas con JSON.stringify es fiable).
  function materiasUtiles(filas) {
    return (filas || []).filter(materiaUtil).map(f => ({
      cuerpo: (f.cuerpo || '').trim(), materia: (f.materia || '').trim(),
      hilos_pua: (f.hilos_pua || '').trim(), colorido: (f.colorido || '').trim(),
    }));
  }
  // opts: { listaMateriales, listaColoridos (ids de <datalist>), onCambio(filas, input), minimo }
  // opts: { listaMateriales, listaColoridos (ids de <datalist>), onCambio(filas, input),
  //         minimo, etiquetaCuerpo, conHilos }.  `configurar` cambia las columnas
  //  cuando cambia el telar (Pompón: Color y sin hilos púa).
  function montarTablaMaterias(root, opts) {
    const o = opts || {};
    const minimo = o.minimo === undefined ? 1 : o.minimo;
    let cfg = { etiquetaCuerpo: o.etiquetaCuerpo || 'Cuerpo', conHilos: o.conHilos !== false };
    let filas = [];
    root.classList.add('ms-materias');
    root.innerHTML =
      '<div class="ms-materias-cab"></div>' +
      '<div class="ms-materias-filas"></div>' +
      '<div class="ms-materias-pie"><button type="button" class="ms-link ms-materias-add">+ Añadir materia</button>' +
      '<span class="ms-materias-hint"></span></div>';
    const cab = root.querySelector('.ms-materias-cab');
    const cont = root.querySelector('.ms-materias-filas');
    const btnAdd = root.querySelector('.ms-materias-add');
    const hint = root.querySelector('.ms-materias-hint');
    const lm = o.listaMateriales ? ` list="${esc(o.listaMateriales)}"` : '';
    const lc = o.listaColoridos ? ` list="${esc(o.listaColoridos)}"` : '';
    const vacia = () => ({ cuerpo: '', materia: '', hilos_pua: '', colorido: '' });

    function pintarCab() {
      // "Cuerpo" a secas: "Nº de cuerpo" no cabe en la columna (va en el título del campo)
      const cols = [cfg.etiquetaCuerpo, 'Materia'].concat(cfg.conHilos ? ['Hilos púa'] : []).concat(['Colorido', '']);
      cab.innerHTML = cols.map(c => `<span>${esc(c)}</span>`).join('');
      root.classList.toggle('sin-hilos', !cfg.conHilos);
    }
    function htmlFila(f, i) {
      const et = esc(cfg.etiquetaCuerpo);
      return `<div class="ms-materia">` +
        `<input type="text" class="cuerpo" maxlength="20" value="${esc(f.cuerpo || '')}" placeholder="${i + 1}" title="${et}" aria-label="${et}" autocomplete="off" />` +
        `<input type="text" class="materia" maxlength="200" value="${esc(f.materia || '')}" placeholder="Ej. Lana 100 3/c" title="Materia" aria-label="Materia" autocomplete="off"${lm} />` +
        (cfg.conHilos ? `<input type="text" class="hilos" maxlength="40" value="${esc(f.hilos_pua || '')}" placeholder="Ej. 3" title="Hilos púa" aria-label="Hilos púa" autocomplete="off" />` : '') +
        `<input type="text" class="colorido" maxlength="120" value="${esc(f.colorido || '')}" placeholder="Ej. CREMA" title="Colorido" aria-label="Colorido" autocomplete="off"${lc} />` +
        `<button type="button" class="ms-materia-x" title="Quitar esta materia" aria-label="Quitar esta materia">×</button></div>`;
    }
    function repintar() {
      cont.innerHTML = filas.map(htmlFila).join('');
      btnAdd.disabled = filas.length >= MAX_MATERIAS;
      hint.textContent = filas.length >= MAX_MATERIAS ? `máximo ${MAX_MATERIAS} materias` : '';
    }
    function leer() {
      return [...cont.querySelectorAll('.ms-materia')].map((d, i) => {
        const h = d.querySelector('.hilos');
        return {
          cuerpo: d.querySelector('.cuerpo').value, materia: d.querySelector('.materia').value,
          // sin columna de hilos púa (Pompón) se conserva lo que hubiera
          hilos_pua: h ? h.value : ((filas[i] || {}).hilos_pua || ''),
          colorido: d.querySelector('.colorido').value,
        };
      });
    }
    function pintar(nuevas) {
      filas = (nuevas || []).map(f => Object.assign(vacia(), {
        cuerpo: f.cuerpo || '', materia: f.materia || '', hilos_pua: f.hilos_pua || '', colorido: f.colorido || '' }));
      while (filas.length < minimo) filas.push(vacia());
      repintar();
    }
    function configurar(nuevo) {
      if (cont.querySelector('.ms-materia')) filas = leer();
      cfg = Object.assign({}, cfg, nuevo || {});
      pintarCab();
      repintar();
    }
    cont.addEventListener('change', (e) => {
      if (!e.target.matches('input')) return;
      filas = leer();
      if (o.onCambio) o.onCambio(filas, e.target);
    });
    cont.addEventListener('click', (e) => {
      const b = e.target.closest('.ms-materia-x');
      if (!b) return;
      const i = [...cont.querySelectorAll('.ms-materia')].indexOf(b.closest('.ms-materia'));
      filas = leer();
      filas.splice(i, 1);
      while (filas.length < minimo) filas.push(vacia());
      repintar();
      if (o.onCambio) o.onCambio(filas, null);
    });
    btnAdd.addEventListener('click', () => {
      filas = leer();
      if (filas.length >= MAX_MATERIAS) return;
      // el nº se propone (1, 2, 3…); la fila no se guarda hasta que diga algo de la materia
      filas.push(Object.assign(vacia(), { cuerpo: String(filas.length + 1) }));
      repintar();
      const ult = cont.querySelector('.ms-materia:last-child .materia');
      if (ult) ult.focus();
    });
    pintarCab();
    pintar([]);
    return { pintar, leer, utiles: () => materiasUtiles(leer()), configurar };
  }

  window.MS = { ESTADOS, ESTADOS_LABEL, ESTADOS_FLUJO, FLUJO_PRINT, FLUJO_TELAR, FLUJO_POMPON, flujoDe, flujoQueContiene, etiquetaEstado,
    PRIO_LABEL, esc, fmtFecha, fmtFechaHora, hoyISO, fmtNum,
    TECNICOS_POR_TELAR, PELO_LABEL, esTecnico, configTecnica, pelosDe, peloFijo, pintarConstruccion,
    numeroHtml, estadoPill, prioPill, tipoTag, clienteHtml, colorearPrio, api, esAdmin, llenarSelect, llenarSelectPersonas, montarBuscadorCliente,
    materiasUtiles, montarTablaMaterias, MAX_MATERIAS };
})();
