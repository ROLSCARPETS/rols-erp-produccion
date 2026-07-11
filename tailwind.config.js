/**
 * Config de Tailwind para compilar el CSS estático del ERP (solo las clases
 * realmente usadas). Sustituye el CDN `cdn.tailwindcss.com` en producción, que
 * el propio Tailwind desaconseja usar en prod (recompila en el navegador).
 *
 * Regenerar tras cambiar clases en las plantillas/JS: descargar el CLI oficial
 * de Tailwind v3 (github.com/tailwindlabs/tailwindcss/releases) y correr desde
 * la raíz del repo:
 *   tailwindcss -c tailwind.config.js -i tailwind.input.css -o static/tailwind.css --minify
 *
 * `content` escanea plantillas Y el JS (las tablas/chips se pintan desde JS con
 * clases Tailwind, así que hay que mirar ambos para no perder estilos).
 */
module.exports = {
  content: [
    "./templates/**/*.html",
    "./static/**/*.js",
  ],
  theme: { extend: {} },
  plugins: [],
}
