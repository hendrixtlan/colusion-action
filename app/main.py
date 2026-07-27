"""Action Hub minimo para Looker: escribe conclusiones de colusion a un grafo.

Implementa el Action API de Looker (tres endpoints POST):

  /                 lista de actions ("integrations"); esta URL raiz es la que
                    se registra en Admin > Actions > Add Action Hub
  /accion/form      formulario que ve el usuario en el dialogo Send/Schedule
  /accion/execute   recibe las filas de la consulta (json_detail o json) y las
                    vacia al grafo via repositorio (Spanner Graph o AlloyDB)

  /accion/celda     extra: destino para actions a nivel de celda definidas en
                    LookML (parametro `action:` en una dimension), para marcar
                    una colusion puntual desde cualquier tabla o dashboard.

Principio heredado de fleet-agent: el LLM propone, el codigo dispone. El agente
de Conversational Analytics solo arma la consulta gobernada; la conversion de
filas a nodos/aristas y toda escritura al grafo es determinista e idempotente.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import os
import re
import uuid

from fastapi import FastAPI, Header, HTTPException, Request

from contratos import Arista, ConclusionColusion, Implicado, TipoArista, TipoNodo
from repositorio import GrafoRepositorio, construir_repositorio

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("colusion")

app = FastAPI(title="Action: escribir grafo de colusion")

# ── Configuracion ──
URL_BASE = os.environ.get("URL_BASE", "").rstrip("/")   # https://...run.app
TOKEN = os.environ.get("ACTION_HUB_TOKEN", "")           # mismo token en Looker

# Mapeo de columnas del Explore -> ontologia (se comparan por sufijo tras el
# ultimo punto: "licitaciones.proveedor_a" == "proveedor_a").
CAMPO_PROVEEDOR_A = os.environ.get("CAMPO_PROVEEDOR_A", "proveedor_a")
CAMPO_PROVEEDOR_B = os.environ.get("CAMPO_PROVEEDOR_B", "proveedor_b")
CAMPO_PROVEEDOR = os.environ.get("CAMPO_PROVEEDOR", "proveedor")
CAMPO_LICITACION = os.environ.get("CAMPO_LICITACION", "licitacion_id")
CAMPO_SCORE = os.environ.get("CAMPO_SCORE", "score")

_repo: GrafoRepositorio | None = None


def _repositorio() -> GrafoRepositorio:
    global _repo
    if _repo is None:
        _repo = construir_repositorio()
    return _repo


def _autorizar(authorization: str | None) -> None:
    """Valida el token que Looker manda en el header Authorization.

    Looker lo envia como `Token token="..."`. Sin ACTION_HUB_TOKEN configurado
    no se valida (solo para desarrollo local; nunca en produccion).
    """
    if not TOKEN:
        return
    recibido = ""
    if authorization:
        m = re.search(r'token="?([^"]+)"?', authorization)
        recibido = m.group(1) if m else authorization.removeprefix("Bearer ").strip()
    if recibido != TOKEN:
        raise HTTPException(status_code=401, detail="token invalido")


# ── 1. Lista de actions ──

@app.get("/")
async def salud():
    return {"ok": True}


@app.post("/")
async def listar(authorization: str | None = Header(default=None)):
    _autorizar(authorization)
    return {
        "integrations": [
            {
                "name": "escribir_grafo_colusion",
                "label": "Escribir conclusión al grafo de colusión",
                "description": (
                    "Convierte las filas del resultado en nodos y aristas "
                    "(Proveedor, Licitación, COLUDIDO_CON / PARTICIPO_EN) con "
                    "proveniencia de la corrida, y las escribe al grafo."
                ),
                "url": f"{URL_BASE}/accion/execute",
                "form_url": f"{URL_BASE}/accion/form",
                "supported_action_types": ["query"],
                "supported_formats": ["json_detail", "json"],
                "supported_formattings": ["unformatted"],
                "supported_visualization_formattings": ["noapply"],
                "supported_download_settings": ["push"],
                "params": [],
            }
        ]
    }


# ── 2. Formulario (dialogo Send / Schedule) ──

@app.post("/accion/form")
async def formulario(authorization: str | None = Header(default=None)):
    _autorizar(authorization)
    return [
        {
            "name": "modo",
            "label": "Modo de escritura",
            "type": "select",
            "required": True,
            "default": "auto",
            "options": [
                {"name": "auto", "label": "Escribir directo al grafo"},
                {"name": "revision", "label": "Encolar a revisión humana"},
            ],
        },
        {
            "name": "score",
            "label": "Score de colusión (0 a 1) si el resultado no trae columna score",
            "type": "text",
            "default": "0.5",
        },
        {
            "name": "notas",
            "label": "Conclusión del analista (queda como evidencia de la corrida)",
            "type": "textarea",
        },
    ]


# ── 3. Ejecucion: filas -> conclusion -> grafo ──

@app.post("/accion/execute")
async def ejecutar(request: Request,
                   authorization: str | None = Header(default=None)):
    _autorizar(authorization)
    cuerpo = await request.json()
    form = cuerpo.get("form_params") or {}
    filas = _filas_de_payload(cuerpo)
    if not filas:
        return _respuesta(False, "El resultado no trae filas; nada que escribir.")

    conclusion = _conclusion_desde_filas(filas, form)
    if not conclusion.aristas:
        return _respuesta(
            False,
            "No encontré columnas mapeables (se esperan "
            f"'{CAMPO_PROVEEDOR_A}'/'{CAMPO_PROVEEDOR_B}' o "
            f"'{CAMPO_PROVEEDOR}'+'{CAMPO_LICITACION}').",
        )

    corrida_id = _corrida_id()
    plan = cuerpo.get("scheduled_plan") or {}
    proveniencia = {"titulo": plan.get("title"), "url": plan.get("url"),
                    "query": plan.get("query"), "tipo": cuerpo.get("type")}

    try:
        if form.get("modo") == "revision":
            _repositorio().encolar_revision(corrida_id, conclusion)
            mensaje = f"{corrida_id}: encolada a revisión humana (RevisionPendiente)."
        else:
            _repositorio().persistir(corrida_id, conclusion,
                                     consulta_looker=proveniencia,
                                     usuario=str(form.get("usuario", "")))
            mensaje = (f"{corrida_id}: {len(conclusion.nodos)} nodos y "
                       f"{len(conclusion.aristas)} aristas escritas al grafo "
                       f"(score {conclusion.score:.2f}).")
    except Exception:
        log.exception("fallo al persistir %s", corrida_id)
        return _respuesta(False, "Error al escribir al grafo; revisa los logs "
                                 "del servicio en Cloud Run.")

    log.info(mensaje)
    return _respuesta(True, mensaje)


# ── 4. Action de celda (LookML `action:` sobre una dimension) ──

@app.post("/accion/celda")
async def celda(request: Request,
                authorization: str | None = Header(default=None)):
    """Marca una colusion puntual: proveedor de la celda -> 'coludido_con'.

    El payload de las actions LookML difiere del Action API, asi que se leen
    valor y parametros de forma tolerante (data / form_params).
    """
    _autorizar(authorization)
    cuerpo = await request.json()
    datos = {**(cuerpo.get("data") or {}), **(cuerpo.get("form_params") or {})}
    origen = str(datos.get("value") or datos.get(CAMPO_PROVEEDOR) or "").strip()
    destino = str(datos.get("coludido_con") or "").strip()
    if not origen or not destino:
        return _respuesta(False, "Faltan proveedor origen o 'coludido_con'.")

    conclusion = ConclusionColusion(
        nodos=[Implicado(tipo=TipoNodo.PROVEEDOR, id=origen),
               Implicado(tipo=TipoNodo.PROVEEDOR, id=destino)],
        aristas=[Arista(origen=origen, destino=destino,
                        tipo=TipoArista.COLUDIDO_CON,
                        props={"fuente": "lookml_cell"})],
        score=float(datos.get("score") or 0.5),
        resumen=str(datos.get("notas") or ""),
    )
    corrida_id = _corrida_id()
    _repositorio().persistir(corrida_id, conclusion,
                             consulta_looker={"tipo": "cell"})
    return _respuesta(True, f"{corrida_id}: arista {origen} -[COLUDIDO_CON]-> "
                            f"{destino} escrita.")


# ── Helpers deterministas ──

def _respuesta(exito: bool, mensaje: str) -> dict:
    return {"looker": {"success": exito, "message": mensaje}}


def _corrida_id() -> str:
    ahora = dt.datetime.now(dt.timezone.utc)
    return f"looker-{ahora:%Y%m%dT%H%M%SZ}-{uuid.uuid4().hex[:6]}"


def _filas_de_payload(cuerpo: dict) -> list[dict]:
    """Extrae filas del attachment, tolerando json_detail y json planos.

    json_detail: {"fields": {...}, "data": [{"vista.campo": {"value": x}}, ...]}
    json:        [{"vista.campo": x}, ...]
    Las llaves se normalizan al sufijo tras el ultimo punto.
    """
    crudo = (cuerpo.get("attachment") or {}).get("data")
    if not crudo:
        return []
    try:
        parseado = json.loads(crudo) if isinstance(crudo, str) else crudo
    except json.JSONDecodeError:
        return []
    filas = parseado.get("data", []) if isinstance(parseado, dict) else parseado

    limpias: list[dict] = []
    for fila in filas or []:
        if not isinstance(fila, dict):
            continue
        limpias.append({
            llave.rsplit(".", 1)[-1]:
                (valor.get("value") if isinstance(valor, dict) else valor)
            for llave, valor in fila.items()
        })
    return limpias


def _conclusion_desde_filas(filas: list[dict], form: dict) -> ConclusionColusion:
    """Conversion determinista filas -> conclusion. Dos formas aceptadas:

    a) pares:      proveedor_a, proveedor_b [, licitacion_id, score, ...]
                   -> aristas COLUDIDO_CON (+ PARTICIPO_EN si hay licitacion)
    b) bipartita:  proveedor, licitacion_id [, monto, ...]
                   -> aristas PARTICIPO_EN; los anillos se descubren despues
                      con GQL / SQL recursivo sobre el grafo.
    Las columnas restantes de cada fila viajan como props de la arista
    (la evidencia queda pegada a la relacion, no suelta).
    """
    nodos: dict[tuple[TipoNodo, str], None] = {}
    aristas: list[Arista] = []
    scores: list[float] = []

    for fila in filas:
        lic = str(fila.get(CAMPO_LICITACION) or "").strip()
        a = str(fila.get(CAMPO_PROVEEDOR_A) or "").strip()
        b = str(fila.get(CAMPO_PROVEEDOR_B) or "").strip()
        p = str(fila.get(CAMPO_PROVEEDOR) or "").strip()

        if a and b:
            nodos[(TipoNodo.PROVEEDOR, a)] = None
            nodos[(TipoNodo.PROVEEDOR, b)] = None
            props = {k: v for k, v in fila.items()
                     if k not in (CAMPO_PROVEEDOR_A, CAMPO_PROVEEDOR_B)
                     and v is not None}
            aristas.append(Arista(origen=a, destino=b,
                                  tipo=TipoArista.COLUDIDO_CON, props=props))
            if lic:
                nodos[(TipoNodo.LICITACION, lic)] = None
                aristas.append(Arista(origen=a, destino=lic,
                                      tipo=TipoArista.PARTICIPO_EN, props={}))
                aristas.append(Arista(origen=b, destino=lic,
                                      tipo=TipoArista.PARTICIPO_EN, props={}))
        elif p and lic:
            nodos[(TipoNodo.PROVEEDOR, p)] = None
            nodos[(TipoNodo.LICITACION, lic)] = None
            props = {k: v for k, v in fila.items()
                     if k not in (CAMPO_PROVEEDOR, CAMPO_LICITACION)
                     and v is not None}
            aristas.append(Arista(origen=p, destino=lic,
                                  tipo=TipoArista.PARTICIPO_EN, props=props))

        valor_score = fila.get(CAMPO_SCORE)
        if isinstance(valor_score, (int, float)):
            scores.append(float(valor_score))

    if scores:
        score = sum(scores) / len(scores)
    else:
        try:
            score = float(form.get("score", 0.5) or 0.5)
        except (TypeError, ValueError):
            score = 0.5

    return ConclusionColusion(
        nodos=[Implicado(tipo=t, id=i) for (t, i) in sorted(nodos)],
        aristas=aristas,
        score=min(max(score, 0.0), 1.0),
        resumen=str(form.get("notas") or ""),
    )
