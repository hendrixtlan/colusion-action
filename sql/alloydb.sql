-- GrafoColusion en AlloyDB (PostgreSQL): la alternativa de costo.
--
-- AlloyDB gestionado no incluye una extension de grafos en su lista de
-- extensiones soportadas, asi que el grafo se modela relacional (tablas de
-- nodos y aristas, espejo del DDL de Spanner) y los recorridos se hacen con
-- WITH RECURSIVE. Si el cliente migra despues a Spanner Graph, las tablas
-- mapean 1 a 1 y solo se agrega el CREATE PROPERTY GRAPH.

CREATE TABLE IF NOT EXISTS proveedor (
  proveedor_id   text PRIMARY KEY,
  nombre         text,
  actualizado_en timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS licitacion (
  licitacion_id  text PRIMARY KEY,
  descripcion    text,
  actualizado_en timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS corrida (
  corrida_id      text PRIMARY KEY,
  origen          text NOT NULL,          -- 'looker_action'
  usuario         text,
  consulta_looker jsonb,
  creado_en       timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS participo_en (
  proveedor_id   text NOT NULL REFERENCES proveedor,
  licitacion_id  text NOT NULL REFERENCES licitacion,
  props          jsonb NOT NULL DEFAULT '{}'::jsonb,
  actualizado_en timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (proveedor_id, licitacion_id)
);
CREATE INDEX IF NOT EXISTS participo_en_licitacion
  ON participo_en (licitacion_id);

CREATE TABLE IF NOT EXISTS coludido_con (
  proveedor_id         text NOT NULL REFERENCES proveedor,
  destino_proveedor_id text NOT NULL REFERENCES proveedor,
  corrida_id           text NOT NULL REFERENCES corrida,
  score                double precision,
  props                jsonb NOT NULL DEFAULT '{}'::jsonb,
  PRIMARY KEY (proveedor_id, destino_proveedor_id, corrida_id)
);
CREATE INDEX IF NOT EXISTS coludido_con_destino
  ON coludido_con (destino_proveedor_id);

CREATE TABLE IF NOT EXISTS proveedor_detectado (
  proveedor_id text NOT NULL REFERENCES proveedor,
  corrida_id   text NOT NULL REFERENCES corrida,
  score        double precision,
  evidencia    jsonb,
  PRIMARY KEY (proveedor_id, corrida_id)
);

CREATE TABLE IF NOT EXISTS revision_pendiente (
  corrida_id text PRIMARY KEY,
  conclusion jsonb,
  estado     text NOT NULL DEFAULT 'PENDIENTE',
  creado_en  timestamptz NOT NULL DEFAULT now()
);

-- ═══ Consultas de ejemplo (equivalentes a las GQL de Spanner) ═══

-- 1) Pares que comparten licitaciones (candidatos a rotacion de posturas):
--
--   SELECT p.proveedor_id AS a, q.proveedor_id AS b,
--          count(*) AS compartidas
--   FROM participo_en p
--   JOIN participo_en q USING (licitacion_id)
--   WHERE p.proveedor_id < q.proveedor_id
--   GROUP BY 1, 2
--   ORDER BY compartidas DESC
--   LIMIT 50;

-- 2) Anillo alcanzable desde un proveedor via COLUDIDO_CON (recorrido
--    recursivo sin direccion, tope de 3 saltos):
--
--   WITH RECURSIVE anillo (proveedor_id, saltos) AS (
--     SELECT $1::text, 0
--     UNION
--     SELECT CASE WHEN c.proveedor_id = a.proveedor_id
--                 THEN c.destino_proveedor_id
--                 ELSE c.proveedor_id END,
--            a.saltos + 1
--     FROM anillo a
--     JOIN coludido_con c
--       ON a.proveedor_id IN (c.proveedor_id, c.destino_proveedor_id)
--     WHERE a.saltos < 3
--   )
--   SELECT DISTINCT proveedor_id FROM anillo;

-- 3) Proveniencia: todo lo concluido por una corrida, con score:
--
--   SELECT pd.proveedor_id, pd.score
--   FROM proveedor_detectado pd
--   WHERE pd.corrida_id = $1
--   ORDER BY pd.score DESC;
