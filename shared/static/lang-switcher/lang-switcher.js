/* ============================================================
 * Rols One — Selector de idioma (shared)
 *
 * Componente auto-contenido. Cualquier app de la suite incluye:
 *   <link rel="stylesheet" href="static/lang-switcher/lang-switcher.css">
 *   <script src="static/lang-switcher/lang-switcher.js" defer></script>
 *
 * Y en el HTML pone un placeholder (cualquier elemento vacio):
 *   <div data-lang-switcher></div>
 *
 * El script:
 *   1. Lee el idioma activo de localStorage('app-lang') (default 'es').
 *   2. Inyecta dentro de [data-lang-switcher] el boton + dropdown.
 *   3. Click en otra bandera -> guarda en localStorage y recarga.
 *      (La recarga es la forma actual de cambiar idioma en calc/stock;
 *      i18n.js lee localStorage al arrancar y aplica el JSON.)
 *
 * Si no hay [data-lang-switcher] en la pagina, no se monta nada.
 * ============================================================ */
(function () {
    "use strict";

    if (window.__rolsLangSwitcherMounted) return;
    window.__rolsLangSwitcherMounted = true;

    var IDIOMAS = [
        { code: "es", label: "Español",    flag: "fi-es" },
        { code: "en", label: "English",    flag: "fi-gb" },
        { code: "fr", label: "Français",   flag: "fi-fr" },
        { code: "pt", label: "Português",  flag: "fi-pt" },
        { code: "de", label: "Deutsch",    flag: "fi-de" },
        { code: "it", label: "Italiano",   flag: "fi-it" },
        { code: "nl", label: "Nederlands", flag: "fi-nl" },
        { code: "pl", label: "Polski",     flag: "fi-pl" },
    ];

    // CUENTAS (IdP) persiste la preferencia de idioma del usuario. Local :5054,
    // prod /cuentas (same-origin). Antes apuntaba al asistente (:5052).
    var _ssHost = window.location.hostname;
    var _ssLocal = (_ssHost === "localhost" || _ssHost === "127.0.0.1");
    var CUENTAS_BASE = _ssLocal ? "http://localhost:5054" : "/cuentas";

    function lang() {
        return localStorage.getItem("app-lang") || "es";
    }
    function setLang(code) {
        localStorage.setItem("app-lang", code);
        // Sentinel para evitar que sso-guard reseteo este idioma al
        // siguiente whoami: el usuario acaba de elegir, su intencion
        // gana. Persistimos al backend para que en su proximo login
        // desde otro equipo ya arranque en este idioma.
        try { sessionStorage.setItem("__rolsLangSynced", "1"); } catch (e) {}
        // Fire-and-forget: si falla (asistente caído, sesion expirada)
        // no bloqueamos la recarga local.
        try {
            fetch(CUENTAS_BASE + "/api/usuario/idioma", {
                method: "POST",
                credentials: "include",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ idioma: code }),
                keepalive: true,
            }).catch(function () { /* ignorar */ });
        } catch (e) { /* ignorar */ }
        location.reload();
    }
    function findIdioma(code) {
        return IDIOMAS.find(function (i) { return i.code === code; }) || IDIOMAS[0];
    }

    function mount() {
        var slots = document.querySelectorAll("[data-lang-switcher]");
        if (!slots.length) return;
        slots.forEach(function (slot) {
            if (slot.dataset.langMounted === "1") return;
            slot.dataset.langMounted = "1";

            var actual = findIdioma(lang());

            var wrap = document.createElement("div");
            wrap.className = "rols-lang";

            var btn = document.createElement("button");
            btn.type = "button";
            btn.className = "rols-lang-btn";
            btn.setAttribute("aria-haspopup", "menu");
            btn.setAttribute("aria-expanded", "false");
            btn.title = "Idioma";
            btn.innerHTML =
                '<span class="rols-lang-flag fi ' + actual.flag + '"></span>' +
                '<span class="rols-lang-code">' + actual.code.toUpperCase() + '</span>' +
                '<svg class="rols-lang-caret" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><polyline points="6 9 12 15 18 9"/></svg>';

            var menu = document.createElement("div");
            menu.className = "rols-lang-menu";
            menu.setAttribute("role", "menu");
            IDIOMAS.forEach(function (i) {
                var it = document.createElement("button");
                it.type = "button";
                it.className = "rols-lang-item" + (i.code === actual.code ? " active" : "");
                it.setAttribute("role", "menuitem");
                it.dataset.code = i.code;
                it.innerHTML =
                    '<span class="rols-lang-flag fi ' + i.flag + '"></span>' +
                    '<span class="rols-lang-label">' + i.label + '</span>' +
                    '<svg class="rols-lang-check" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><polyline points="20 6 9 17 4 12"/></svg>';
                it.addEventListener("click", function () {
                    if (i.code === actual.code) {
                        close();
                        return;
                    }
                    setLang(i.code);
                });
                menu.appendChild(it);
            });

            function open() {
                menu.classList.add("open");
                btn.setAttribute("aria-expanded", "true");
            }
            function close() {
                menu.classList.remove("open");
                btn.setAttribute("aria-expanded", "false");
            }
            btn.addEventListener("click", function (e) {
                e.stopPropagation();
                if (menu.classList.contains("open")) close();
                else open();
            });
            document.addEventListener("click", function (e) {
                if (!wrap.contains(e.target)) close();
            });
            document.addEventListener("keydown", function (e) {
                if (e.key === "Escape" && menu.classList.contains("open")) close();
            });

            wrap.appendChild(btn);
            wrap.appendChild(menu);
            slot.appendChild(wrap);
        });
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", mount);
    } else {
        mount();
    }
})();
