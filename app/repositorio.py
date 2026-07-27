"""Puerto GrafoRepositorio con dos adaptadores: Spanner Graph y AlloyDB.

El contrato es identico en ambos:
  - persistir(): vaciado idempotente de una ConclusionColusion con proveniencia
    (nodo Corrida). En Spanner es insert_or_update; en AlloyDB es
    INSERT ... ON CONFLICT DO UPDATE. Reejecutar la misma corrida no duplica.
  - encolar_revision(): ruta humana; la conclusion queda en RevisionPendiente
    y NO toca el grafo hasta que alguien la apruebe (y llame persistir()).

Elegir backend con la variable de entorno GRAFO_BACKEND = "spanner" | "alloydb".
El esquema es espejo (ver sql/): si el cliente empieza en AlloyDB por costo y
luego migra a Spanner, las tablas mapean 1 a 1 y solo se agrega el
CREATE PROPERTY GRAPH.
"""
from __future__ import annotations

import json
import os
from typing import Protocol

from contratos import ConclusionColusion, TipoArista, TipoNodo


class GrafoRepositorio(Protocol):
    def persistir(self, corrida_id: str, conclusion: ConclusionColusion,
                  consulta_looker: dict | None = None, usuario: str = "") -> None: ...

    def encolar_revision(self, corrida_id: str,
                         conclusion: ConclusionColusion) -> None: ...


def construir_repositorio() -> GrafoRepositorio:
    backend = os.environ.get("GRAFO_BACKEND", "spanner").lower()
    if backend == "alloydb":
        return AlloyDBGrafo()
    return SpannerGrafo()


# ── Coleccion comun: de la conclusion a filas planas (ambos backends) ──

def _coleccionar(c: ConclusionColusion):
    proveedores = {n.id for n in c.nodos if n.tipo == TipoNodo.PROVEEDOR}
    licitaciones = {n.id for n in c.nodos if n.tipo == TipoNodo.LICITACION}
    participo: dict[tuple[str, str], dict] = {}
    coludido: dict[tuple[str, str], dict] = {}

    for a in c.aristas:
        if a.tipo == TipoArista.PARTICIPO_EN:
            proveedores.add(a.origen)
            licitaciones.add(a.destino)
            participo[(a.origen, a.destino)] = a.props
        elif a.tipo == TipoArista.COLUDIDO_CON:
            proveedores.update((a.origen, a.destino))
            coludido[(a.origen, a.destino)] = a.props

    return sorted(proveedores), sorted(licitaciones), participo, coludido


def _score_arista(props: dict, defecto: float) -> float:
    valor = props.get("score")
    return float(valor) if isinstance(valor, (int, float)) else defecto


# ── Adaptador Spanner Graph ──

class SpannerGrafo:
    """Escrituras via mutaciones batch, como vaciado.py de fleet-agent.

    Requiere una instancia Spanner de edicion ENTERPRISE (o superior) y base
    en dialecto GoogleSQL: Spanner Graph no existe en Standard ni en el
    dialecto PostgreSQL. DDL en sql/spanner_graph.sql.
    """

    def __init__(self) -> None:
        from google.cloud import spanner  # import perezoso: solo si se usa
        self._sp = spanner
        cliente = spanner.Client(project=os.environ["GOOGLE_CLOUD_PROJECT"])
        self._db = (cliente.instance(os.environ["SPANNER_INSTANCE"])
                    .database(os.environ["SPANNER_DATABASE"]))

    def persistir(self, corrida_id, conclusion, consulta_looker=None, usuario=""):
        sp = self._sp
        ts = sp.COMMIT_TIMESTAMP
        provs, lics, participo, coludido = _coleccionar(conclusion)

        with self._db.batch() as b:
            b.insert_or_update(
                table="Corrida",
                columns=("corrida_id", "origen", "usuario", "consulta_looker",
                         "creado_en"),
                values=[(corrida_id, "looker_action", usuario,
                         sp.JsonObject(consulta_looker or {}), ts)],
            )
            if provs:
                b.insert_or_update(
                    table="Proveedor",
                    columns=("proveedor_id", "actualizado_en"),
                    values=[(p, ts) for p in provs],
                )
            if lics:
                b.insert_or_update(
                    table="Licitacion",
                    columns=("licitacion_id", "actualizado_en"),
                    values=[(l, ts) for l in lics],
                )
            if participo:
                b.insert_or_update(
                    table="ParticipoEn",
                    columns=("proveedor_id", "licitacion_id", "props",
                             "actualizado_en"),
                    values=[(p, l, sp.JsonObject(props), ts)
                            for (p, l), props in sorted(participo.items())],
                )
            if coludido:
                b.insert_or_update(
                    table="ColudidoCon",
                    columns=("proveedor_id", "destino_proveedor_id", "corrida_id",
                             "score", "props"),
                    values=[(p, q, corrida_id,
                             _score_arista(props, conclusion.score),
                             sp.JsonObject(props))
                            for (p, q), props in sorted(coludido.items())],
                )
            if provs:
                b.insert_or_update(
                    table="ProveedorDetectado",
                    columns=("proveedor_id", "corrida_id", "score", "evidencia"),
                    values=[(p, corrida_id, conclusion.score,
                             sp.JsonObject({"resumen": conclusion.resumen}))
                            for p in provs],
                )

    def encolar_revision(self, corrida_id, conclusion):
        sp = self._sp
        with self._db.batch() as b:
            b.insert_or_update(
                table="RevisionPendiente",
                columns=("corrida_id", "conclusion", "estado", "creado_en"),
                values=[(corrida_id,
                         sp.JsonObject(json.loads(conclusion.model_dump_json())),
                         "PENDIENTE", sp.COMMIT_TIMESTAMP)],
            )


# ── Adaptador AlloyDB (PostgreSQL) ──

class AlloyDBGrafo:
    """Mismo esquema en AlloyDB; upserts con ON CONFLICT y consultas de anillos
    con WITH RECURSIVE (AlloyDB gestionado no trae extension de grafos, asi que
    el grafo se modela relacional; ver sql/alloydb.sql).

    Conexion: ALLOYDB_DSN, p. ej.
      host=10.x.x.x port=5432 dbname=colusion user=accion password=... sslmode=require
    o via AlloyDB Auth Proxy / Language Connector apuntando a localhost.
    """

    def __init__(self) -> None:
        import psycopg  # import perezoso
        from psycopg.types.json import Json
        self._pg = psycopg
        self._Json = Json
        self._dsn = os.environ["ALLOYDB_DSN"]

    def persistir(self, corrida_id, conclusion, consulta_looker=None, usuario=""):
        J = self._Json
        provs, lics, participo, coludido = _coleccionar(conclusion)

        with self._pg.connect(self._dsn) as con, con.cursor() as cur:
            cur.execute(
                """INSERT INTO corrida (corrida_id, origen, usuario, consulta_looker)
                   VALUES (%s, 'looker_action', %s, %s)
                   ON CONFLICT (corrida_id) DO UPDATE
                     SET consulta_looker = EXCLUDED.consulta_looker""",
                (corrida_id, usuario, J(consulta_looker or {})),
            )
            if provs:
                cur.executemany(
                    """INSERT INTO proveedor (proveedor_id) VALUES (%s)
                       ON CONFLICT (proveedor_id) DO UPDATE
                         SET actualizado_en = now()""",
                    [(p,) for p in provs],
                )
            if lics:
                cur.executemany(
                    """INSERT INTO licitacion (licitacion_id) VALUES (%s)
                       ON CONFLICT (licitacion_id) DO UPDATE
                         SET actualizado_en = now()""",
                    [(l,) for l in lics],
                )
            if participo:
                cur.executemany(
                    """INSERT INTO participo_en (proveedor_id, licitacion_id, props)
                       VALUES (%s, %s, %s)
                       ON CONFLICT (proveedor_id, licitacion_id) DO UPDATE
                         SET props = EXCLUDED.props, actualizado_en = now()""",
                    [(p, l, J(props))
                     for (p, l), props in sorted(participo.items())],
                )
            if coludido:
                cur.executemany(
                    """INSERT INTO coludido_con
                         (proveedor_id, destino_proveedor_id, corrida_id, score, props)
                       VALUES (%s, %s, %s, %s, %s)
                       ON CONFLICT (proveedor_id, destino_proveedor_id, corrida_id)
                       DO UPDATE SET score = EXCLUDED.score, props = EXCLUDED.props""",
                    [(p, q, corrida_id, _score_arista(props, conclusion.score), J(props))
                     for (p, q), props in sorted(coludido.items())],
                )
            if provs:
                cur.executemany(
                    """INSERT INTO proveedor_detectado
                         (proveedor_id, corrida_id, score, evidencia)
                       VALUES (%s, %s, %s, %s)
                       ON CONFLICT (proveedor_id, corrida_id)
                       DO UPDATE SET score = EXCLUDED.score,
                                     evidencia = EXCLUDED.evidencia""",
                    [(p, corrida_id, conclusion.score,
                      J({"resumen": conclusion.resumen})) for p in provs],
                )

    def encolar_revision(self, corrida_id, conclusion):
        with self._pg.connect(self._dsn) as con, con.cursor() as cur:
            cur.execute(
                """INSERT INTO revision_pendiente (corrida_id, conclusion, estado)
                   VALUES (%s, %s, 'PENDIENTE')
                   ON CONFLICT (corrida_id) DO UPDATE
                     SET conclusion = EXCLUDED.conclusion, estado = 'PENDIENTE'""",
                (corrida_id,
                 self._Json(json.loads(conclusion.model_dump_json()))),
            )
