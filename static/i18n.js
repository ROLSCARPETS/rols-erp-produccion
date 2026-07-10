// ============================================================
// i18n compartido para todas las páginas de la calculadora.
// Idiomas: español, inglés, francés, portugués, alemán, italiano,
// holandés, polaco (los mismos que consulta-stock).
//   - Carga el JSON del idioma actual + es (fallback).
//   - Aplica traducciones a [data-i18n], [data-i18n-html],
//     [data-i18n-placeholder], [data-i18n-title].
//   - Pinta el selector de banderas en la sidebar.
//   - Persistencia en localStorage clave "calc-lang".
// ============================================================

const SUPPORTED_LANGS = ['es', 'en', 'fr', 'pt', 'de', 'it', 'nl', 'pl'];

// La clave canonica entre todas las apps de Rols One es 'app-lang' (la usa
// lang-switcher.js, la app de stock y la asistente). En el pasado calc
// guardaba aqui en 'calc-lang' — leemos eso como fallback y migramos.
let CURRENT_LANG = (() => {
  let saved = localStorage.getItem('app-lang');
  if (!saved || !SUPPORTED_LANGS.includes(saved)) {
    const legacy = localStorage.getItem('calc-lang');
    if (legacy && SUPPORTED_LANGS.includes(legacy)) {
      saved = legacy;
      localStorage.setItem('app-lang', legacy);
    }
  }
  return (saved && SUPPORTED_LANGS.includes(saved)) ? saved : 'es';
})();

const TRANSLATIONS = {};

function _i18nLookup(key, lang) {
  let val = TRANSLATIONS[lang];
  if (!val) return null;
  for (const part of key.split('.')) {
    if (val && typeof val === 'object') val = val[part];
    else return null;
    if (val === undefined) return null;
  }
  return val;
}

function t(key, params) {
  let val = _i18nLookup(key, CURRENT_LANG);
  if (val == null && CURRENT_LANG !== 'es') val = _i18nLookup(key, 'es');
  if (val == null) return key;
  if (typeof val === 'string' && params) {
    return val.replace(/\{(\w+)\}/g, (_, k) => params[k] !== undefined ? params[k] : `{${k}}`);
  }
  return val;
}

async function loadTranslations(lang) {
  if (TRANSLATIONS[lang]) return;
  try {
    const res = await fetch(`/static/i18n/${lang}.json`);
    if (res.ok) TRANSLATIONS[lang] = await res.json();
  } catch (e) {
    console.warn(`[i18n] error cargando ${lang}.json`, e);
  }
}

function applyStaticTranslations() {
  document.querySelectorAll('[data-i18n]').forEach(el => {
    const v = t(el.getAttribute('data-i18n'));
    if (typeof v === 'string') el.textContent = v;
  });
  document.querySelectorAll('[data-i18n-html]').forEach(el => {
    const v = t(el.getAttribute('data-i18n-html'));
    if (typeof v === 'string') el.innerHTML = v;
  });
  document.querySelectorAll('[data-i18n-placeholder]').forEach(el => {
    const v = t(el.getAttribute('data-i18n-placeholder'));
    if (typeof v === 'string') el.setAttribute('placeholder', v);
  });
  document.querySelectorAll('[data-i18n-title]').forEach(el => {
    const v = t(el.getAttribute('data-i18n-title'));
    if (typeof v === 'string') el.setAttribute('title', v);
  });
}

function highlightActiveLangBtn() {
  document.querySelectorAll('.lang-btn').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.lang === CURRENT_LANG);
  });
}

async function initI18n() {
  await Promise.all([loadTranslations(CURRENT_LANG), loadTranslations('es')]);
  applyStaticTranslations();
  highlightActiveLangBtn();
  document.querySelectorAll('.lang-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      const newLang = btn.dataset.lang;
      if (!newLang || newLang === CURRENT_LANG) return;
      localStorage.setItem('app-lang', newLang);
      location.reload();
    });
  });
  // Notificar a otros módulos por si quieren re-render dinámico
  document.dispatchEvent(new CustomEvent('i18n:ready', { detail: { lang: CURRENT_LANG } }));
}

// Expose helpers globales
window.CURRENT_LANG = CURRENT_LANG;
window.t = t;
window.applyI18n = applyStaticTranslations;
window.initI18n = initI18n;

// Auto-init en cuanto el DOM esté listo
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', initI18n);
} else {
  initI18n();
}
