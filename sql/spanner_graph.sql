-- GrafoColusion en Spanner Graph.
--
-- Requisitos:
--   * Instancia Spanner de edicion ENTERPRISE (o Enterprise Plus): Spanner
--     Graph no esta disponible en la edicion Standard. 100 processing units
--     bastan para arrancar.
--   * Base de datos en dialecto GoogleSQL (Spanner Graph no existe en el
--     dialecto PostgreSQL de Spanner).
--
-- Mismo estilo que fleet-agent: aristas interleaved en el nodo origen para
-- localidad fisica, proveniencia colgada del nodo Corrida.

CREATE TABLE Proveedor (
  proveedor_id   STRING(128) NOT NULL,
  nombre         STRING(256),
  actualizado_en TIMESTAMP NOT NULL OPTIONS (allow_commit_timestamp = true),
) PRIMARY KEY (proveedor_id);

CREATE TABLE Licitacion (
  licitacion_id  STRING(128) NOT NULL,
  descripcion    STRING(MAX),
  actualizado_en TIMESTAMP NOT NULL OPTIONS (allow_commit_timestamp = true),
) PRIMARY KEY (licitacion_id);

-- Proveniencia: por que existe cada conclusion (quien, cuando, con que
-- consulta de Looker). Toda escritura de la action cuelga de una Corrida.
CREATE TABLE Corrida (
  corrida_id      STRING(128) NOT NULL,
  origen          STRING(64) NOT NULL,   -- 'looker_action'
  usuario         STRING(256),
  consulta_looker JSON,                  -- scheduled_plan: titulo, url, query
  creado_en       TIMESTAMP NOT NULL OPTIONS (allow_commit_timestamp = true),
) PRIMARY KEY (corrida_id);

-- ── Aristas ──

CREATE TABLE ParticipoEn (
  proveedor_id   STRING(128) NOT NULL,
  licitacion_id  STRING(128) NOT NULL,
  props          JSON,                   -- monto, postura, resultado...
  actualizado_en TIMESTAMP NOT NULL OPTIONS (allow_commit_timestamp = true),
) PRIMARY KEY (proveedor_id, licitacion_id),
  INTERLEAVE IN PARENT Proveedor ON DELETE CASCADE;

-- La corrida forma parte de la llave: cada conclusion agrega su propia arista
-- y reejecutar la misma corrida es idempotente (insert_or_update).
CREATE TABLE ColudidoCon (
  proveedor_id         STRING(128) NOT NULL,
  destino_proveedor_id STRING(128) NOT NULL,
  corrida_id           STRING(128) NOT NULL,
  score                FLOAT64,
  props                JSON,             -- senales, evidencia por fila
) PRIMARY KEY (proveedor_id, destino_proveedor_id, corrida_id),
  INTERLEAVE IN PARENT Proveedor ON DELETE CASCADE;

CREATE TABLE ProveedorDetectado (
  proveedor_id STRING(128) NOT NULL,
  corrida_id   STRING(128) NOT NULL,
  score        FLOAT64,
  evidencia    JSON,
) PRIMARY KEY (proveedor_id, corrida_id),
  INTERLEAVE IN PARENT Proveedor ON DELETE CASCADE;

-- Cola de revision humana: la ruta 'revision' del form de la action.
CREATE TABLE RevisionPendiente (
  corrida_id STRING(128) NOT NULL,
  conclusion JSON,
  estado     STRING(32) NOT NULL,        -- PENDIENTE | APROBADA | RECHAZADA
  creado_en  TIMESTAMP NOT NULL OPTIONS (allow_commit_timestamp = true),
) PRIMARY KEY (corrida_id);

-- ── El grafo de propiedades ──

CREATE PROPERTY GRAPH GrafoColusion
  NODE TABLES (
    Proveedor,
    Licitacion,
    Corrida
  )
  EDGE TABLES (
    ParticipoEn
      SOURCE KEY (proveedor_id) REFERENCES Proveedor (proveedor_id)
      DESTINATION KEY (licitacion_id) REFERENCES Licitacion (licitacion_id)
      LABEL PARTICIPO_EN,
    ColudidoCon
      SOURCE KEY (proveedor_id) REFERENCES Proveedor (proveedor_id)
      DESTINATION KEY (destino_proveedor_id) REFERENCES Proveedor (proveedor_id)
      LABEL COLUDIDO_CON,
    ProveedorDetectado
      SOURCE KEY (proveedor_id) REFERENCES Proveedor (proveedor_id)
      DESTINATION KEY (corrida_id) REFERENCES Corrida (corrida_id)
      LABEL DETECTADO_EN
  );

-- ═══ Consultas GQL de ejemplo (Spanner Studio) ═══
--
-- 1) Pares que comparten licitaciones (candidatos a rotacion de posturas):
--
--   GRAPH GrafoColusion
--   MATCH (p:Proveedor)-[:PARTICIPO_EN]->(l:Licitacion)<-[:PARTICIPO_EN]-(q:Proveedor)
--   WHERE p.proveedor_id < q.proveedor_id
--   RETURN p.proveedor_id AS a, q.proveedor_id AS b,
--          COUNT(l.licitacion_id) AS compartidas
--   GROUP BY a, b
--   NEXT
--   RETURN a, b, compartidas
--   ORDER BY compartidas DESC
--   LIMIT 50
--
-- 2) Anillo alcanzable desde un proveedor via COLUDIDO_CON (1 a 3 saltos):
--
--   GRAPH GrafoColusion
--   MATCH (p:Proveedor {proveedor_id: @proveedor})
--         -[:COLUDIDO_CON]-{1,3}(q:Proveedor)
--   RETURN DISTINCT q.proveedor_id
--
-- 3) Proveniencia: todo lo concluido por una corrida, con score:
--
--   GRAPH GrafoColusion
--   MATCH (p:Proveedor)-[d:DETECTADO_EN]->(c:Corrida {corrida_id: @corrida})
--   RETURN p.proveedor_id, d.score
--   ORDER BY d.score DESC
