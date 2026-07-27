# Dashboard del grafo. Los dos primeros tiles nacen como tabla/columna;
# tras instalar Chord y Sankey del Marketplace (Marketplace → Visualizations),
# edítalos en la UI y cambia el tipo de visualización: Chord con
# (a, b, licitaciones_compartidas) dibuja los anillos.
- dashboard: grafo_colusion
  title: "Grafo de colusión"
  layout: newspaper
  elements:

  - name: pares_candidatos
    title: "Pares por licitaciones compartidas (→ Chord del Marketplace)"
    model: colusion
    explore: pares_por_licitacion
    type: looker_grid
    fields: [pares_por_licitacion.a, pares_por_licitacion.b,
             pares_por_licitacion.licitaciones_compartidas]
    sorts: [pares_por_licitacion.licitaciones_compartidas desc]
    limit: 50
    row: 0
    col: 0
    width: 14
    height: 8

  - name: pendientes
    title: "Conclusiones esperando revisión humana"
    model: colusion
    explore: revision_pendiente
    type: single_value
    fields: [revision_pendiente.pendientes]
    row: 0
    col: 14
    width: 10
    height: 4

  - name: score_conclusiones
    title: "Conclusiones por score (aristas COLUDIDO_CON)"
    model: colusion
    explore: aristas_colusion
    type: looker_column
    fields: [aristas_colusion.proveedor_a, aristas_colusion.score_promedio,
             aristas_colusion.conclusiones]
    sorts: [aristas_colusion.score_promedio desc]
    limit: 20
    row: 4
    col: 14
    width: 10
    height: 8

  - name: cola_revision
    title: "Cola de revisión (camino ámbar)"
    model: colusion
    explore: revision_pendiente
    type: looker_grid
    fields: [revision_pendiente.corrida_id, revision_pendiente.score_propuesto,
             revision_pendiente.resumen, revision_pendiente.estado,
             revision_pendiente.creado_time]
    filters:
      revision_pendiente.estado: "PENDIENTE"
    sorts: [revision_pendiente.creado_time desc]
    row: 8
    col: 0
    width: 14
    height: 6

  - name: corridas_en_el_tiempo
    title: "Corridas por semana (proveniencia)"
    model: colusion
    explore: proveedor_detectado
    type: looker_column
    fields: [corridas.creado_week, proveedor_detectado.detecciones,
             proveedor_detectado.proveedores_unicos]
    sorts: [corridas.creado_week]
    row: 12
    col: 14
    width: 10
    height: 6
