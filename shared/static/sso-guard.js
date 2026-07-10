/* ============================================================
 * Rols One — SSO guard
 *
 * Pequeño script que cualquier app de la suite (calc, stock,
 * futuras) embebe en su <head>. Se ejecuta inline (sin defer) al
 * cargar la página y:
 *
 *   1. Pregunta a CUENTAS quién está logueado vía
 *      fetch('http://localhost:5054/api/whoami', credentials:'include').
 *   2. Si 200 → guarda el usuario en window.__rolsUser y dispara
 *      un evento 'rols:sso-ok' para que el resto de la app reaccione.
 *   3. Si 401 → redirige a la página de login de cuentas con
 *      ?next=URL_ACTUAL (vuelve aquí tras loguearse).
 *   4. Si cuentas no está arrancado (network error) → deja
 *      pasar pero marca <html class="sso-offline"> para que el
 *      widget del chat se pinte en estado offline.
 *
 * Esto reemplaza al login individual de cada app: cuentas es
 * el único Identity Provider. Las apps confían en él.
 * ============================================================ */
(function () {
    "use strict";

    // Dónde vive CUENTAS (Identity Provider):
    //   - LOCAL: cada app corre en su puerto, cuentas en :5054.
    //   - PRODUCCIÓN: la suite va COMPUESTA bajo un único dominio y cuentas
    //     se sirve en /cuentas (mismo origen). Eso hace el SSO trivial: el
    //     fetch a /cuentas/api/whoami es same-origin (sin CORS ni mixed-content)
    //     y la cookie de sesión viaja sola.
    var _host = window.location.hostname;
    var _isLocal = (_host === "localhost" || _host === "127.0.0.1");
    var CUENTAS_BASE = _isLocal ? "http://localhost:5054" : "/cuentas";

    // No correr el guard dentro de las propias páginas de CUENTAS (el IdP:
    // login, admin) — evita bucle de redirecciones. En prod son /cuentas/*,
    // en local es el origin :5054. El resto de apps (incl. el asistente, que
    // ahora es consumidor del SSO) SÍ corren el guard.
    if (_isLocal) {
        if (window.location.origin === CUENTAS_BASE) return;
    } else if (window.location.pathname.indexOf("/cuentas") === 0) {
        return;
    }

    // Evitar guard en peticiones internas (asset, ajax) — el script va
    // a ir en <head> de las pantallas HTML pero por si acaso.
    if (window.__rolsSsoStarted) return;
    window.__rolsSsoStarted = true;

    var htmlEl = document.documentElement;
    htmlEl.classList.add("sso-checking");

    // ------------------------------------------------------------------
    // Interceptor de fetch: añade el header 'X-Rols-User-Rol' a todas las
    // peticiones del mismo origen. El backend lo usa para filtrar refs
    // visibles (representante solo ve stock_rols activo).
    //
    // El rol se cachea en sessionStorage cuando whoami responde, asi las
    // siguientes peticiones lo encuentran sin esperar al fetch async.
    // Si por alguna razon no hay rol cacheado (primera carga del SSO),
    // el server lo trata como "rol desconocido" = filtro restrictivo.
    // ------------------------------------------------------------------
    (function patchFetch() {
        if (window.__rolsFetchPatched) return;
        window.__rolsFetchPatched = true;
        var origFetch = window.fetch.bind(window);
        window.fetch = function (input, init) {
            try {
                var url = typeof input === "string" ? input : (input && input.url);
                // Solo añadimos el header a peticiones que van al mismo
                // origen (calc 5051 a calc 5051, stock 5050 a stock 5050).
                // Las peticiones cross-origin a asistente NO lo necesitan
                // (el asistente tiene la sesion completa).
                var esMismoOrigen = !url || url.indexOf("http") !== 0 ||
                                    url.indexOf(window.location.origin) === 0;
                if (esMismoOrigen) {
                    var rol = (window.__rolsUser && window.__rolsUser.rol) ||
                              sessionStorage.getItem("rolsUserRol") || "";
                    // Username: identifica al usuario para el estado por-usuario
                    // del backend (p.ej. el presupuesto activo de la calc).
                    var uname = (window.__rolsUser && window.__rolsUser.username) ||
                                sessionStorage.getItem("rolsUserName") || "";
                    init = init || {};
                    init.headers = new Headers(init.headers || {});
                    if (rol && !init.headers.has("X-Rols-User-Rol")) {
                        init.headers.set("X-Rols-User-Rol", rol);
                    }
                    if (uname && !init.headers.has("X-Rols-User-Name")) {
                        init.headers.set("X-Rols-User-Name", uname);
                    }
                }
            } catch (e) { /* nunca bloquear la peticion por esto */ }
            return origFetch(input, init);
        };
    })();

    function goLogin() {
        var next = encodeURIComponent(window.location.href);
        window.location.replace(CUENTAS_BASE + "/login?next=" + next);
    }
    // NOTA: la inyeccion dinamica de "Gestión de usuarios" en el sidebar
    // se elimino al pasar la sub-seccion bajo /configuracion. Los admins
    // ven la card "Gestión de usuarios" dentro de la pagina de
    // Configuracion, que la oculta/muestra segun __rolsUser.rol.

    fetch(CUENTAS_BASE + "/api/whoami", {
        credentials: "include",
        cache: "no-store",
    })
        .then(function (r) {
            if (r.status === 401) {
                goLogin();
                return null;
            }
            if (!r.ok) {
                // 5xx u otro: tratar como offline (no romper la app)
                htmlEl.classList.remove("sso-checking");
                htmlEl.classList.add("sso-offline");
                return null;
            }
            return r.json();
        })
        .then(function (me) {
            if (!me) return;
            window.__rolsUser = me;
            // Cache para que el interceptor de fetch tenga el rol al
            // primer load (sessionStorage sobrevive recargas de la misma
            // pestaña pero se borra al cerrar el navegador, suficiente).
            try {
                if (me.rol) sessionStorage.setItem("rolsUserRol", me.rol);
                if (me.username) sessionStorage.setItem("rolsUserName", me.username);
            } catch (e) {}
            htmlEl.classList.remove("sso-checking");
            htmlEl.classList.add("sso-ok");
            if (me.rol === "admin") {
                htmlEl.classList.add("sso-admin");
            }
            // Sincronizar el idioma preferido del usuario con localStorage.
            // Si difiere de lo que el navegador tiene cacheado, recargamos
            // UNA SOLA VEZ (sentinel en sessionStorage evita loops). Asi el
            // user ve la pagina en su idioma sea cual sea el equipo desde
            // el que entre, sin tener que ajustar nada manualmente.
            try {
                var idiomaUser = me.idioma;
                if (idiomaUser) {
                    var actual = localStorage.getItem("app-lang");
                    if (actual !== idiomaUser && !sessionStorage.getItem("__rolsLangSynced")) {
                        sessionStorage.setItem("__rolsLangSynced", "1");
                        localStorage.setItem("app-lang", idiomaUser);
                        window.location.reload();
                        return; // no disparar evento; al recargar se hara solo
                    }
                }
            } catch (e) { /* ignorar errores de storage en modo privado */ }
            // Evento para que la app reaccione (ej. pintar nombre en sidebar)
            try {
                window.dispatchEvent(new CustomEvent("rols:sso-ok", { detail: me }));
            } catch (e) { /* IE/old browsers: ignorar */ }
        })
        .catch(function () {
            // Network error: asistente no arrancado. La app sigue
            // funcionando, solo el widget chat estará en modo offline.
            htmlEl.classList.remove("sso-checking");
            htmlEl.classList.add("sso-offline");
        });
})();
