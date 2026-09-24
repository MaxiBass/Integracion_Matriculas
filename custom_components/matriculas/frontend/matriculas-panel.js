// Panel "Matrículas" de la barra lateral de Home Assistant.
//
// Sin dependencias ni paso de compilación: un custom element con Shadow DOM
// que usa las variables CSS del tema de HA. Lee los datos por el websocket
// `matriculas/suscribir` (llegan solos cada vez que algo cambia) y edita
// llamando a los servicios de la integración, que validan y dan los errores.
//
// La lógica que no toca el DOM se exporta para probarla con Node
// (tests/test_panel.mjs).

// ── Lógica pura ─────────────────────────────────────────────────────

export function normalizar(texto) {
  return String(texto ?? "").toUpperCase().replace(/[^0-9A-Z]/g, "");
}

export function sinTildes(texto) {
  return String(texto ?? "")
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase();
}

export function formatoPlaca(matricula) {
  const m = String(matricula ?? "");
  return /^\d{4}[A-Z]{3}$/.test(m) ? `${m.slice(0, 4)} ${m.slice(4)}` : m;
}

export function hace(iso, ahora = Date.now()) {
  const t = Date.parse(iso ?? "");
  if (Number.isNaN(t)) return "";
  const seg = Math.round((t - ahora) / 1000);
  const abs = Math.abs(seg);
  const rtf = new Intl.RelativeTimeFormat("es", { numeric: "auto" });
  if (abs < 60) return "ahora mismo";
  if (abs < 3600) return rtf.format(Math.round(seg / 60), "minute");
  if (abs < 86400) return rtf.format(Math.round(seg / 3600), "hour");
  if (abs < 86400 * 7) return rtf.format(Math.round(seg / 86400), "day");
  if (abs < 86400 * 30) return rtf.format(Math.round(seg / (86400 * 7)), "week");
  if (abs < 86400 * 365) return rtf.format(Math.round(seg / (86400 * 30)), "month");
  return rtf.format(Math.round(seg / (86400 * 365)), "year");
}

export function fechaHora(iso) {
  const t = Date.parse(iso ?? "");
  if (Number.isNaN(t)) return "";
  return new Date(t).toLocaleString("es-ES", {
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function fechaLarga(fechaIso) {
  // "2026-10-12" → "12 oct 2026", sin pasar por la zona horaria.
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(fechaIso ?? "");
  if (!m) return "";
  const meses = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sept", "oct", "nov", "dic"];
  return `${Number(m[3])} ${meses[Number(m[2]) - 1]} ${m[1]}`;
}

export function hoyIso(ahora = new Date()) {
  const dos = (n) => String(n).padStart(2, "0");
  return `${ahora.getFullYear()}-${dos(ahora.getMonth() + 1)}-${dos(ahora.getDate())}`;
}

export function estaCaducada(caduca, hoy = hoyIso()) {
  return Boolean(caduca) && caduca < hoy;
}

export function filtrar(elementos, texto) {
  const q = String(texto ?? "").trim();
  if (!q) return elementos;
  const qPlaca = normalizar(q);
  const qNombre = sinTildes(q);
  return elementos.filter(
    (e) =>
      (qPlaca && normalizar(e.matricula).includes(qPlaca)) ||
      sinTildes(e.nombre).includes(qNombre)
  );
}

export const ORDENES = {
  nombre: "Nombre",
  ultima: "Última visita",
  veces: "Más vistas",
  matricula: "Matrícula",
};

export function ordenar(fichas, criterio = "nombre") {
  const porNombre = (a, b) =>
    String(a.nombre).localeCompare(String(b.nombre), "es", { sensitivity: "base" }) ||
    String(a.matricula).localeCompare(String(b.matricula));
  const copia = [...fichas];
  if (criterio === "ultima") {
    return copia.sort(
      (a, b) =>
        String(b.vista?.ultima ?? "").localeCompare(String(a.vista?.ultima ?? "")) ||
        porNombre(a, b)
    );
  }
  if (criterio === "veces") {
    return copia.sort((a, b) => (b.vista?.veces ?? 0) - (a.vista?.veces ?? 0) || porNombre(a, b));
  }
  if (criterio === "matricula") {
    return copia.sort((a, b) => String(a.matricula).localeCompare(String(b.matricula)));
  }
  return copia.sort(porNombre);
}

// Decide qué servicio llamar con qué datos a partir del formulario. Lanza un
// Error con un mensaje para la persona si falta algo evidente; el resto de la
// validación la hace la integración.
export function peticionGuardar(modo, original, formulario, existentes = []) {
  const matricula = normalizar(formulario.matricula);
  const nombre = String(formulario.nombre ?? "").trim();
  if (matricula.length < 2) throw new Error("Escribe la matrícula.");
  if (!nombre) throw new Error("Escribe el nombre.");
  const comunes = {
    nombre,
    avisar: Boolean(formulario.avisar),
    abrir: Boolean(formulario.abrir),
    notas: String(formulario.notas ?? "").trim(),
  };
  const yaExiste = (m) =>
    new Error(`La matrícula ${formatoPlaca(m)} ya está registrada. Búscala en la lista para editarla.`);

  if (modo === "nuevo") {
    if (existentes.includes(matricula)) throw yaExiste(matricula);
    const datos = { matricula, ...comunes };
    if (formulario.caduca) datos.caduca = formulario.caduca;
    return { servicio: "guardar", datos };
  }
  // Al editar, una caducidad vacía la quita.
  const datos = { matricula: original, ...comunes, caduca: formulario.caduca || "" };
  if (matricula !== original) {
    if (existentes.includes(matricula)) throw yaExiste(matricula);
    datos.nueva_matricula = matricula;
  }
  return { servicio: "editar", datos };
}

export const TIPOS = {
  conocida: "Conocida",
  desconocida: "Desconocida",
  ignorada: "Ignorada",
  caducada: "Caducada",
};

export function urlFoto(frigateId, tipo = "thumbnail") {
  return frigateId ? `/api/frigate/notifications/${encodeURIComponent(frigateId)}/${tipo}.jpg` : "";
}

export function esc(texto) {
  return String(texto ?? "").replace(
    /[&<>"']/g,
    (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]
  );
}

// ── Elemento ────────────────────────────────────────────────────────

const ICONOS = {
  menu: "M3,6H21V8H3V6M3,11H21V13H3V11M3,16H21V18H3V16Z",
  mas: "M19,13H13V19H11V13H5V11H11V5H13V11H19V13Z",
  cerrar:
    "M19,6.41L17.59,5L12,10.59L6.41,5L5,6.41L10.59,12L5,17.59L6.41,19L12,13.41L17.59,19L19,17.59L13.41,12L19,6.41Z",
  buscar:
    "M9.5,3A6.5,6.5 0 0,1 16,9.5C16,11.11 15.41,12.59 14.44,13.73L14.71,14H15.5L20.5,19L19,20.5L14,15.5V14.71L13.73,14.44C12.59,15.41 11.11,16 9.5,16A6.5,6.5 0 0,1 3,9.5A6.5,6.5 0 0,1 9.5,3M9.5,5C7,5 5,7 5,9.5C5,12 7,14 9.5,14C12,14 14,12 14,9.5C14,7 12,5 9.5,5Z",
};

const icono = (nombre) =>
  `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="${ICONOS[nombre]}"></path></svg>`;

const placa = (m) => `<span class="placa"><span class="pais">E</span>${esc(formatoPlaca(m))}</span>`;

const MENSAJES_ERROR = {
  matricula_invalida: "«{matricula}» no es una matrícula válida: tiene que tener entre 2 y 10 letras o cifras.",
  nombre_vacio: "Falta el nombre.",
  no_existe: "La matrícula {matricula} no está registrada.",
  ya_existe: "La matrícula {matricula} ya está registrada.",
  ignorar_registrada: "La matrícula {matricula} está registrada; elimínala antes de ignorarla.",
  no_ignorada: "La matrícula {matricula} no estaba ignorada.",
  no_cargada: "La integración Matrículas no está cargada.",
};

export function mensajeError(err) {
  if (err instanceof Error && !err.translation_key) return err.message;
  const plantilla = MENSAJES_ERROR[err?.translation_key ?? err?.code];
  if (plantilla) {
    return plantilla.replace(/\{(\w+)\}/g, (_, k) => err.translation_placeholders?.[k] ?? "");
  }
  return err?.message || "No se ha podido completar la operación.";
}

const ESTILOS = `
:host {
  display: block;
  height: 100%;
  background: var(--primary-background-color, #fafafa);
  color: var(--primary-text-color, #212121);
  font-family: var(--ha-font-family-body, Roboto, system-ui, sans-serif);
  --mt-tarjeta: var(--card-background-color, #fff);
  --mt-texto2: var(--secondary-text-color, #727272);
  --mt-primario: var(--primary-color, #03a9f4);
  --mt-borde: var(--divider-color, rgba(0, 0, 0, 0.12));
  --mt-error: var(--error-color, #db4437);
  --mt-ok: var(--success-color, #43a047);
  --mt-aviso: var(--warning-color, #ffa600);
  --mt-radio: var(--ha-card-border-radius, 12px);
}
* { box-sizing: border-box; }
[hidden] { display: none !important; }
svg { width: 24px; height: 24px; fill: currentColor; flex: none; }
button { font: inherit; cursor: pointer; }
.cabecera {
  display: flex; align-items: center; gap: 8px;
  height: var(--header-height, 56px); padding: 0 12px;
  background: var(--app-header-background-color, var(--mt-primario));
  color: var(--app-header-text-color, #fff);
  position: sticky; top: 0; z-index: 2;
}
.cabecera h1 { font-size: 20px; font-weight: 400; margin: 0 0 0 8px; flex: 1; }
.icono { background: none; border: 0; color: inherit; padding: 8px; border-radius: 50%; display: inline-flex; }
.icono:hover { background: rgba(127, 127, 127, 0.15); }
.contenido { max-width: 960px; margin: 0 auto; padding: 12px 16px 96px; }
.pestanas { display: flex; gap: 4px; overflow-x: auto; border-bottom: 1px solid var(--mt-borde); margin-bottom: 12px; scrollbar-width: none; }
.pestana {
  background: none; border: 0; border-bottom: 2px solid transparent; color: var(--mt-texto2);
  padding: 10px 12px; white-space: nowrap; font-weight: 500;
}
.pestana[aria-selected="true"] { color: var(--mt-primario); border-bottom-color: var(--mt-primario); }
.contador { display: inline-block; min-width: 20px; padding: 0 6px; margin-left: 4px; border-radius: 10px; background: var(--mt-borde); color: var(--primary-text-color, #212121); font-size: 12px; line-height: 20px; text-align: center; }
.pestana[data-aviso="true"] .contador { background: var(--mt-aviso); color: #000; }
.herramientas { display: flex; gap: 8px; margin-bottom: 12px; flex-wrap: wrap; }
.busqueda { flex: 1 1 220px; display: flex; align-items: center; gap: 6px; padding: 0 12px; border: 1px solid var(--mt-borde); border-radius: 24px; background: var(--mt-tarjeta); color: var(--mt-texto2); }
.busqueda input { flex: 1; border: 0; outline: 0; background: none; color: var(--primary-text-color, #212121); font: inherit; padding: 10px 0; min-width: 0; }
select { font: inherit; padding: 8px 10px; border-radius: 24px; border: 1px solid var(--mt-borde); background: var(--mt-tarjeta); color: var(--primary-text-color, #212121); }
.boton { border: 0; border-radius: 20px; padding: 8px 16px; font-weight: 500; display: inline-flex; align-items: center; gap: 6px; }
.boton.principal { background: var(--mt-primario); color: var(--text-primary-color, #fff); }
.boton.secundario { background: none; color: var(--mt-primario); border: 1px solid var(--mt-borde); }
.boton.peligro { background: none; color: var(--mt-error); border: 1px solid var(--mt-error); }
.boton.peligro.confirmar { background: var(--mt-error); color: #fff; }
.boton svg { width: 18px; height: 18px; }
.lista { display: grid; gap: 8px; grid-template-columns: minmax(0, 1fr); }
.fila {
  display: flex; align-items: center; gap: 12px; width: 100%; text-align: left;
  background: var(--mt-tarjeta); color: inherit; border: 1px solid var(--mt-borde);
  border-radius: var(--mt-radio); padding: 10px 12px;
}
button.fila:hover { border-color: var(--mt-primario); }
.cuerpo { flex: 1; min-width: 0; display: grid; gap: 3px; }
.titulo { display: flex; align-items: center; gap: 10px; min-width: 0; }
.nombre { font-weight: 500; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; min-width: 0; }
.nombre.anonima { font-weight: 400; font-style: italic; color: var(--mt-texto2); }
.secundario { color: var(--mt-texto2); font-size: 13px; }
.chips { display: flex; gap: 6px; flex-wrap: wrap; }
.chip { font-size: 12px; line-height: 20px; padding: 0 8px; border-radius: 10px; border: 1px solid var(--mt-borde); color: var(--mt-texto2); }
.chip.si { border-color: var(--mt-ok); color: var(--mt-ok); }
.chip.mal { border-color: var(--mt-error); color: var(--mt-error); }
.chip.ojo { border-color: var(--mt-aviso); color: var(--mt-aviso); }
.acciones { display: flex; gap: 6px; flex-wrap: wrap; }
.placa {
  display: inline-flex; align-items: stretch; overflow: hidden; flex: none;
  background: #fff; color: #111; border: 2px solid #222; border-radius: 5px;
  font: 700 15px/24px "DIN Alternate", "Roboto Mono", ui-monospace, monospace; letter-spacing: 1px;
  padding-right: 6px;
}
.placa .pais { background: #1f4fa3; color: #fff; font-size: 9px; padding: 0 3px; margin-right: 6px; display: flex; align-items: flex-end; letter-spacing: 0; }
.foto { width: 72px; height: 54px; flex: none; border-radius: 8px; overflow: hidden; background: var(--mt-borde); display: flex; }
.foto img { width: 100%; height: 100%; object-fit: cover; }
.foto.grande { width: 100%; height: 200px; }
.vacio { text-align: center; color: var(--mt-texto2); padding: 40px 16px; line-height: 1.5; }
.error-carga { color: var(--mt-error); }
.fondo {
  position: fixed; inset: 0; background: rgba(0, 0, 0, 0.45); z-index: 10;
  display: flex; align-items: center; justify-content: center; padding: 16px;
}
.dialogo {
  background: var(--mt-tarjeta); color: var(--primary-text-color, #212121);
  border-radius: 16px; width: 100%; max-width: 480px; max-height: calc(100% - 32px);
  overflow: auto; padding: 20px; display: grid; gap: 14px;
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.3);
}
.dialogo h2 { margin: 0; font-size: 20px; font-weight: 400; display: flex; align-items: center; justify-content: space-between; }
.campo { display: grid; gap: 4px; }
.campo label { font-size: 13px; color: var(--mt-texto2); }
.campo input, .campo textarea {
  font: inherit; padding: 10px 12px; border: 1px solid var(--mt-borde); border-radius: 8px;
  background: var(--primary-background-color, #fafafa); color: var(--primary-text-color, #212121);
}
.campo input:focus, .campo textarea:focus { outline: 2px solid var(--mt-primario); outline-offset: -1px; }
#f-matricula { text-transform: uppercase; font-weight: 700; letter-spacing: 1px; }
.interruptor { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.interruptor span small { display: block; color: var(--mt-texto2); font-size: 12px; }
.interruptor input { width: 20px; height: 20px; accent-color: var(--mt-primario); flex: none; }
.mensaje-error { background: color-mix(in srgb, var(--mt-error) 12%, transparent); color: var(--mt-error); border-radius: 8px; padding: 10px 12px; }
.pie { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
.pie .hueco { flex: 1; }
.aviso {
  position: fixed; left: 50%; bottom: 24px; transform: translateX(-50%); z-index: 20;
  background: #323232; color: #fff; padding: 12px 20px; border-radius: 8px;
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.3); max-width: calc(100% - 32px);
}
@media (max-width: 600px) {
  .contenido { padding: 8px 8px 96px; }
  .fondo { align-items: flex-end; padding: 0; }
  .dialogo { border-radius: 16px 16px 0 0; max-height: 92%; padding-bottom: calc(20px + env(safe-area-inset-bottom, 0px)); }
  .foto { width: 60px; height: 45px; }
  .foto.grande { height: 160px; }
}
`;

const Base = typeof HTMLElement === "undefined" ? class {} : HTMLElement;

export class MatriculasPanel extends Base {
  constructor() {
    super();
    this._datos = null;
    this._errorCarga = "";
    this._pestana = "registradas";
    this._busqueda = "";
    this._orden = "nombre";
    this._dialogo = null;
    this._desuscribir = null;
    this._narrow = false;
    this._temporizadorAviso = null;
  }

  // HA sustituye `hass` en cada cambio de estado de toda la casa: aquí solo se
  // guarda. Los datos del panel llegan por la suscripción.
  set hass(hass) {
    const primero = !this._hass;
    this._hass = hass;
    this._actualizarMenu();
    if (primero && this.isConnected) this._suscribir();
  }

  get hass() {
    return this._hass;
  }

  set narrow(valor) {
    this._narrow = Boolean(valor);
    this._actualizarMenu();
  }

  // Igual que el ha-menu-button de HA: solo si la barra lateral no está a la vista.
  _verMenu() {
    return this._narrow || this._hass?.dockedSidebar === "always_hidden";
  }

  _actualizarMenu() {
    const boton = this.shadowRoot?.querySelector("#menu");
    if (boton) boton.hidden = !this._verMenu();
  }

  connectedCallback() {
    if (!this.shadowRoot) this._montar();
    if (this._hass) this._suscribir();
  }

  disconnectedCallback() {
    if (typeof this._desuscribir === "function") this._desuscribir();
    this._desuscribir = null;
  }

  async _suscribir() {
    if (this._desuscribir || !this._hass) return;
    this._desuscribir = "pendiente";
    try {
      const cancelar = await this._hass.connection.subscribeMessage(
        (datos) => {
          this._datos = datos;
          this._errorCarga = "";
          this._pintar();
        },
        { type: "matriculas/suscribir" }
      );
      if (this._desuscribir === "pendiente") this._desuscribir = cancelar;
      else cancelar();
    } catch (err) {
      this._desuscribir = null;
      this._errorCarga = mensajeError(err);
      this._pintar();
    }
  }

  // ── Estructura fija ──

  _montar() {
    const raiz = this.attachShadow({ mode: "open" });
    raiz.innerHTML = `
      <style>${ESTILOS}</style>
      <div class="cabecera">
        <button class="icono" id="menu" title="Menú" ${this._verMenu() ? "" : "hidden"}>${icono("menu")}</button>
        <h1>Matrículas</h1>
      </div>
      <div class="contenido">
        <div class="pestanas" role="tablist"></div>
        <div class="herramientas">
          <label class="busqueda">${icono("buscar")}
            <input id="busqueda" type="search" placeholder="Buscar matrícula o nombre" autocomplete="off">
          </label>
          <select id="orden" aria-label="Ordenar">
            ${Object.entries(ORDENES).map(([k, v]) => `<option value="${k}">${esc(v)}</option>`).join("")}
          </select>
          <button class="boton principal" data-accion="nueva">${icono("mas")}Añadir</button>
        </div>
        <div class="lista" aria-live="polite"></div>
      </div>
      <div id="dialogo"></div>
      <div id="aviso"></div>`;

    raiz.querySelector("#menu").addEventListener("click", () =>
      this.dispatchEvent(new Event("hass-toggle-menu", { bubbles: true, composed: true }))
    );
    raiz.querySelector("#busqueda").addEventListener("input", (e) => {
      this._busqueda = e.target.value;
      this._pintarLista();
    });
    raiz.querySelector("#orden").addEventListener("change", (e) => {
      this._orden = e.target.value;
      this._pintarLista();
    });
    raiz.addEventListener("click", (e) => this._alPulsar(e));
    raiz.addEventListener("keydown", (e) => {
      if (e.key === "Escape" && this._dialogo) this._cerrarDialogo();
    });
    this._pintar();
  }

  _pintar() {
    if (!this.shadowRoot) return;
    this._pintarPestanas();
    this._pintarLista();
  }

  _pintarPestanas() {
    const d = this._datos;
    const pestanas = [
      ["registradas", "Registradas", d?.matriculas.length],
      ["desconocidas", "Desconocidas", d?.desconocidas.length],
      ["historial", "Historial", null],
      ["ignoradas", "Ignoradas", d?.ignoradas.length],
    ];
    this.shadowRoot.querySelector(".pestanas").innerHTML = pestanas
      .map(
        ([id, texto, n]) => `
        <button class="pestana" role="tab" data-pestana="${id}"
          aria-selected="${this._pestana === id}" data-aviso="${id === "desconocidas" && n > 0}">
          ${texto}${n == null ? "" : `<span class="contador">${n}</span>`}
        </button>`
      )
      .join("");
    const registradas = this._pestana === "registradas";
    this.shadowRoot.querySelector("#orden").hidden = !registradas;
  }

  _pintarLista() {
    const contenedor = this.shadowRoot?.querySelector(".lista");
    if (!contenedor) return;
    if (this._errorCarga) {
      contenedor.innerHTML = `<div class="vacio error-carga">${esc(this._errorCarga)}</div>`;
      return;
    }
    if (!this._datos) {
      contenedor.innerHTML = `<div class="vacio">Cargando…</div>`;
      return;
    }
    const html = {
      registradas: () => this._htmlRegistradas(),
      desconocidas: () => this._htmlDesconocidas(),
      historial: () => this._htmlHistorial(),
      ignoradas: () => this._htmlIgnoradas(),
    }[this._pestana]();
    contenedor.innerHTML = html;
    // Frigate borra las fotos antiguas: si ya no está, se quita el hueco.
    contenedor.querySelectorAll(".foto img").forEach((img) =>
      img.addEventListener("error", () => img.closest(".foto")?.remove(), { once: true })
    );
  }

  // Con enlace a la foto completa, salvo dentro de una fila que ya es un
  // botón (un enlace dentro de un botón no es HTML válido).
  _foto(frigateId, { enlace = true, clase = "foto" } = {}) {
    if (!frigateId) return "";
    const img = `<img loading="lazy" alt="" src="${urlFoto(frigateId)}">`;
    return enlace
      ? `<a class="${clase}" href="${urlFoto(frigateId, "snapshot")}" target="_blank" rel="noopener"
           title="Abrir la foto de Frigate" data-accion="nada">${img}</a>`
      : `<span class="${clase}">${img}</span>`;
  }

  _vacio(texto) {
    return `<div class="vacio">${texto}</div>`;
  }

  _htmlRegistradas() {
    const hoy = hoyIso();
    const fichas = ordenar(filtrar(this._datos.matriculas, this._busqueda), this._orden);
    if (!fichas.length) {
      return this._vacio(
        this._busqueda ? "Ninguna matrícula coincide con la búsqueda." : "Todavía no hay matrículas registradas."
      );
    }
    return fichas
      .map((f) => {
        const chips = [
          f.avisar ? `<span class="chip si">Avisa</span>` : `<span class="chip">No avisa</span>`,
          f.abrir ? `<span class="chip si">Puede abrir</span>` : `<span class="chip">No abre</span>`,
        ];
        if (f.caduca) {
          chips.push(
            estaCaducada(f.caduca, hoy)
              ? `<span class="chip mal">Caducó el ${esc(fechaLarga(f.caduca))}</span>`
              : `<span class="chip ojo">Hasta el ${esc(fechaLarga(f.caduca))}</span>`
          );
        }
        const vista = f.vista
          ? `Vista ${hace(f.vista.ultima)} · ${f.vista.veces} ${f.vista.veces === 1 ? "vez" : "veces"}`
          : "Sin detecciones todavía";
        return `
          <button class="fila" data-accion="editar" data-matricula="${esc(f.matricula)}">
            <div class="cuerpo">
              <div class="titulo">${placa(f.matricula)}<span class="nombre">${esc(f.nombre)}</span></div>
              <div class="chips">${chips.join("")}</div>
              <div class="secundario">${esc(vista)}${f.notas ? ` · ${esc(f.notas)}` : ""}</div>
            </div>
          </button>`;
      })
      .join("");
  }

  _htmlDesconocidas() {
    const lista = filtrar(this._datos.desconocidas, this._busqueda);
    if (!lista.length) {
      return this._vacio(
        this._busqueda
          ? "Ninguna desconocida coincide con la búsqueda."
          : "No hay matrículas desconocidas.<br>Las que lea Frigate y no estén registradas aparecerán aquí, de más a menos vistas."
      );
    }
    return lista
      .map(
        (v) => `
        <div class="fila">
          ${this._foto(v.frigate_id)}
          <div class="cuerpo">
            <div class="titulo">${placa(v.matricula)}</div>
            <div class="secundario">Vista ${v.veces} ${v.veces === 1 ? "vez" : "veces"} · la última ${esc(hace(v.ultima))}</div>
            <div class="acciones">
              <button class="boton principal" data-accion="nueva" data-matricula="${esc(v.matricula)}">${icono("mas")}Añadir</button>
              <button class="boton secundario" data-accion="ignorar" data-matricula="${esc(v.matricula)}">Ignorar</button>
            </div>
          </div>
        </div>`
      )
      .join("");
  }

  _htmlHistorial() {
    const lista = filtrar(this._datos.historial, this._busqueda);
    if (!lista.length) {
      return this._vacio(
        this._busqueda
          ? "Ninguna detección coincide con la búsqueda."
          : "Todavía no hay detecciones desde que se instaló la integración."
      );
    }
    const registradas = new Set(this._datos.matriculas.map((f) => f.matricula));
    return lista
      .map((h) => {
        const chips = h.tipo === "conocida"
          ? []
          : [`<span class="chip ${h.tipo === "caducada" ? "mal" : ""}">${esc(TIPOS[h.tipo] ?? h.tipo)}</span>`];
        if (h.aproximada) chips.push(`<span class="chip ojo">Leída ${esc(formatoPlaca(h.leida))}</span>`);
        const accion = registradas.has(h.matricula) ? "editar" : h.tipo === "desconocida" ? "nueva" : "nada";
        return `
          <button class="fila" data-accion="${accion}" data-matricula="${esc(h.matricula)}">
            ${this._foto(h.frigate_id, { enlace: false })}
            <div class="cuerpo">
              <div class="titulo">${placa(h.matricula)}<span class="nombre${h.nombre ? "" : " anonima"}">${esc(h.nombre || "Sin registrar")}</span></div>
              ${chips.length ? `<div class="chips">${chips.join("")}</div>` : ""}
              <div class="secundario" title="${esc(fechaHora(h.hora))}">${esc(fechaHora(h.hora))} · ${esc(hace(h.hora))}</div>
            </div>
          </button>`;
      })
      .join("");
  }

  _htmlIgnoradas() {
    const lista = filtrar(this._datos.ignoradas, this._busqueda);
    if (!lista.length) {
      return this._vacio(
        this._busqueda ? "Ninguna ignorada coincide con la búsqueda." : "No hay matrículas ignoradas."
      );
    }
    return lista
      .map(
        (i) => `
        <div class="fila">
          <div class="cuerpo">
            <div class="titulo">${placa(i.matricula)}</div>
            <div class="secundario">Ignorada ${esc(hace(i.desde))}</div>
          </div>
          <button class="boton secundario" data-accion="dejar_de_ignorar" data-matricula="${esc(i.matricula)}">Dejar de ignorar</button>
        </div>`
      )
      .join("");
  }

  // ── Acciones ──

  _alPulsar(e) {
    const pestana = e.target.closest("[data-pestana]");
    if (pestana) {
      this._pestana = pestana.dataset.pestana;
      this._pintar();
      return;
    }
    const origen = e.target.closest("[data-accion]");
    if (!origen) return;
    const { accion, matricula } = origen.dataset;
    if (accion === "nada") return;
    if (accion === "nueva") return this._abrirDialogo("nuevo", matricula);
    if (accion === "editar") return this._abrirDialogo("editar", matricula);
    if (accion === "ignorar") return this._llamar("ignorar", { matricula }, `${formatoPlaca(matricula)} ignorada: no volverá a avisar.`);
    if (accion === "dejar_de_ignorar") return this._llamar("dejar_de_ignorar", { matricula }, `${formatoPlaca(matricula)} vuelve a avisar.`);
    if (accion === "cerrar") return this._cerrarDialogo();
    if (accion === "guardar") return this._guardar();
    if (accion === "eliminar") return this._eliminar();
  }

  async _llamar(servicio, datos, textoOk) {
    try {
      await this._hass.callWS({
        type: "call_service",
        domain: "matriculas",
        service: servicio,
        service_data: datos,
      });
      if (textoOk) this._avisar(textoOk);
      return true;
    } catch (err) {
      if (this._dialogo) {
        this._dialogo.error = mensajeError(err);
        this._pintarDialogo();
      } else {
        this._avisar(mensajeError(err));
      }
      return false;
    }
  }

  _abrirDialogo(modo, matricula) {
    const ficha = modo === "editar" ? this._datos?.matriculas.find((f) => f.matricula === matricula) : null;
    if (modo === "editar" && !ficha) return;
    this._dialogo = {
      modo,
      original: ficha?.matricula ?? "",
      ficha,
      valores: ficha
        ? { matricula: ficha.matricula, nombre: ficha.nombre, avisar: ficha.avisar, abrir: ficha.abrir, notas: ficha.notas ?? "", caduca: ficha.caduca ?? "" }
        : { matricula: matricula ?? "", nombre: "", avisar: true, abrir: true, notas: "", caduca: "" },
      fotoDesconocida: modo === "nuevo" ? this._datos?.desconocidas.find((v) => v.matricula === matricula)?.frigate_id : null,
      error: "",
      confirmarBorrado: false,
      ocupado: false,
    };
    this._pintarDialogo();
    const foco = this.shadowRoot.querySelector(modo === "nuevo" && matricula ? "#f-nombre" : "#f-matricula");
    foco?.focus();
  }

  _cerrarDialogo() {
    this._dialogo = null;
    this._pintarDialogo();
  }

  _leerFormulario() {
    const $ = (id) => this.shadowRoot.querySelector(id);
    return {
      matricula: $("#f-matricula").value,
      nombre: $("#f-nombre").value,
      avisar: $("#f-avisar").checked,
      abrir: $("#f-abrir").checked,
      notas: $("#f-notas").value,
      caduca: $("#f-caduca").value,
    };
  }

  async _guardar() {
    const d = this._dialogo;
    if (!d || d.ocupado) return;
    d.valores = this._leerFormulario();
    let peticion;
    try {
      peticion = peticionGuardar(d.modo, d.original, d.valores, this._datos.matriculas.map((f) => f.matricula));
    } catch (err) {
      d.error = err.message;
      this._pintarDialogo();
      return;
    }
    d.ocupado = true;
    d.error = "";
    this._pintarDialogo();
    const destino = peticion.datos.nueva_matricula ?? peticion.datos.matricula;
    const ok = await this._llamar(
      peticion.servicio,
      peticion.datos,
      `${formatoPlaca(normalizar(destino))} guardada.`
    );
    if (ok) this._cerrarDialogo();
    else if (this._dialogo) {
      this._dialogo.ocupado = false;
      this._pintarDialogo();
    }
  }

  async _eliminar() {
    const d = this._dialogo;
    if (!d || d.ocupado) return;
    d.valores = this._leerFormulario();
    if (!d.confirmarBorrado) {
      d.confirmarBorrado = true;
      this._pintarDialogo();
      return;
    }
    d.ocupado = true;
    this._pintarDialogo();
    const ok = await this._llamar("eliminar", { matricula: d.original }, `${formatoPlaca(d.original)} eliminada.`);
    if (ok) this._cerrarDialogo();
    else if (this._dialogo) {
      this._dialogo.ocupado = false;
      this._dialogo.confirmarBorrado = false;
      this._pintarDialogo();
    }
  }

  _pintarDialogo() {
    const contenedor = this.shadowRoot?.querySelector("#dialogo");
    if (!contenedor) return;
    const d = this._dialogo;
    if (!d) {
      contenedor.innerHTML = "";
      return;
    }
    const v = d.valores;
    const f = d.ficha;
    const estadisticas = f?.vista
      ? `<div class="secundario">Vista ${f.vista.veces} ${f.vista.veces === 1 ? "vez" : "veces"}, la última ${esc(hace(f.vista.ultima))}</div>`
      : f
        ? `<div class="secundario">Sin detecciones todavía</div>`
        : "";
    const fotoId = f?.vista?.frigate_id || d.fotoDesconocida;
    contenedor.innerHTML = `
      <div class="fondo">
        <div class="dialogo" role="dialog" aria-modal="true" aria-labelledby="titulo-dialogo">
          <h2 id="titulo-dialogo">${d.modo === "nuevo" ? "Añadir matrícula" : "Editar matrícula"}
            <button class="icono" data-accion="cerrar" title="Cerrar">${icono("cerrar")}</button></h2>
          ${this._foto(fotoId, { clase: "foto grande" })}
          ${estadisticas}
          <div class="campo"><label for="f-matricula">Matrícula</label>
            <input id="f-matricula" value="${esc(v.matricula)}" autocomplete="off" autocapitalize="characters" spellcheck="false"></div>
          <div class="campo"><label for="f-nombre">Nombre</label>
            <input id="f-nombre" value="${esc(v.nombre)}" autocomplete="off" placeholder="Quién es"></div>
          <label class="interruptor"><span>Avisar cuando llegue<small>Notifica su llegada al videoportero.</small></span>
            <input id="f-avisar" type="checkbox" ${v.avisar ? "checked" : ""}></label>
          <label class="interruptor"><span>Puede abrir la puerta<small>Con la apertura automática activada, también si la lectura es aproximada.</small></span>
            <input id="f-abrir" type="checkbox" ${v.abrir ? "checked" : ""}></label>
          <div class="campo"><label for="f-caduca">Autorizada hasta (opcional)</label>
            <input id="f-caduca" type="date" value="${esc(v.caduca)}"></div>
          <div class="campo"><label for="f-notas">Notas</label>
            <textarea id="f-notas" rows="2">${esc(v.notas)}</textarea></div>
          ${d.error ? `<div class="mensaje-error" role="alert">${esc(d.error)}</div>` : ""}
          <div class="pie">
            ${d.modo === "editar"
              ? `<button class="boton peligro ${d.confirmarBorrado ? "confirmar" : ""}" data-accion="eliminar" ${d.ocupado ? "disabled" : ""}>
                  ${d.confirmarBorrado ? "Pulsa otra vez para eliminar" : "Eliminar"}</button>`
              : ""}
            <span class="hueco"></span>
            <button class="boton secundario" data-accion="cerrar">Cancelar</button>
            <button class="boton principal" data-accion="guardar" ${d.ocupado ? "disabled" : ""}>${d.ocupado ? "Guardando…" : "Guardar"}</button>
          </div>
        </div>
      </div>`;
    contenedor.querySelectorAll(".foto img").forEach((img) =>
      img.addEventListener("error", () => img.closest(".foto")?.remove(), { once: true })
    );
    contenedor.querySelector(".dialogo").addEventListener("keydown", (e) => {
      if (e.key === "Enter" && e.target.tagName === "INPUT" && e.target.type !== "checkbox") {
        e.preventDefault();
        this._guardar();
      }
    });
  }

  _avisar(texto) {
    const contenedor = this.shadowRoot?.querySelector("#aviso");
    if (!contenedor) return;
    contenedor.innerHTML = `<div class="aviso" role="status">${esc(texto)}</div>`;
    clearTimeout(this._temporizadorAviso);
    this._temporizadorAviso = setTimeout(() => (contenedor.innerHTML = ""), 3500);
  }
}

if (typeof customElements !== "undefined" && !customElements.get("matriculas-panel")) {
  customElements.define("matriculas-panel", MatriculasPanel);
}
