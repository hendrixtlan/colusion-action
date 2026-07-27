// Prueba del custom viz contra un DOM real (jsdom) y d3 v7 de verdad:
// simula el contrato de Looker (create + updateAsync) y verifica el SVG.
import { JSDOM } from "jsdom";
import { readFileSync } from "fs";

const dom = new JSDOM("<div id='viz' style='width:800px;height:500px'></div>",
                      { pretendToBeVisual: true });
global.window = dom.window; global.document = dom.window.document;
Object.defineProperty(global, "navigator", { value: dom.window.navigator, configurable: true });

const d3 = await import("d3");
let registrado = null;
const looker = { plugins: { visualizations: { add: v => (registrado = v) } } };
let drill = 0;
const LookerCharts = { Utils: { openDrillMenu: () => drill++ } };

const codigo = readFileSync("../app/estaticos/grafo_fuerza.js", "utf8");
new Function("looker", "d3", "LookerCharts", codigo)(looker, d3, LookerCharts);
if (!registrado || registrado.id !== "grafo_fuerza") throw new Error("no se registró el viz");
console.log("✔ registrado:", registrado.id, "-", registrado.label);

const el = document.getElementById("viz");
Object.defineProperty(el, "clientWidth", { value: 800 });
Object.defineProperty(el, "clientHeight", { value: 500 });
const errores = [];
registrado.addError = e => errores.push(e);
registrado.clearErrors = () => errores.length = 0;
registrado.trigger = () => {};

registrado.create(el, {});

const qr = { fields: {
  dimension_like: [{ name: "p.a" }, { name: "p.b" }],
  measure_like: [{ name: "p.compartidas" }] } };
const datos = [
  { "p.a": { value: "ACME", links: [{label:"drill"}] }, "p.b": { value: "BETA" }, "p.compartidas": { value: 8 } },
  { "p.a": { value: "ACME", links: [] }, "p.b": { value: "GAMA" }, "p.compartidas": { value: 3 } },
  { "p.a": { value: "BETA", links: [] }, "p.b": { value: "GAMA" }, "p.compartidas": { value: 5 } },
  { "p.a": { value: "GAMA", links: [] }, "p.b": { value: "DELTA" }, "p.compartidas": { value: 1 } },
];
let termino = false;
registrado.updateAsync(datos, el, { etiquetas: true }, qr, {}, () => (termino = true));

if (!termino) throw new Error("no llamó done()");
const circulos = el.querySelectorAll("circle").length;
const lineas = el.querySelectorAll("line").length;
const textos = el.querySelectorAll("text").length;
console.log(`✔ render: ${circulos} nodos, ${lineas} aristas, ${textos} etiquetas`);
if (circulos !== 4 || lineas !== 4 || textos !== 4) throw new Error("conteos incorrectos");

// posiciones reales calculadas por la simulación (no todo en 0,0)
const xs = [...el.querySelectorAll("g.nodo")].map(n => n.getAttribute("transform"));
if (new Set(xs).size < 4) throw new Error("la simulación no separó los nodos");
console.log("✔ layout: 4 posiciones distintas calculadas por d3-force");

// grosor de arista proporcional al peso (8 vs 1)
const anchos = [...el.querySelectorAll("line")].map(l => +l.getAttribute("stroke-width"));
if (Math.max(...anchos) <= Math.min(...anchos)) throw new Error("peso no refleja grosor");
console.log("✔ aristas ponderadas:", anchos.map(a => a.toFixed(1)).join(", "));

// caminos de error: 1 dimensión y tope de nodos
registrado.updateAsync(datos, el, {}, { fields: { dimension_like: [{name:"x"}], measure_like: [] } }, {}, ()=>{});
if (!errores.some(e => e.title === "Faltan campos")) throw new Error("no avisó campos faltantes");
registrado.updateAsync(datos, el, { max_nodos: 2 }, qr, {}, ()=>{});
if (!errores.some(e => /Demasiados nodos/.test(e.title))) throw new Error("no aplicó el tope");
console.log("✔ errores guiados: campos faltantes y tope de nodos");

// drill: click en la arista ACME→BETA dispara openDrillMenu
registrado.clearErrors();
registrado.updateAsync(datos, el, {}, qr, {}, ()=>{});
const linea = el.querySelector("line");
linea.dispatchEvent(new dom.window.MouseEvent("click", { bubbles: true }));
if (drill !== 1) throw new Error("el drill de Looker no se disparó");
console.log("✔ drill nativo de Looker en la arista");
console.log("\n✔✔ VIZ VALIDADO: contrato Looker + d3-force + DOM real");
