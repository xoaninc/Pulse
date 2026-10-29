/* Galería local: elegir 24 fotos de arte involuntario + 12 o más del paseo y generar las láminas. */
"use strict";

const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const h = (tag, attrs = {}, ...hijos) => {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") el.className = v;
    else if (k === "style") el.style.cssText = v;
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (v !== false && v != null) el.setAttribute(k, v === true ? "" : v);
  }
  for (const c of hijos.flat()) if (c != null && c !== false) el.append(c.nodeType ? c : document.createTextNode(c));
  return el;
};

const MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"];
const MAX_ARTE = 24;
const MIN_PASEO = 12;

const S = {
  estado: null,
  cats: [],
  nombres: {},
  catActiva: null,
  vista: "cat",          // cat | buscar | general | similares
  consulta: "",
  lista: [],
  desde: 0,
  sel: null,
  paseos: [],
  paseo: null,           // respuesta de /api/paseo
  modalLista: [],
  modalPos: -1,
};

// ------------------------------------------------------------------ utilidades
async function api(ruta, opciones) {
  const r = await fetch(ruta, opciones);
  const d = await r.json().catch(() => ({}));
  if (!r.ok || d.error) throw new Error(d.error || `Error ${r.status}`);
  return d;
}
const post = (ruta, cuerpo) => api(ruta, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(cuerpo || {}) });
const mini = (uuid, s = 360) => `/mini/${encodeURIComponent(uuid)}?s=${s}`;
const num = (x, d = 1) => Number(x).toLocaleString("es-ES", { minimumFractionDigits: d, maximumFractionDigits: d });
let turno = 0;  // cada vista nueva invalida las respuestas lentas de la anterior (W7)

function mesAnio(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  return isNaN(d) ? "" : `${MESES[d.getMonth()]} ${d.getFullYear()}`;
}
function fechaCorta(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  return isNaN(d) ? "" : d.toLocaleDateString("es-ES", { day: "numeric", month: "short", year: "numeric" });
}
function pieDefecto(d) {
  return [d.lugar, mesAnio(d.fecha)].filter(Boolean).join(" · ");
}
let toastT;
function toast(msg) {
  let t = $("#toast");
  if (!t) { t = h("div", { id: "toast", style: "position:fixed;bottom:90px;left:50%;transform:translateX(-50%);background:#1d1b19;color:#fff;padding:9px 16px;border-radius:99px;z-index:60;font-size:13px;box-shadow:0 4px 14px rgba(0,0,0,.25)" }); document.body.append(t); }
  t.textContent = msg; t.style.display = "block";
  clearTimeout(toastT); toastT = setTimeout(() => (t.style.display = "none"), 2600);
}
let guardarT = null;
async function guardarAhora() {
  guardarT = null;
  const r = await fetch("/api/seleccion", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(S.sel) });
  const d = await r.json().catch(() => ({}));
  if (r.status === 409 && d.seleccion) {
    // otra pestaña (u otra galería) cambió la selección después: manda la más reciente
    toast("La selección se cambió en otra pestaña: cargo la versión más reciente.");
    S.sel = normalizarSel(d.seleccion);
    repintarTodo();
    return;
  }
  if (!r.ok) throw new Error(d.error || `Error ${r.status}`);
  S.sel._rev = d._rev;
}
function guardar() {
  clearTimeout(guardarT);
  guardarT = setTimeout(() => guardarAhora().catch(e => toast("No se pudo guardar: " + e.message)), 350);
  contadores();
}
function normalizarSel(sel) {
  sel.arte = sel.arte || [];
  sel.paseo = Object.assign({ id: null, titulo: "", linea: "", fotos: [], mayusculas: true, dibujo: true, datos: true, diseno: "rejilla", k: 12 }, sel.paseo || {});
  sel.opciones = Object.assign({ orden: "categoria", contraste: "normal", cabecera: true, sin_descargar: false }, sel.opciones || {});
  sel.autor = sel.autor || "";
  sel.borradores = sel.borradores || {};
  return sel;
}
function repintarTodo() {
  contadores();
  if (S.lista.length) pintarRejilla();
  if (S.paseo) pintarPaseo();
  iniciarLaminas();
}
// el último cambio no se pierde al cerrar o recargar la pestaña (W14)
addEventListener("pagehide", () => {
  if (guardarT) { clearTimeout(guardarT); navigator.sendBeacon("/api/seleccion", new Blob([JSON.stringify(S.sel)], { type: "application/json" })); }
});
// al volver a esta pestaña, traer la selección por si se cambió en otra
document.addEventListener("visibilitychange", async () => {
  if (document.visibilityState !== "visible" || guardarT || !S.sel) return;
  const d = await api("/api/seleccion").catch(() => null);
  if (d && (d._rev || 0) > (S.sel._rev || 0)) { S.sel = normalizarSel(d); repintarTodo(); }
});

// ------------------------------------------------------------------ arranque
async function iniciar() {
  S.estado = await api("/api/estado");
  S.cats = S.estado.categorias;
  S.cats.forEach(c => (S.nombres[c.id] = c.nombre));
  S.sel = normalizarSel(await api("/api/seleccion"));
  const est = S.estado.estadisticas || {};
  $("#estado-global").innerHTML = `${S.estado.fotos.toLocaleString("es-ES")} fotos analizadas · modelo ${S.estado.modelo.nombre}` +
    (est.sin_imagen_local ? ` · ${est.sin_imagen_local} solo en iCloud` : "") +
    (S.estado.ia ? ` · IA: ${S.estado.ia.modelo.split("/").pop()}` : "");
  if (S.estado.ia_problema) setTimeout(() => toast(S.estado.ia_problema), 1200);
  $$("nav button").forEach(b => b.addEventListener("click", () => cambiarTab(b.dataset.tab)));
  $("#btn-buscar").onclick = () => buscar($("#busqueda").value.trim());
  $("#busqueda").addEventListener("keydown", e => { if (e.key === "Enter") buscar(e.target.value.trim()); });
  $("#btn-mas").onclick = () => cargarMas();
  $("#modal-cerrar").onclick = () => cerrarModal();
  let inicioClic = null;
  $("#modal").addEventListener("pointerdown", e => (inicioClic = e.target));
  $("#modal").addEventListener("click", e => { if (e.target.id === "modal" && inicioClic && inicioClic.id === "modal") cerrarModal(); });
  document.addEventListener("keydown", teclas);
  if (S.estado.ia) { $("#btn-ia-cat").classList.remove("oculto"); $("#btn-ia-cat").onclick = revisarIA; }
  pintarCategorias();
  elegirCategoria(S.cats[0].id);
  iniciarLaminas();
  contadores();
}

function cambiarTab(t) {
  $$("nav button").forEach(b => b.classList.toggle("activa", b.dataset.tab === t));
  $$(".tab").forEach(s => s.classList.toggle("activa", s.id === "tab-" + t));
  $("#bandeja").classList.toggle("oculto", t !== "arte");
  if (t === "paseo" && !S.paseos.length) cargarPaseos();
  if (t === "laminas") resumenSeleccion();
  window.scrollTo(0, 0);
}

function contadores() {
  const n = S.sel.arte.length;
  $("#cuenta-arte").textContent = `${n}/${MAX_ARTE}`;
  $("#cuenta-paseo").textContent = `${S.sel.paseo.fotos.length}/${MIN_PASEO}+`;
  pintarCategorias();
  pintarBandeja();
}

// ------------------------------------------------------------------ ARTE: categorías
function pintarCategorias() {
  const cont = $("#categorias");
  const porCat = {};
  S.sel.arte.forEach(a => (porCat[a.categoria] = (porCat[a.categoria] || 0) + 1));
  cont.innerHTML = "";
  cont.append(h("h3", {}, "Categorías de Clément"),
    h("p", { class: "ayuda" }, "Elige 24 fotos e intenta que estén las 8 categorías (3 de cada una es un buen reparto)."));
  for (const c of S.cats) {
    const n = porCat[c.id] || 0;
    cont.append(h("button", { class: "cat" + (S.vista === "cat" && S.catActiva === c.id ? " activa" : ""), onclick: () => elegirCategoria(c.id) },
      h("div", {}, h("div", { class: "nombre" }, c.nombre), h("div", { class: "info" }, c.fuertes > 0 ? `${c.fuertes} candidatas fuertes` : "pocas candidatas: busca a mano")),
      h("span", { class: "num" + (n ? " ok" : "") }, n)));
  }
  cont.append(h("button", { class: "cat especial" + (S.vista === "general" ? " activa" : ""), onclick: verGeneral },
    h("div", {}, h("div", { class: "nombre" }, "★ Lo más «Clément»"), h("div", { class: "info" }, "las mejores de todas las categorías"))));
}

function recortar(t, n) {
  if (!t || t.length <= n) return t;
  const corte = t.lastIndexOf(" ", n - 1);
  return t.slice(0, corte > n / 2 ? corte : n).replace(/[,;:.]$/, "") + "…";
}

async function elegirCategoria(id) {
  turno++; cargando = false;
  S.vista = "cat"; S.catActiva = id; S.desde = 0; S.lista = []; S.catChip = null;
  const c = S.cats.find(x => x.id === id);
  $("#cab-categoria").innerHTML = "";
  $("#cab-categoria").append(
    h("h2", {}, c.nombre),
    c.definicion && c.definicion.length > 420
      ? h("details", { class: "def" }, h("summary", {}, `«${recortar(c.definicion, 300)}»`), c.definicion)
      : h("div", { class: "def" }, c.definicion ? `«${c.definicion}»` : ""),
    h("p", { class: "ayuda" }, recortar(c.descripcion || "", 260)),
    c.consejos && c.consejos.length ? h("details", {}, h("summary", {}, "Qué buscar"), h("ul", {}, c.consejos.map(x => h("li", {}, x)))) : "");
  pintarSugerencias(c);
  pintarCategorias();
  await cargarMas();
}

function pintarSugerencias(c) {
  const cont = $("#sugerencias");
  cont.innerHTML = "";
  cont.classList.remove("abiertas");
  if (!c) return;
  const total = (c.busquedas || []).length;
  cont.append(h("span", { class: "ayuda", style: "margin:3px 4px 0 0" }, "Buscar solo:"),
    h("button", { class: "chip ver", onclick: e => { cont.classList.toggle("abiertas"); e.target.textContent = cont.classList.contains("abiertas") ? "menos" : `ver las ${total}`; } }, `ver las ${total}`));
  (c.busquedas || []).forEach(q => cont.append(h("button", { class: "chip" + (S.consulta === q && S.vista === "buscar" ? " activa" : ""), onclick: () => buscar(q, true) }, q.replace(/^a photo of /i, ""))));
}

let cargando = false;
async function cargarMas() {
  if (cargando) return;
  cargando = true;
  $("#btn-mas").disabled = true;
  const n = 60, mio = turno, desde = S.desde;
  S.desde += n;
  let nuevos = [];
  try {
    if (S.vista === "cat") nuevos = await api(`/api/candidatas?cat=${S.catActiva}&desde=${desde}&n=${n}`);
    else if (S.vista === "general" && desde === 0) nuevos = await api(`/api/general?n=180`);
  } catch (e) { toast(e.message); }
  finally { cargando = false; $("#btn-mas").disabled = false; }
  if (mio !== turno) return;
  S.lista = S.lista.concat(nuevos);
  $("#btn-mas").classList.toggle("oculto", !(S.vista === "cat" && nuevos.length === n));
  pintarRejilla();
}

async function buscar(q, desdeChip) {
  if (!q) return;
  const mio = ++turno;
  // desde un chip de una categoría, lo que se añada va a ESA categoría (W8)
  S.catChip = desdeChip ? S.catActiva : null;
  S.vista = "buscar"; S.consulta = q; S.lista = [];
  $("#titulo-rejilla").textContent = "Buscando… (la primera búsqueda tarda unos segundos mientras se carga el modelo)";
  $("#rejilla").innerHTML = "";
  if (!desdeChip) pintarSugerencias(null);
  else pintarSugerencias(S.cats.find(x => x.id === S.catActiva));
  try {
    const r = await api(`/api/buscar?q=${encodeURIComponent(q)}&n=120`);
    if (mio !== turno) return;
    S.lista = r.fotos;
    S.consultaReal = r.consulta !== q ? r.consulta : "";
  } catch (e) { toast(e.message); }
  $("#btn-mas").classList.add("oculto");
  pintarRejilla();
}

async function verGeneral() {
  turno++; cargando = false;
  S.vista = "general"; S.desde = 0; S.lista = []; S.catChip = null;
  $("#cab-categoria").innerHTML = "<h2>★ Lo más «Clément» de tu fototeca</h2><p class='ayuda'>Las fotos que mejor encajan en alguna categoría. Debajo de cada una, la categoría sugerida (puedes cambiarla).</p>";
  pintarSugerencias(null);
  pintarCategorias();
  await cargarMas();
}

async function verSimilares(uuid) {
  cerrarModal();
  cambiarTab("arte");
  const mio = ++turno;
  S.vista = "similares"; S.lista = []; S.catChip = null;
  $("#cab-categoria").innerHTML = "";
  $("#cab-categoria").append(h("h2", {}, "Fotos parecidas a esta"), h("img", { src: mini(uuid, 200), style: "height:90px;border-radius:8px" }));
  pintarSugerencias(null);
  const lista = await api(`/api/similares?uuid=${encodeURIComponent(uuid)}&n=90`);
  if (mio !== turno) return;
  S.lista = lista;
  $("#btn-mas").classList.add("oculto");
  pintarRejilla();
}

function seleccionadaArte(uuid) { return S.sel.arte.find(a => a.uuid === uuid); }

function anadirArte(d, cat) {
  const ya = seleccionadaArte(d.uuid);
  if (ya) { ya.categoria = cat; guardar(); return true; }
  if (S.sel.arte.length >= MAX_ARTE) { toast(`Ya tienes ${MAX_ARTE}. Quita alguna desde la bandeja de abajo.`); return false; }
  const pie = (d.ia && d.ia.pie && false) || pieDefecto(d);
  S.sel.arte.push({ uuid: d.uuid, categoria: cat, pie, fecha: d.fecha, lugar: d.lugar, recorte: { cx: 0.5, cy: 0.5, zoom: 1 } });
  guardar();
  return true;
}
function quitarArte(uuid) {
  S.sel.arte = S.sel.arte.filter(a => a.uuid !== uuid);
  guardar();
}

function refrescar(uuid) {
  const i = S.lista.findIndex(d => d.uuid === uuid);
  $$(".tarjeta[data-uuid]", $("#rejilla")).forEach(el => {
    if (el.dataset.uuid === uuid && i >= 0) el.replaceWith(tarjetaArte(S.lista[i], i));
  });
}

function pintarRejilla() {
  const cont = $("#rejilla");
  cont.innerHTML = "";
  const tit = { cat: `Candidatas para ${S.nombres[S.catActiva] || ""}, de más a menos probable`, buscar: `Resultados para «${S.consulta}»` + (S.consultaReal ? ` (buscado como «${S.consultaReal}»)` : ""), general: "", similares: "" }[S.vista];
  $("#titulo-rejilla").textContent = S.lista.length ? tit : "";
  if (!S.lista.length) { cont.append(h("div", { class: "vacio" }, "No hay fotos que mostrar.")); return; }
  S.lista.forEach((d, i) => cont.append(tarjetaArte(d, i)));
}

function tarjetaArte(d, i) {
  const sel = seleccionadaArte(d.uuid);
  const catVista = S.vista === "cat" ? S.catActiva : (S.vista === "buscar" && S.catChip) || null;
  const t = h("div", { class: "tarjeta" + (sel ? " elegida" : ""), "data-uuid": d.uuid });
  const img = h("div", { class: "img", style: `background-image:url('${mini(d.uuid)}')`, title: "Ver grande", onclick: () => abrirVisor(S.lista, i) });
  t.append(img);
  if (d.en_icloud) t.append(h("span", { class: "badge", title: "El original está en iCloud: se descargará solo si la eliges" }, "☁"));
  if (d.ia && d.ia.nota != null) t.append(h("span", { class: "badge ia" + (d.ia.nota < 6 ? " baja" : ""), style: d.en_icloud ? "left:34px" : "", title: d.ia.motivo || "" }, `IA ${d.ia.nota}/10`));
  if (sel) t.append(h("span", { class: "num-sel" }, S.nombres[sel.categoria]));
  const pie = h("div", { class: "pie" });
  pie.append(h("div", {}, [d.lugar, fechaCorta(d.fecha)].filter(Boolean).join(" · ") || "—"));
  const fila = h("div", { class: "fila" });
  if (catVista) {
    if (sel && sel.categoria === catVista) fila.append(h("button", { class: "sec", onclick: () => { quitarArte(d.uuid); refrescar(d.uuid); } }, "✓ Quitar"));
    else fila.append(h("button", { onclick: () => { if (anadirArte(d, catVista)) refrescar(d.uuid); } }, sel ? `Mover a ${S.nombres[catVista]}` : `＋ ${S.nombres[catVista]}`));
    if (d.tambien && d.tambien.length) fila.append(h("span", { title: "También encaja en" }, "≈ " + d.tambien.map(c => S.nombres[c]).join(", ")));
  } else {
    const s = h("select", {}, S.cats.map(c => h("option", { value: c.id, selected: (sel ? sel.categoria : d.sugerida) === c.id }, c.nombre)));
    fila.append(s, sel ? h("button", { class: "sec", onclick: () => { quitarArte(d.uuid); refrescar(d.uuid); } }, "✓") :
      h("button", { onclick: () => { if (anadirArte(d, s.value)) refrescar(d.uuid); } }, "＋"));
  }
  pie.append(fila);
  t.append(pie);
  return t;
}

// ------------------------------------------------------------------ bandeja
function pintarBandeja() {
  const b = $("#bandeja");
  if (!b) return;
  b.innerHTML = "";
  const ordenadas = ordenArte();
  b.append(h("div", { class: "bandeja-titulo" }, h("b", {}, `${S.sel.arte.length} / ${MAX_ARTE}`), "fotos elegidas · clic para recortar"));
  for (let l = 0; l < 4; l++) {
    const lam = h("div", { class: "lamina-mini", title: `Lámina ${l + 1}` });
    for (let k = 0; k < 6; k++) {
      const a = ordenadas[l * 6 + k];
      const hueco = h("div", { class: "hueco" });
      if (a) {
        hueco.style.backgroundImage = `url('${mini(a.uuid, 120)}')`;
        hueco.append(h("span", {}, (S.nombres[a.categoria] || "").slice(0, 7)));
        hueco.onclick = () => editarArte(a.uuid);
      }
      lam.append(hueco);
    }
    b.append(lam);
  }
}

function ordenArte() {
  if (S.sel.opciones.orden === "manual") return S.sel.arte;
  const pos = Object.fromEntries(S.cats.map((c, i) => [c.id, i]));
  return S.sel.arte.map((a, i) => [a, i]).sort((x, y) => (pos[x[0].categoria] - pos[y[0].categoria]) || (x[1] - y[1])).map(x => x[0]);
}

// ------------------------------------------------------------------ visor / editor
function abrirModal(contenido) {
  modalSucio = false;
  if (alCerrarModal) { alCerrarModal(); alCerrarModal = null; }
  $("#modal-cuerpo").innerHTML = "";
  $("#modal-cuerpo").append(contenido);
  $("#modal").classList.remove("oculto");
}
let alCerrarModal = null;   // limpieza del editor abierto
let modalSucio = false;      // hay cambios sin guardar en el editor
function cerrarModal(forzar) {
  if (modalSucio && forzar !== true && !confirm("¿Cerrar sin guardar el recorte y el texto?")) return;
  $("#modal").classList.add("oculto"); S.modalPos = -1; modalSucio = false;
  if (alCerrarModal) { alCerrarModal(); alCerrarModal = null; }
}
function teclas(e) {
  if ($("#modal").classList.contains("oculto")) return;
  if (e.key === "Escape") cerrarModal();
  if (S.modalPos >= 0 && (e.key === "ArrowRight" || e.key === "ArrowLeft") && document.activeElement.tagName !== "INPUT" && document.activeElement.tagName !== "TEXTAREA") {
    const n = S.modalPos + (e.key === "ArrowRight" ? 1 : -1);
    if (n >= 0 && n < S.modalLista.length) abrirVisor(S.modalLista, n);
  }
}

async function abrirVisor(lista, i) {
  S.modalLista = lista; S.modalPos = i;
  const d = lista[i];
  const meta = await api(`/api/foto?uuid=${encodeURIComponent(d.uuid)}`).catch(() => ({}));
  const sel = seleccionadaArte(d.uuid);
  const s = h("select", {}, S.cats.map(c => h("option", { value: c.id, selected: (sel ? sel.categoria : (S.vista === "cat" ? S.catActiva : (S.catChip || d.sugerida))) === c.id }, c.nombre)));
  const panel = h("div", { class: "panel" },
    h("div", { class: "meta" }, h("b", {}, meta.nombre || ""), h("br"), [fechaCorta(meta.fecha), meta.lugar || meta.lugar_corto].filter(Boolean).join(" · ")),
    meta.en_icloud ? h("div", { class: "meta" }, "☁ Original en iCloud (aquí ves la previsualización local). Si la eliges se descargará solo esta.") : "",
    d.ia ? h("div", { class: "meta" }, h("b", {}, `IA: ${d.ia.nota}/10`), " ", d.ia.motivo || "") : "",
    meta.descripcion ? h("div", { class: "meta" }, meta.descripcion) : "",
    meta.etiquetas && meta.etiquetas.length ? h("div", { class: "etqs" }, meta.etiquetas.slice(0, 18).map(e => h("span", {}, e))) : "",
    h("label", {}, "Categoría", s),
    sel ? h("button", { class: "sec", onclick: () => { quitarArte(d.uuid); cerrarModal(); refrescar(d.uuid); } }, "Quitar de la selección")
      : h("button", { onclick: () => { if (anadirArte(d, s.value)) { cerrarModal(); refrescar(d.uuid); } } }, "＋ Elegir esta foto"),
    sel ? h("button", { onclick: () => { sel.categoria = s.value; guardar(); editarArte(d.uuid); } }, "Recortar y poner pie") : "",
    h("button", { class: "sec", onclick: () => verSimilares(d.uuid) }, "≈ Ver fotos parecidas"),
    h("p", { class: "ayuda" }, "← → para pasar de foto · Esc para cerrar"));
  abrirModal(h("div", { class: "visor" }, h("div", {}, h("div", { class: "lienzo" }, h("img", { src: mini(d.uuid, 1400) }))), panel));
}

function editorRecorte({ uuid, recorte, bn, extra, alGuardar }) {
  const r = Object.assign({ cx: 0.5, cy: 0.5, zoom: 1 }, recorte || {});
  const img = h("img", { src: mini(uuid, 1400), draggable: "false" });
  const marco = h("div", { class: "marco" });
  const lienzo = h("div", { class: "lienzo" + (bn ? " bn" : "") }, img, marco);
  const zoom = h("input", { type: "range", min: "1", max: "3", step: "0.05", value: r.zoom });
  function colocar() {
    const W = img.clientWidth, H = img.clientHeight;
    if (!W || !H) return;
    const lado = Math.min(W, H) / r.zoom;
    let x = r.cx * W - lado / 2, y = r.cy * H - lado / 2;
    x = Math.max(0, Math.min(W - lado, x)); y = Math.max(0, Math.min(H - lado, y));
    r.cx = (x + lado / 2) / W; r.cy = (y + lado / 2) / H;
    Object.assign(marco.style, { left: x + "px", top: y + "px", width: lado + "px", height: lado + "px" });
  }
  img.onload = colocar;
  const ac = new AbortController();
  window.addEventListener("resize", colocar, { signal: ac.signal });
  zoom.oninput = () => { r.zoom = parseFloat(zoom.value); colocar(); modalSucio = true; };
  let arrastrando = false;
  const mover = e => {
    const b = img.getBoundingClientRect();
    r.cx = (e.clientX - b.left) / b.width; r.cy = (e.clientY - b.top) / b.height; colocar();
  };
  lienzo.addEventListener("pointerdown", e => { arrastrando = true; modalSucio = true; lienzo.setPointerCapture(e.pointerId); mover(e); });
  lienzo.addEventListener("pointermove", e => { if (arrastrando) mover(e); });
  lienzo.addEventListener("pointerup", () => (arrastrando = false));
  const panel = h("div", { class: "panel" },
    h("p", { class: "ayuda" }, "Arrastra el cuadrado para elegir el encuadre. La lámina usa exactamente este recorte" + (bn ? ", en blanco y negro." : ", en color.")),
    h("label", {}, "Zoom", zoom),
    h("button", { class: "sec", onclick: () => { r.cx = 0.5; r.cy = 0.5; r.zoom = 1; zoom.value = 1; colocar(); } }, "Centrar"),
    extra || "",
    h("button", { onclick: () => { alGuardar(r); cerrarModal(true); } }, "Guardar"));
  panel.addEventListener("input", () => (modalSucio = true));
  S.modalPos = -1;
  abrirModal(h("div", { class: "visor" }, h("div", {}, lienzo), panel));
  alCerrarModal = () => ac.abort();
}

function editarArte(uuid) {
  const a = seleccionadaArte(uuid);
  if (!a) return;
  const s = h("select", {}, S.cats.map(c => h("option", { value: c.id, selected: a.categoria === c.id }, c.nombre)));
  const pie = h("textarea", { rows: 2 }, a.pie || "");
  const extra = h("div", { class: "panel" },
    h("label", {}, "Categoría", s),
    h("label", {}, "Pie (lugar, fecha o lo que quieras; como en el libro: «Arrozal en Suzhou, lago Tai (China)»)", pie),
    h("button", { class: "sec", onclick: () => { quitarArte(uuid); cerrarModal(true); refrescar(uuid); } }, "Quitar de la selección"));
  editorRecorte({
    uuid, recorte: a.recorte, bn: false, extra,
    alGuardar: r => { a.recorte = r; a.categoria = s.value; a.pie = pie.value.trim(); guardar(); refrescar(uuid); },
  });
}

// ------------------------------------------------------------------ IA
async function revisarIA() {
  const cat = S.catActiva;
  if (S.vista !== "cat") { toast("Abre una categoría primero"); return; }
  await post("/api/ia/revisar", { categorias: [cat], n: 12 });
  toast("Revisando con IA… (unos segundos)");
  esperarIA(() => {
    if (S.vista === "cat" && S.catActiva === cat) elegirCategoria(cat);
    else toast(`IA: revisión de ${S.nombres[cat]} lista`);
  });
}
function esperarIA(alAcabar) {
  const t = setInterval(async () => {
    const d = await api("/api/ia");
    if (d.log.length) toast(d.log[d.log.length - 1]);
    if (d.estado !== "trabajando") { clearInterval(t); if (d.estado === "error") toast("IA: " + d.log.slice(-1)[0]); alAcabar(d); }
  }, 1500);
}

// ------------------------------------------------------------------ PASEO
async function cargarPaseos() {
  const cont = $("#lista-paseos");
  cont.innerHTML = "<p class='ayuda'>Buscando caminatas…</p>";
  S.paseos = await api("/api/paseos");
  pintarPaseos();
  const rango = S.sel.paseo.rango || {};
  $("#rango-desde").value = rango.desde || "";
  $("#rango-hasta").value = rango.hasta || "";
  $("#btn-rango").onclick = async () => {
    const d = $("#rango-desde").value, a = $("#rango-hasta").value;
    if (!d || !a) return toast("Pon las dos fechas");
    try {
      const p = await post("/api/paseo_rango", { desde: d, hasta: a });
      S.paseos = S.paseos.filter(x => x.id !== p.id).concat([p]);
      S.sel.paseo.rango = { desde: d, hasta: a };
      pintarPaseos(); abrirPaseo(p.id);
    } catch (e) { toast(e.message); }
  };
  const id = S.sel.paseo.id;
  if (id && !S.paseos.find(p => p.id === id) && id.startsWith("r")) {
    // caminata elegida a mano en otra sesión: el servidor la reconstruye por su id
    const r = await api(`/api/paseo?id=${encodeURIComponent(id)}&k=${S.sel.paseo.k || 12}`).catch(() => null);
    if (r) { S.paseos.push(r.paseo); pintarPaseos(); }
  }
  if (id && S.paseos.find(p => p.id === id)) abrirPaseo(id);
}

function pintarPaseos() {
  const cont = $("#lista-paseos");
  cont.innerHTML = "";
  if (!S.paseos.length) { cont.append(h("p", { class: "ayuda" }, "No he encontrado caminatas con 8 fotos o más. Usa «Elegir fechas a mano».")); return; }
  for (const p of S.paseos) {
    cont.append(h("button", { class: "paseo-item" + (S.paseo && S.paseo.paseo.id === p.id ? " activa" : ""), onclick: () => abrirPaseo(p.id) },
      h("div", { class: "tira" }, p.portada.slice(0, 4).map(u => h("div", { style: `background-image:url('${mini(u, 120)}')` }))),
      h("div", { class: "datos" }, h("b", {}, fechaCorta(p.inicio)), h("br"),
        `${p.lugar || "sin lugar"} · ${p.fotos} fotos (${p.naturales} de paisaje)` + (p.km ? ` · ${num(p.km)} km` : "") + (p.horas ? ` · ${num(p.horas)} h` : ""))));
  }
}

const copia = x => JSON.parse(JSON.stringify(x));

// modo: "abrir" (por defecto), "k" (otro número de fotos: conserva lo escrito) o "reiniciar"
async function abrirPaseo(id, modo = "abrir", k = null) {
  const P = S.sel.paseo;
  if (P.id && P.id !== id && P.fotos.length) {
    // guardar el borrador de la caminata que se deja (frases, recortes, título…)
    S.sel.borradores[P.id] = copia({ titulo: P.titulo, linea: P.linea, fotos: P.fotos, k: P.k, rango: P.rango });
  }
  const borrador = P.id !== id ? S.sel.borradores[id] : null;
  k = k || (P.id === id ? P.k : borrador && borrador.k) || 12;
  $("#cab-paseo").innerHTML = "<p class='ayuda'>Cargando…</p>";
  let r;
  try { r = await api(`/api/paseo?id=${encodeURIComponent(id)}&k=${k}`); }
  catch (e) { $("#cab-paseo").innerHTML = ""; toast(e.message); return; }
  S.paseo = r;
  const fichas = Object.fromEntries(r.todas.map(f => [f.uuid, f]));
  const propuesta = () => r.sugeridas.map(u => nuevaFotoPaseo(fichas[u]));
  if (P.id !== id) {
    P.id = id;
    if (borrador) Object.assign(P, copia(borrador));
    else {
      P.fotos = propuesta();
      P.titulo = (r.titulos && r.titulos[0]) || "";
      P.linea = r.linea || "";
    }
    P.k = k;
    guardar();
  } else if (modo === "k") {
    // nueva propuesta, pero las fotos que ya has trabajado (frase propia o recorte) se quedan
    const viejas = Object.fromEntries(P.fotos.map(f => [f.uuid, f]));
    const trabajadas = P.fotos.filter(f => fraseEditada(f) || recorteTocado(f));
    const nuevas = r.sugeridas.map(u => viejas[u] || nuevaFotoPaseo(fichas[u]));
    const ya = new Set(nuevas.map(f => f.uuid));
    P.fotos = nuevas.concat(trabajadas.filter(f => !ya.has(f.uuid)));
    ordenarPaseo();
    P.k = k;
    guardar();
    if (P.fotos.length > k) toast(`${P.fotos.length} fotos: se conservan las que ya habías escrito o recortado.`);
  } else if (modo === "reiniciar") {
    P.fotos = propuesta();
    P.k = k;
    guardar();
  }
  pintarPaseos();
  pintarPaseo();
}

function recorteTocado(f) {
  const r = f.recorte || {};
  return Math.abs((r.cx ?? 0.5) - 0.5) > 1e-3 || Math.abs((r.cy ?? 0.5) - 0.5) > 1e-3 || Math.abs((r.zoom ?? 1) - 1) > 1e-3;
}
function fraseEditada(f) {
  const frase = (f.frase || "").trim();
  const auto = (f.auto !== undefined ? f.auto : (fichaPaseo(f.uuid) || {}).frase || "").trim();
  return !!frase && frase !== auto;
}

function nuevaFotoPaseo(f) {
  // `auto` recuerda la sugerencia del ordenador: así sabemos si la frase la has escrito tú
  return { uuid: f.uuid, frase: f.frase, auto: f.frase, recorte: { cx: 0.5, cy: 0.5, zoom: 1 }, km: f.km, alt: f.alt, hora: f.hora };
}
function datosFoto(f) {
  return [f.hora, f.km != null ? `km ${num(f.km)}` : "", f.alt != null ? `${Math.round(f.alt).toLocaleString("es-ES")} m` : ""].filter(Boolean).join(" · ");
}
function fichaPaseo(uuid) { return S.paseo.todas.find(f => f.uuid === uuid); }
function ordenarPaseo() {
  const pos = Object.fromEntries(S.paseo.todas.map((f, i) => [f.uuid, i]));
  S.sel.paseo.fotos.sort((a, b) => (pos[a.uuid] ?? 1e9) - (pos[b.uuid] ?? 1e9));
}

function pintarPaseo() {
  const r = S.paseo, P = S.sel.paseo;
  const p = r.paseo;
  $("#cab-paseo").innerHTML = "";
  $("#cab-paseo").append(
    h("h2", {}, `${fechaCorta(p.inicio)} · ${p.lugar || "Caminata"}`),
    h("p", { class: "ayuda" }, `${p.fotos} fotos · ${num(p.horas)} h` + (p.km ? ` · ${num(p.km)} km` : "") +
      ". Haz clic en las fotos para añadirlas o quitarlas (mínimo 12). La primera será el ORIGEN y la última el FINAL. Las grises tenues son selfies/capturas."),
    h("div", { class: "form-fila" },
      h("button", { class: "sec", onclick: () => {
        if (P.fotos.some(fraseEditada) && !confirm("Se sustituirán las fotos elegidas y sus frases por la propuesta automática. ¿Seguir?")) return;
        abrirPaseo(p.id, "reiniciar", P.k || 12);
      } }, "↺ Volver a la propuesta automática"),
      h("label", { style: "flex-direction:row;align-items:center;gap:6px" }, "Proponer",
        h("select", { onchange: e => abrirPaseo(p.id, "k", parseInt(e.target.value, 10)) },
          [12, 14, 16].map(k => h("option", { value: k, selected: (P.k || 12) === k }, `${k} fotos`)))),
      h("span", { class: "ayuda" }, `Elegidas: ${P.fotos.length}` + (P.fotos.length < MIN_PASEO ? ` (faltan ${MIN_PASEO - P.fotos.length})` : " ✓"))));
  const grid = $("#paseo-fotos");
  grid.innerHTML = "";
  const elegidas = P.fotos.map(f => f.uuid);
  r.todas.forEach((f, i) => {
    const k = elegidas.indexOf(f.uuid);
    const t = h("div", { class: "tarjeta" + (k >= 0 ? " elegida" : "") + (f.util ? "" : " no-util") },
      h("div", { class: "img", style: `background-image:url('${mini(f.uuid)}')`, onclick: () => alternarPaseo(f) }),
      k >= 0 ? h("span", { class: "num-sel" }, k === 0 ? "ORIGEN" : (k === elegidas.length - 1 ? "FINAL" : String(k + 1).padStart(2, "0"))) : "",
      h("div", { class: "pie" }, h("div", {}, [f.hora, f.km != null ? `km ${num(f.km)}` : "", f.suceso ? f.suceso.palabra.toLowerCase() : ""].filter(Boolean).join(" · "))));
    grid.append(t);
  });
  pintarEditorPaseo();
}

function alternarPaseo(f) {
  const P = S.sel.paseo;
  const i = P.fotos.findIndex(x => x.uuid === f.uuid);
  if (i >= 0) P.fotos.splice(i, 1);
  else { P.fotos.push(nuevaFotoPaseo(f)); ordenarPaseo(); }
  guardar();
  pintarPaseo();
}

function pintarEditorPaseo() {
  const P = S.sel.paseo, r = S.paseo;
  const cont = $("#paseo-editor");
  cont.innerHTML = "";
  const titulo = h("input", { class: "titulo-input", value: P.titulo, placeholder: "PALABRA", oninput: e => { P.titulo = e.target.value; guardar(); } });
  const linea = h("textarea", { rows: 2, oninput: e => { P.linea = e.target.value; guardar(); } }, P.linea);
  const chk = (k, txt) => h("label", { class: "check", style: "flex-direction:row;align-items:center" }, h("input", { type: "checkbox", checked: P[k], onchange: e => { P[k] = e.target.checked; guardar(); } }), " " + txt);
  const diseno = h("select", { onchange: e => { P.diseno = e.target.value; guardar(); } },
    h("option", { value: "rejilla", selected: P.diseno === "rejilla" }, "Rejilla regular"),
    h("option", { value: "crece", selected: P.diseno === "crece" }, "Las fotos crecen con el recorrido (H. Sear)"));
  cont.append(h("div", { class: "editor-paseo" },
    h("h3", {}, "Textos al estilo Hamish Fulton"),
    h("p", { class: "ayuda" }, "Fulton titula cada obra con UNA palabra (LIZARDS, CLOUDS, ROAD) y una línea factual que describe la caminata. Bajo cada foto: una frase sobria, en presente, con algo singular de ese momento («Un buitre gira sobre el collado», «Huele a jara»). Los borradores los propone el ordenador: cámbialos por lo que pasó de verdad."),
    h("div", { class: "form-fila" },
      h("label", {}, "Palabra-título", titulo),
      h("div", { class: "chips", style: "max-height:none" }, (r.titulos || []).map(t => h("button", { class: "chip", onclick: () => { P.titulo = t; titulo.value = t; guardar(); } }, t)))),
    h("label", { style: "display:block;margin-bottom:10px;font-size:13px" }, "Línea de la caminata", linea),
    h("div", { class: "form-fila" }, chk("mayusculas", "Frases en MAYÚSCULAS (como Fulton)"), chk("datos", "Hora · km · altitud bajo cada foto"), chk("dibujo", "Dibujar el recorrido/perfil (GPS)"), h("label", {}, "Diseño", diseno),
      S.estado.ia ? h("button", { class: "sec", onclick: frasesIA }, "✨ Proponer frases con IA") : ""),
    h("div", { class: "frases" }, P.fotos.map((f, k) => {
      const fi = fichaPaseo(f.uuid) || {};
      const marca = k === 0 ? "ORIGEN" : (k === P.fotos.length - 1 ? "FINAL" : String(k + 1).padStart(2, "0"));
      return h("div", { class: "frase" },
        h("div", { class: "mini", style: `background-image:url('${mini(f.uuid, 160)}')`, title: "Recortar", onclick: () => editorRecorte({ uuid: f.uuid, recorte: f.recorte, bn: true, alGuardar: rr => { f.recorte = rr; guardar(); } }) }),
        h("div", {}, h("div", { class: "marca-frase" }, marca, h("span", {}, datosFoto(Object.assign({}, fi, f)))),
          h("textarea", { rows: 2, maxlength: 160, placeholder: "¿Qué pasó en este momento?", oninput: e => { f.frase = e.target.value; guardar(); } }, f.frase || ""),
          f.sugerencia_ia ? h("div", { class: "ayuda", style: "margin:2px 0 0" }, `IA: ${f.sugerencia_ia} `,
            h("button", { class: "chip", onclick: () => { f.frase = f.sugerencia_ia; delete f.sugerencia_ia; guardar(); pintarEditorPaseo(); } }, "usar")) :
            (fi.suceso && fi.suceso.frase !== f.frase ? h("div", { class: "ayuda", style: "margin:2px 0 0" }, `sugerencia: ${fi.suceso.frase}`) : "")));
    }))));
}

async function frasesIA() {
  const P = S.sel.paseo;
  await post("/api/ia/frases", { fotos: P.fotos.map(f => { const fi = fichaPaseo(f.uuid) || {}; return { uuid: f.uuid, hora: fi.hora, km: fi.km }; }) });
  toast("Pidiendo frases a la IA…");
  esperarIA(d => {
    const res = d.resultado || {};
    P.fotos.forEach(f => {
      const x = res[f.uuid];
      if (!x || !x.frase) return;
      if (!fraseEditada(f)) f.frase = x.frase;   // vacía o todavía la sugerencia automática
      else f.sugerencia_ia = x.frase;           // escrita a mano: se ofrece, no se sustituye
    });
    const pal = Object.values(res).map(x => x.palabra).filter(Boolean);
    if (pal.length) S.paseo.titulos = [...new Set(pal.concat(S.paseo.titulos || []))].slice(0, 10);
    guardar(); pintarEditorPaseo();
  });
}

// ------------------------------------------------------------------ LÁMINAS
function iniciarLaminas() {
  const o = S.sel.opciones;
  $("#autor").value = S.sel.autor;
  $("#autor").oninput = e => { S.sel.autor = e.target.value; guardar(); };
  $("#orden").value = o.orden; $("#orden").onchange = e => { o.orden = e.target.value; guardar(); };
  $("#contraste").value = o.contraste; $("#contraste").onchange = e => { o.contraste = e.target.value; guardar(); };
  $("#cabecera").checked = o.cabecera !== false; $("#cabecera").onchange = e => { o.cabecera = e.target.checked; guardar(); };
  $("#sin-descargar").checked = !!o.sin_descargar; $("#sin-descargar").onchange = e => { o.sin_descargar = e.target.checked; guardar(); };
  $("#btn-generar").onclick = generarLaminas;
}

function resumenSeleccion() {
  const cont = $("#resumen-seleccion");
  const porCat = {};
  S.sel.arte.forEach(a => (porCat[a.categoria] = (porCat[a.categoria] || 0) + 1));
  cont.innerHTML = "";
  cont.append(h("p", {}, h("b", {}, `Arte involuntario: ${S.sel.arte.length}/24 fotos`), S.sel.arte.length === 24 ? " ✓" : " (el ejercicio pide 24)"),
    h("div", { class: "resumen-cats" }, S.cats.map(c => h("span", { class: porCat[c.id] ? "ok" : "no" }, `${c.nombre}: ${porCat[c.id] || 0}`))),
    h("p", {}, h("b", {}, `Paseo: ${S.sel.paseo.fotos.length} fotos`), S.sel.paseo.fotos.length >= 12 ? " ✓" : " (mínimo 12)",
      S.sel.paseo.titulo ? ` · título «${S.sel.paseo.titulo.toUpperCase()}»` : ""));
}

async function generarLaminas() {
  const btn = $("#btn-generar");
  btn.disabled = true;
  const log = $("#log-generar");
  log.classList.remove("oculto"); log.textContent = "Empezando…";
  $("#resultado").innerHTML = "";
  try { await post("/api/generar", S.sel); } catch (e) { toast(e.message); btn.disabled = false; return; }
  const t = setInterval(async () => {
    const d = await api("/api/generar");
    log.textContent = d.log.join("\n") || "Trabajando…";
    log.scrollTop = log.scrollHeight;
    if (d.estado === "trabajando") return;
    clearInterval(t);
    btn.disabled = false;
    if (d.estado === "error") { log.textContent = d.log.join("\n") || "Ha fallado la generación."; return; }
    log.textContent = (d.log.join("\n") || "") + (d.log.length ? "\n" : "") + "Hecho.";
    mostrarResultado(d.resultado);
  }, 1000);
}

function mostrarResultado(r) {
  const cont = $("#resultado");
  cont.innerHTML = "";
  const ahora = Date.now();
  const f = r.ficheros || {};
  const nombre = p => p.split(/[\\/]/).pop();
  cont.append(h("h3", {}, `✓ ${r.laminas} láminas generadas`),
    h("p", { class: "ayuda" }, `Tipografía: ${r.fuente}. Todo está en la carpeta «salida» del proyecto.`),
    h("div", { class: "enlaces" },
      f.completo_pdf ? h("a", { href: `/salida/${nombre(f.completo_pdf)}?t=${ahora}`, target: "_blank" }, "📄 Entrega completa (PDF)") : "",
      f.arte_pdf ? h("a", { href: `/salida/${nombre(f.arte_pdf)}?t=${ahora}`, target: "_blank" }, "Arte involuntario (PDF)") : "",
      f.paseo_pdf ? h("a", { href: `/salida/${nombre(f.paseo_pdf)}?t=${ahora}`, target: "_blank" }, "Paseo (PDF)") : "",
      h("a", { href: "#", onclick: e => { e.preventDefault(); post("/api/abrir_salida"); } }, "📂 Abrir carpeta")));
  if (r.avisos && r.avisos.length) cont.append(h("div", { class: "avisos" }, h("b", {}, "Revisa:"), h("ul", {}, r.avisos.map(a => h("li", {}, a)))));
  cont.append(h("div", { class: "previas" }, (f.previas || []).map(p => h("a", { href: `/salida/${p.replace("previas/", "")}?t=${ahora}`, target: "_blank" }, h("img", { src: `/salida/${p}?t=${ahora}` })))));
}

iniciar().catch(e => { document.body.innerHTML = `<p style="padding:30px">No se pudo iniciar: ${e.message}</p>`; });
