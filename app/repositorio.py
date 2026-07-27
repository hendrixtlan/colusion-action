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

    def verificar(self) -> None: ...


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


# ── Resiliencia comun ──

_TRANSITORIOS = {"Aborted", "ServiceUnavailable", "DeadlineExceeded",
                 "InternalServerError", "OperationalError", "InterfaceError",
                 "ConnectionDoesNotExist", "TooManyConnections"}
LOTE = int(os.environ.get("LOTE_ESCRITURA", "500"))


def _con_reintentos(fn, intentos: int = 3):
    """Ejecuta fn() reintentando errores transitorios con backoff exponencial.

    Seguro porque toda escritura es idempotente (insert_or_update /
    ON CONFLICT con corrida_id determinista): reintentar converge.
    """
    import time
    ultimo = None
    for n in range(intentos):
        try:
            return fn()
        except Exception as exc:  # clasificacion por nombre: sin acoplar imports
            ultimo = exc
            if type(exc).__name__ not in _TRANSITORIOS or n == intentos - 1:
                raise
            time.sleep(0.5 * (2 ** n))
    raise ultimo


def _lotes(filas: list, tam: int = None):
    tam = tam or LOTE
    for i in range(0, len(filas), tam):
        yield filas[i:i + tam]


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

    def verificar(self) -> None:
        with self._db.snapshot() as s:
            list(s.execute_sql("SELECT 1"))

    def persistir(self, corrida_id, conclusion, consulta_looker=None, usuario=""):
        _con_reintentos(lambda: self._persistir(
            corrida_id, conclusion, consulta_looker, usuario))

    def _persistir(self, corrida_id, conclusion, consulta_looker, usuario):
        """Escritura por lotes (<= LOTE filas por commit) para no rozar los
        limites de mutaciones por transaccion de Spanner. Cada commit es
        idempotente; si truena a la mitad, el reintento converge."""
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
        tandas = [
            ("Proveedor", ("proveedor_id", "actualizado_en"),
             [(p, ts) for p in provs]),
            ("Licitacion", ("licitacion_id", "actualizado_en"),
             [(l, ts) for l in lics]),
            ("ParticipoEn",
             ("proveedor_id", "licitacion_id", "props", "actualizado_en"),
             [(p, l, sp.JsonObject(props), ts)
              for (p, l), props in sorted(participo.items())]),
            ("ColudidoCon",
             ("proveedor_id", "destino_proveedor_id", "corrida_id",
              "score", "props"),
             [(p, q, corrida_id, _score_arista(props, conclusion.score),
               sp.JsonObject(props))
              for (p, q), props in sorted(coludido.items())]),
            ("ProveedorDetectado",
             ("proveedor_id", "corrida_id", "score", "evidencia"),
             [(p, corrida_id, conclusion.score,
               sp.JsonObject({"resumen": conclusion.resumen}))
              for p in provs]),
        ]
        for tabla, columnas, filas in tandas:
            for lote in _lotes(filas):
                if lote:
                    with self._db.batch() as b:
                        b.insert_or_update(table=tabla, columns=columnas,
                                           values=lote)

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

    def verificar(self) -> None:
        with self._pg.connect(self._dsn) as con, con.cursor() as cur:
            cur.execute("SELECT 1")

    def persistir(self, corrida_id, conclusion, consulta_looker=None, usuario=""):
        _con_reintentos(lambda: self._persistir(
            corrida_id, conclusion, consulta_looker, usuario))

    def _persistir(self, corrida_id, conclusion, consulta_looker, usuario):
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
