# Vistas del GrafoColusion en Spanner. Dos sabores:
#  * tablas directas (ColudidoCon, RevisionPendiente, Corrida, ProveedorDetectado)
#  * derived tables con GQL adentro de SQL via GRAPH_TABLE — el patrón de
#    grafo corre en Spanner; Looker agrupa, mide y grafica encima.

# ── GQL: pares que comparten licitaciones ──
view: pares_por_licitacion {
  derived_table: {
    sql:
      SELECT a, b, lic
      FROM GRAPH_TABLE(
        GrafoColusion
        MATCH (p:Proveedor)-[:PARTICIPO_EN]->(l:Licitacion)<-[:PARTICIPO_EN]-(q:Proveedor)
        WHERE p.proveedor_id < q.proveedor_id
        RETURN p.proveedor_id AS a, q.proveedor_id AS b, l.licitacion_id AS lic
      ) ;;
  }
  dimension: a {
    label: "Proveedor A"
    sql: ${TABLE}.a ;;
    # Cierra el ciclo: marcar colusión adicional desde la celda.
    action: {
      label: "Marcar colusión en el grafo"
      url: "https://TU-SERVICIO.run.app/accion/celda"   # ← tu Cloud Run
      param: { name: "origen" value: "lookml_cell" }
      form_param: {
        name: "coludido_con"
        type: string
        label: "Coludido con (proveedor_id)"
        required: yes
      }
      form_param: { name: "notas" type: textarea label: "Notas del analista" }
    }
  }
  dimension: b { label: "Proveedor B" sql: ${TABLE}.b ;; }
  dimension: par { sql: CONCAT(${TABLE}.a, ' ↔ ', ${TABLE}.b) ;; }
  dimension: licitacion { sql: ${TABLE}.lic ;; }
  measure: licitaciones_compartidas {
    type: count_distinct
    sql: ${TABLE}.lic ;;
    drill_fields: [a, b, licitacion]
  }
}

# ── GQL: anillo alcanzable desde un proveedor (1 a 3 saltos, sin dirección) ──
view: anillo {
  parameter: proveedor_raiz {
    type: unquoted
    default_value: "ACME"
    description: "Proveedor desde el que se expande el anillo"
  }
  derived_table: {
    sql:
      SELECT origen, miembro
      FROM GRAPH_TABLE(
        GrafoColusion
        MATCH (p:Proveedor {proveedor_id: '{% parameter proveedor_raiz %}'})
              -[:COLUDIDO_CON]-{1,3}(q:Proveedor)
        RETURN DISTINCT p.proveedor_id AS origen, q.proveedor_id AS miembro
      ) ;;
  }
  dimension: origen { sql: ${TABLE}.origen ;; }
  dimension: miembro { sql: ${TABLE}.miembro ;; }
  measure: tamano_anillo { type: count_distinct sql: ${TABLE}.miembro ;; }
}

# ── Tabla: aristas COLUDIDO_CON (lo que escribe la action) ──
view: aristas_colusion {
  sql_table_name: ColudidoCon ;;
  dimension: llave {
    primary_key: yes
    hidden: yes
    sql: CONCAT(${TABLE}.proveedor_id, '|', ${TABLE}.destino_proveedor_id,
                '|', ${TABLE}.corrida_id) ;;
  }
  dimension: proveedor_a { sql: ${TABLE}.proveedor_id ;; }
  dimension: proveedor_b { sql: ${TABLE}.destino_proveedor_id ;; }
  dimension: corrida_id { sql: ${TABLE}.corrida_id ;; }
  dimension: score { type: number sql: ${TABLE}.score ;; }
  dimension: senales { sql: TO_JSON_STRING(${TABLE}.props) ;; }
  measure: conclusiones { type: count drill_fields: [proveedor_a, proveedor_b, score, corrida_id] }
  measure: score_promedio { type: average sql: ${score} ;; value_format_name: decimal_2 }
}

# ── Tabla: cola de revisión humana (el camino ámbar, dentro de Looker) ──
view: revision_pendiente {
  sql_table_name: RevisionPendiente ;;
  dimension: corrida_id { primary_key: yes sql: ${TABLE}.corrida_id ;; }
  dimension: estado { sql: ${TABLE}.estado ;; }
  dimension: score_propuesto {
    type: number
    sql: CAST(JSON_VALUE(${TABLE}.conclusion, '$.score') AS FLOAT64) ;;
  }
  dimension: resumen { sql: JSON_VALUE(${TABLE}.conclusion, '$.resumen') ;; }
  dimension_group: creado {
    type: time
    timeframes: [raw, time, date, week]
    sql: ${TABLE}.creado_en ;;
  }
  measure: pendientes { type: count filters: [estado: "PENDIENTE"] }
  measure: total { type: count }
}

# ── Tabla: proveniencia ──
view: corridas {
  sql_table_name: Corrida ;;
  dimension: corrida_id { primary_key: yes sql: ${TABLE}.corrida_id ;; }
  dimension: origen { sql: ${TABLE}.origen ;; }
  dimension: usuario { sql: ${TABLE}.usuario ;; }
  dimension: consulta { sql: TO_JSON_STRING(${TABLE}.consulta_looker) ;; }
  dimension_group: creado {
    type: time
    timeframes: [raw, time, date, week, month]
    sql: ${TABLE}.creado_en ;;
  }
  measure: total_corridas { type: count }
}

view: proveedor_detectado {
  sql_table_name: ProveedorDetectado ;;
  dimension: llave {
    primary_key: yes
    hidden: yes
    sql: CONCAT(${TABLE}.proveedor_id, '|', ${TABLE}.corrida_id) ;;
  }
  dimension: proveedor { sql: ${TABLE}.proveedor_id ;; }
  dimension: corrida_id { sql: ${TABLE}.corrida_id ;; }
  dimension: score { type: number sql: ${TABLE}.score ;; }
  measure: detecciones { type: count drill_fields: [proveedor, score, corrida_id] }
  measure: proveedores_unicos { type: count_distinct sql: ${TABLE}.proveedor_id ;; }
  measure: score_promedio { type: average sql: ${score} ;; value_format_name: decimal_2 }
}
