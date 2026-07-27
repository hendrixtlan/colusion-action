/**
 * grafo_fuerza — visualización custom de Looker (API de custom viz):
 * grafo dirigido por fuerzas para anillos de colusión.
 *
 * Campos esperados en el Explore:
 *   dimensión 1 = nodo origen  (p.ej. pares_por_licitacion.a)
 *   dimensión 2 = nodo destino (p.ej. pares_por_licitacion.b)
 *   medida  1   = peso de la arista, opcional (licitaciones_compartidas, score)
 *
 * Registro (Admin → Platform → Visualizations → Add):
 *   ID: grafo_fuerza · Main: https://TU-SERVICIO.run.app/viz/grafo_fuerza.js
 *   Dependencies: https://d3js.org/d3.v7.min.js
 * (o vía manifest LookML con `visualization:` si prefieren empaquetarlo.)
 *
 * Decisiones de robustez:
 *  - El layout corre SÍNCRONO (ticks acotados) y luego llama done():
 *    render determinista, compatible con PDF/schedules, y testeable.
 *  - Tope de nodos con mensaje claro: un force layout no es para el grafo
 *    completo; se dibuja el subgrafo que el Explore ya limitó (GQL primero).
 */
(function () {
  var viz = {
    id: "grafo_fuerza",
    label: "Grafo de colusión (fuerzas)",

    options: {
      color_nodo: {
        label: "Color de nodo", type: "string", display: "color",
        default: "#4285F4", section: "Estilo", order: 1
      },
      color_arista: {
        label: "Color de arista", type: "string", display: "color",
        default: "#9AA0A6", section: "Estilo", order: 2
      },
      max_nodos: {
        label: "Máximo de nodos a dibujar", type: "number",
        default: 300, section: "Datos", order: 1
      },
      distancia: {
        label: "Distancia entre nodos", type: "number",
        default: 90, section: "Física", order: 1
      },
      carga: {
        label: "Repulsión (carga)", type: "number",
        default: 220, section: "Física", order: 2
      },
      etiquetas: {
        label: "Mostrar etiquetas", type: "boolean",
        default: true, section: "Estilo", order: 3
      }
    },

    create: function (element, config) {
      element.innerHTML = "";
      this._svg = d3.select(element).append("svg")
        .style("width", "100%").style("height", "100%");
      this._capa = this._svg.append("g").attr("class", "capa");
    },

    updateAsync: function (data, element, config, queryResponse, details, done) {
      this.clearErrors();
      var dims = queryResponse.fields.dimension_like || [];
      var meds = queryResponse.fields.measure_like || [];
      if (dims.length < 2) {
        this.addError({
          title: "Faltan campos",
          message: "Se requieren 2 dimensiones (origen y destino) y " +
                   "opcionalmente 1 medida como peso de la arista."
        });
        return;
      }
      var dimA = dims[0].name, dimB = dims[1].name;
      var med = meds.length ? meds[0].name : null;

      // ── filas → nodos y aristas (con grado por nodo) ──
      var nodos = {}, aristas = [], filaDe = {};
      data.forEach(function (fila) {
        var a = fila[dimA] && fila[dimA].value;
        var b = fila[dimB] && fila[dimB].value;
        if (a == null || b == null) return;
        a = String(a); b = String(b);
        nodos[a] = (nodos[a] || 0) + 1;
        nodos[b] = (nodos[b] || 0) + 1;
        var peso = med && fila[med] && typeof fila[med].value === "number"
          ? fila[med].value : 1;
        aristas.push({ source: a, target: b, peso: peso });
        filaDe[a + "→" + b] = fila;   // para el drill de Looker
      });

      var ids = Object.keys(nodos);
      var tope = Number(config.max_nodos || 300);
      if (!ids.length) {
        this.addError({ title: "Sin datos", message: "La consulta no trae filas." });
        return;
      }
      if (ids.length > tope) {
        this.addError({
          title: "Demasiados nodos (" + ids.length + ")",
          message: "Un force layout se satura; limita la consulta (LIMIT, " +
                   "filtros o el Explore de anillo) o sube 'Máximo de nodos'."
        });
        return;
      }

      var ancho = element.clientWidth || 800;
      var alto = element.clientHeight || 500;
      var maxGrado = d3.max(ids, function (n) { return nodos[n]; }) || 1;
      var maxPeso = d3.max(aristas, function (e) { return e.peso; }) || 1;
      var listaNodos = ids.map(function (n) { return { id: n, grado: nodos[n] }; });

      // ── layout síncrono: determinista y listo para PDF ──
      var sim = d3.forceSimulation(listaNodos)
        .force("link", d3.forceLink(aristas).id(function (d) { return d.id; })
          .distance(Number(config.distancia || 90)))
        .force("carga", d3.forceManyBody().strength(-Number(config.carga || 220)))
        .force("centro", d3.forceCenter(ancho / 2, alto / 2))
        .force("choque", d3.forceCollide(18))
        .stop();
      for (var i = 0; i < 250 && sim.alpha() > 0.02; i++) sim.tick();

      // ── render ──
      var g = this._capa;
      g.selectAll("*").remove();
      this._svg.attr("viewBox", "0 0 " + ancho + " " + alto);
      this._svg.call(d3.zoom().scaleExtent([0.3, 4]).on("zoom", function (ev) {
        g.attr("transform", ev.transform);
      }));

      g.selectAll("line").data(aristas).enter().append("line")
        .attr("stroke", config.color_arista || "#9AA0A6")
        .attr("stroke-opacity", 0.6)
        .attr("stroke-width", function (e) {
          return 1 + 4 * (e.peso / maxPeso);
        })
        .attr("x1", function (e) { return e.source.x; })
        .attr("y1", function (e) { return e.source.y; })
        .attr("x2", function (e) { return e.target.x; })
        .attr("y2", function (e) { return e.target.y; })
        .on("click", function (ev, e) {   // drill nativo de Looker en la arista
          var fila = filaDe[e.source.id + "→" + e.target.id];
          var celda = fila && fila[dimA];
          if (celda && celda.links && typeof LookerCharts !== "undefined") {
            LookerCharts.Utils.openDrillMenu({ links: celda.links, event: ev });
          }
        });

      var nodo = g.selectAll("g.nodo").data(listaNodos).enter()
        .append("g").attr("class", "nodo")
        .attr("transform", function (d) {
          return "translate(" + d.x + "," + d.y + ")";
        });
      nodo.append("circle")
        .attr("r", function (d) { return 7 + 9 * (d.grado / maxGrado); })
        .attr("fill", config.color_nodo || "#4285F4")
        .attr("stroke", "#fff").attr("stroke-width", 1.5);
      nodo.append("title").text(function (d) {
        return d.id + " · grado " + d.grado;
      });
      if (config.etiquetas !== false) {
        nodo.append("text").text(function (d) { return d.id; })
          .attr("x", 12).attr("y", 4)
          .attr("font-family", "sans-serif").attr("font-size", "11px")
          .attr("fill", "#3c4043");
      }

      // arrastre re-calienta la simulación (interactivo en el navegador)
      nodo.call(d3.drag()
        .on("start", function (ev, d) { d.fx = d.x; d.fy = d.y; })
        .on("drag", function (ev, d) {
          d.fx = ev.x; d.fy = ev.y;
          sim.alpha(0.3).tick();
          g.selectAll("line")
            .attr("x1", function (e) { return e.source.x; })
            .attr("y1", function (e) { return e.source.y; })
            .attr("x2", function (e) { return e.target.x; })
            .attr("y2", function (e) { return e.target.y; });
          g.selectAll("g.nodo").attr("transform", function (n) {
            return "translate(" + n.x + "," + n.y + ")";
          });
        })
        .on("end", function (ev, d) { d.fx = null; d.fy = null; }));

      done();
    }
  };

  looker.plugins.visualizations.add(viz);
})();
