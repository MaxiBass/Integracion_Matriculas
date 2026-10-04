// Pruebas de la lógica del panel (lo que no toca el DOM). Sin dependencias:
//
//   node tests/test_panel.mjs
//
// Todas las matrículas y nombres son inventados: este repositorio es público.

import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

// Se importa desde una URL data: porque Node trata los .js como CommonJS y no
// queremos un package.json dentro de la integración (HACS lo copiaría a HA).
const raiz = join(dirname(fileURLToPath(import.meta.url)), "..");
const fuente = readFileSync(join(raiz, "custom_components/matriculas/frontend/matriculas-panel.js"), "utf-8");
const p = await import(`data:text/javascript;base64,${Buffer.from(fuente).toString("base64")}`);

const fallos = [];
function comprobar(condicion, etiqueta) {
  console.log(`  ${condicion ? "OK   " : "FALLO"} ${etiqueta}`);
  if (!condicion) fallos.push(etiqueta);
}
const igual = (a, b) => JSON.stringify(a) === JSON.stringify(b);

console.log("\nPanel — lógica");

comprobar(p.normalizar(" 1234-bcd ") === "1234BCD", "normalizar quita espacios y guiones y pasa a mayúsculas");
comprobar(p.formatoPlaca("1234BCD") === "1234 BCD", "formato español con espacio");
comprobar(p.formatoPlaca("M1234AB") === "M1234AB", "otros formatos se dejan tal cual");
comprobar(p.sinTildes("Tío Ramón") === "tio ramon", "sinTildes");

const fichas = [
  { matricula: "1234BCD", nombre: "Abuela", vista: { ultima: "2026-09-20T10:00:00Z", veces: 3 } },
  { matricula: "5678FGH", nombre: "Tío Ramón", vista: { ultima: "2026-09-24T10:00:00Z", veces: 1 } },
  { matricula: "9012JKL", nombre: "reparto", vista: null },
];
comprobar(p.filtrar(fichas, "ramon").length === 1, "buscar por nombre sin tildes ni mayúsculas");
comprobar(p.filtrar(fichas, "1234 b").length === 1, "buscar por matrícula con espacio");
comprobar(p.filtrar(fichas, "  ").length === 3, "búsqueda vacía no filtra");
comprobar(
  igual(p.ordenar(fichas, "nombre").map((f) => f.nombre), ["Abuela", "reparto", "Tío Ramón"]),
  "ordenar por nombre, sin distinguir mayúsculas"
);
comprobar(
  igual(p.ordenar(fichas, "ultima").map((f) => f.matricula), ["5678FGH", "1234BCD", "9012JKL"]),
  "ordenar por última visita: las nunca vistas al final"
);
comprobar(
  igual(p.ordenar(fichas, "veces").map((f) => f.matricula), ["1234BCD", "5678FGH", "9012JKL"]),
  "ordenar por más vistas"
);
comprobar(fichas[0].matricula === "1234BCD", "ordenar no modifica la lista original");
comprobar(new p.MatriculasPanel()._orden === "ultima", "registradas: por defecto, la última visita arriba");

// Lo que llega del servidor (desconocidas de más a menos vistas, ignoradas
// por matrícula, historial por hora de cierre) se reordena en el panel.
const desconocidas = [
  { matricula: "1111AAA", veces: 5, ultima: "2026-09-20T10:00:00+00:00" },
  { matricula: "2222BBB", veces: 1, ultima: "2026-09-28T12:16:17+00:00" },
  { matricula: "3333CCC", veces: 2, ultima: "2026-09-25T08:00:00+00:00" },
];
comprobar(
  igual(p.recientesPrimero(desconocidas, "ultima").map((v) => v.matricula), ["2222BBB", "3333CCC", "1111AAA"]),
  "desconocidas: la vista más recientemente arriba, aunque se haya visto menos"
);
const historial = [
  { matricula: "2222BBB", hora: "2026-09-28T12:18:59+00:00" },
  { matricula: "2222BBB", hora: "2026-09-28T12:18:43+00:00" },
  { matricula: "4444DDD", hora: "2026-09-28T12:19:30+00:00" },
];
comprobar(
  igual(p.recientesPrimero(historial, "hora").map((h) => h.hora.slice(11, 19)), ["12:19:30", "12:18:59", "12:18:43"]),
  "historial: por la hora de la detección, no por el orden en que se cerró"
);
const ignoradas = [
  { matricula: "1111AAA", desde: "2026-09-26T09:00:00+00:00" },
  { matricula: "5555EEE" },
  { matricula: "3333CCC", desde: "2026-09-27T09:00:00+00:00" },
];
comprobar(
  igual(p.recientesPrimero(ignoradas, "desde").map((i) => i.matricula), ["3333CCC", "1111AAA", "5555EEE"]),
  "ignoradas: la última ignorada arriba; sin fecha, al final"
);
comprobar(desconocidas[0].matricula === "1111AAA", "recientesPrimero no modifica la lista original");

const existentes = fichas.map((f) => f.matricula);
const form = { matricula: "2468-dfg", nombre: " Nuevo ", avisar: true, abrir: false, notas: "", caduca: "" };
let r = p.peticionGuardar("nuevo", "", form, existentes);
comprobar(
  r.servicio === "guardar" && igual(r.datos, { matricula: "2468DFG", nombre: "Nuevo", avisar: true, abrir: false, notas: "" }),
  "nueva: guardar, sin caducidad si está vacía"
);
r = p.peticionGuardar("nuevo", "", { ...form, caduca: "2026-12-31" }, existentes);
comprobar(r.datos.caduca === "2026-12-31", "nueva con caducidad");

function lanza(fn, texto) {
  try {
    fn();
    return false;
  } catch (err) {
    return err.message.includes(texto);
  }
}
comprobar(lanza(() => p.peticionGuardar("nuevo", "", { ...form, matricula: "1234 bcd" }, existentes), "ya está registrada"),
  "nueva que ya existe: error claro en vez de sobrescribirla");
comprobar(lanza(() => p.peticionGuardar("nuevo", "", { ...form, nombre: "  " }, existentes), "nombre"), "sin nombre: error");
comprobar(lanza(() => p.peticionGuardar("nuevo", "", { ...form, matricula: "-" }, existentes), "matrícula"), "sin matrícula: error");

r = p.peticionGuardar("editar", "1234BCD", { ...form, matricula: "1234BCD" }, existentes);
comprobar(r.servicio === "editar" && r.datos.matricula === "1234BCD" && !("nueva_matricula" in r.datos),
  "editar sin cambiar la matrícula");
comprobar(r.datos.caduca === "", "editar con caducidad vacía la quita");
r = p.peticionGuardar("editar", "1234BCD", { ...form, matricula: "1234BCF" }, existentes);
comprobar(r.datos.nueva_matricula === "1234BCF" && r.datos.matricula === "1234BCD", "editar la matrícula la renombra");
comprobar(lanza(() => p.peticionGuardar("editar", "1234BCD", { ...form, matricula: "5678FGH" }, existentes), "ya está registrada"),
  "renombrar encima de otra: error");

const ahora = Date.parse("2026-09-25T12:00:00Z");
comprobar(p.hace("2026-09-25T11:59:30Z", ahora) === "ahora mismo", "hace: segundos");
comprobar(p.hace("2026-09-25T09:00:00Z", ahora) === "hace 3 horas", `hace: horas (${p.hace("2026-09-25T09:00:00Z", ahora)})`);
comprobar(p.hace("2026-09-24T12:00:00Z", ahora) === "ayer", `hace: ayer (${p.hace("2026-09-24T12:00:00Z", ahora)})`);
comprobar(p.hace("", ahora) === "", "hace: vacío");
comprobar(p.fechaLarga("2026-10-12") === "12 oct 2026", "fechaLarga sin desfase de zona horaria");
comprobar(p.estaCaducada("2026-09-24", "2026-09-25") && !p.estaCaducada("2026-09-25", "2026-09-25"),
  "caduca al día siguiente de la fecha indicada");

comprobar(p.esc(`<img src=x onerror="a">'`) === "&lt;img src=x onerror=&quot;a&quot;&gt;&#39;", "esc neutraliza HTML");
comprobar(
  p.mensajeError({ code: "service_validation_error", translation_key: "ya_existe", translation_placeholders: { matricula: "1234BCD" } })
    === "La matrícula 1234BCD ya está registrada.",
  "mensajeError traduce los errores de la integración"
);
comprobar(p.mensajeError(new Error("Escribe el nombre.")) === "Escribe el nombre.", "mensajeError de validación local");
comprobar(p.mensajeError({ code: "x", message: "Otro fallo" }) === "Otro fallo", "mensajeError desconocido: el mensaje tal cual");
comprobar(p.urlFoto("1758.4-abc") === "/api/frigate/notifications/1758.4-abc/thumbnail.jpg", "url de la foto de Frigate");
comprobar(p.urlFoto("") === "", "sin id no hay foto");

// Sugerencias de matrículas mal guardadas
comprobar(p.veces(1) === "1 vez" && p.veces(3) === "3 veces", "singular y plural de veces");
const corr = p.textoSugerencia({
  id: "correccion_1234bcd_1234bcf", tipo: "correccion", matricula: "1234BCD", propuesta: "1234BCF",
  nombre: "Abuela", veces_propuesta: 3, veces_guardada: 0,
});
comprobar(corr.titulo === "¿1234 BCD está mal guardada?", "título de corrección");
comprobar(corr.detalle.includes("3 veces como 1234 BCF") && corr.detalle.includes("0 veces como 1234 BCD"),
  `explica la evidencia: ${corr.detalle}`);
comprobar(igual(corr.acciones.map((a) => a.opcion), ["corregir", "otro_coche", "descartar"]) && corr.acciones[0].principal,
  "corrección: corregir (destacada), otro coche o descartar");
const dup = p.textoSugerencia({
  id: "duplicado_0123knn_0123knw", tipo: "duplicado", matricula: "0123KNN", otra: "0123KNW",
  nombre: "L", nombre_otra: "L2", veces: 0, veces_otra: 2, sobra: "0123KNN",
});
comprobar(dup.acciones[0].matricula === "0123KNN" && dup.acciones[0].principal && !dup.acciones[1].principal,
  "duplicado: destaca eliminar la que nunca se ha leído");
r = p.peticionGuardar("nuevo", "", { ...form, matricula: "1234BCF", abrir: false }, existentes, "correccion_1234bcd_1234bcf");
comprobar(r.servicio === "resolver_sugerencia" && r.datos.accion === "otro_coche" && r.datos.id === "correccion_1234bcd_1234bcf"
  && r.datos.abrir === false && r.datos.nombre === "Nuevo",
  "«es otro coche» registra y resuelve la sugerencia en una sola llamada");

// Botón del menú: como el ha-menu-button de HA, solo si la barra lateral no se ve.
const panel = new p.MatriculasPanel();
const menu = (narrow, dockedSidebar) => {
  panel.narrow = narrow;
  panel.hass = { dockedSidebar };
  return panel._verMenu();
};
comprobar(!menu(false, "docked"), "menú oculto con la barra lateral a la vista");
comprobar(menu(true, "docked"), "menú visible en pantalla estrecha");
comprobar(menu(false, "always_hidden"), "menú visible si la barra lateral está siempre oculta");

console.log();
if (fallos.length) {
  console.log(`${fallos.length} FALLOS`);
  process.exit(1);
}
console.log("Todo OK");
