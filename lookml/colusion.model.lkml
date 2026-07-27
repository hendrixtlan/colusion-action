# Modelo: el grafo de colusión de vuelta en Looker.
# Requiere una conexión con dialecto "Google Spanner" apuntando a la base
# del grafo (Admin → Connections; project / instance / database).
connection: "spanner_colusion"

include: "grafo_colusion.view.lkml"

# Pares que comparten licitaciones — la vista de anillos candidatos.
# GQL vía GRAPH_TABLE: el patrón corre en Spanner, Looker agrega encima.
explore: pares_por_licitacion {
  label: "Colusión: pares por licitaciones compartidas"
}

# Las conclusiones escritas por la action (aristas COLUDIDO_CON) con su corrida.
explore: aristas_colusion {
  label: "Colusión: conclusiones (aristas)"
  join: corridas {
    sql_on: ${aristas_colusion.corrida_id} = ${corridas.corrida_id} ;;
    relationship: many_to_one
    type: left_outer
  }
}

# Anillo alcanzable desde un proveedor (camino cuantificado 1..3 saltos).
explore: anillo {
  label: "Colusión: anillo desde un proveedor"
}

# La cola de revisión humana como contenido de Looker.
explore: revision_pendiente {
  label: "Colusión: revisión pendiente"
}

# Proveniencia: qué detectó cada corrida.
explore: proveedor_detectado {
  label: "Colusión: detecciones por corrida"
  join: corridas {
    sql_on: ${proveedor_detectado.corrida_id} = ${corridas.corrida_id} ;;
    relationship: many_to_one
    type: left_outer
  }
}
