"""Action Hub minimo para Looker: escribe conclusiones de colusion a un grafo.

Endpoints del Action API de Looker (POST):
  /                 lista de actions; esta URL raiz se registra en Admin
  /accion/form      formulario del dialogo Send/Schedule
  /accion/execute   filas de la consulta -> grafo (Spanner o AlloyDB)
  /accion/celda     action de celda LookML (marcar una colusion puntual)
Y de operacion (GET):
  /                 vivo (liveness)
  /listo            listo (readiness: verifica la base)

Garantias "a prueba de balas":
  * Idempotencia real ante reintentos: corrida_id = hash del contenido del
    payload. Looker reintenta webhooks fallidos; el mismo payload produce la
    misma corrida y el grafo converge en vez de duplicarse.
  * Politica de errores: payload invalido -> 200 {success:false} (reintentar
    no ayuda); error de base -> 503 (Looker SI debe reintentar; es seguro
    por la idempotencia).
  * Limites: MAX_BYTES por peticion y MAX_FILAS procesadas (con aviso).
  * Token comparado en tiempo constante (hmac.compare_digest).
  * Logs estructurados JSON (Cloud Logging los indexa por campo).

El principio se mantiene: el LLM propone, el codigo dispone.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import json
import logging
import os
import re

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse

from contratos import Arista, ConclusionColusion, Implicado, TipoArista, TipoNodo
from repositorio import GrafoRepositorio, construir_repositorio

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("colusion")

app = FastAPI(title="Action: escribir grafo de colusion")

# ── Configuracion ──
URL_BASE = os.environ.get("URL_BASE", "").rstrip("/")
TOKEN = os.environ.get("ACTION_HUB_TOKEN", "")
MAX_BYTES = int(os.environ.get("MAX_BYTES", 20 * 1024 * 1024))   # 20 MB
MAX_FILAS = int(os.environ.get("MAX_FILAS", 2000))

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


def _bitacora(nivel: str, evento: str, **campos) -> None:
    registro = {"severity": nivel, "evento": evento, **campos,
                "ts": dt.datetime.now(dt.timezone.utc).isoformat()}
    log.info(json.dumps(registro, ensure_ascii=False, default=str))


def _autorizar(authorization: str | None) -> None:
    """Token del Action Hub en tiempo constante. Sin token = solo dev local."""
    if not TOKEN:
        return
    recibido = ""
    if authorization:
        m = re.search(r'token="?([^"]+)"?', authorization)
        recibido = m.group(1) if m else authorization.removeprefix("Bearer ").strip()
    if not hmac.compare_digest(recibido.encode(), TOKEN.encode()):
        raise HTTPException(status_code=401, detail="token invalido")


@app.exception_handler(Exception)
async def _errores_no_previstos(request: Request, exc: Exception):
    """Nunca filtrar stack traces a Looker; log completo, mensaje limpio."""
    _bitacora("ERROR", "excepcion_no_prevista", ruta=str(request.url.path),
              tipo=type(exc).__name__, detalle=str(exc)[:400])
    return JSONResponse(status_code=500, content=_respuesta(
        False, "Error interno del servicio; revisa los logs en Cloud Run."))


# ── Operacion ──

@app.get("/")
async def vivo():
    return {"ok": True}


@app.get("/listo")
async def listo():
    """Readiness: verifica conectividad real con el backend del grafo."""
    try:
        _repositorio().verificar()
        return {"listo": True, "backend": os.environ.get("GRAFO_BACKEND", "spanner")}
    except Exception as exc:
        _bitacora("ERROR", "no_listo", detalle=str(exc)[:300])
        raise HTTPException(status_code=503, detail="base de datos inaccesible")


# ── 1. Lista de actions ──

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


# ── 2. Formulario ──

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

    declarado = int(request.headers.get("content-length") or 0)
    if declarado > MAX_BYTES:
        return _respuesta(False, f"Payload de {declarado} bytes excede el "
                                 f"límite ({MAX_BYTES}). Limita la consulta "
                                 f"o baja el número de filas.")
    try:
        cuerpo = await request.json()
    except Exception:
        return _respuesta(False, "El cuerpo no es JSON válido.")

    form = cuerpo.get("form_params") or {}
    filas, total = _filas_de_payload(cuerpo)
    if not filas:
        return _respuesta(False, "El resultado no trae filas; nada que escribir.")
    truncadas = total > len(filas)

    conclusion = _conclusion_desde_filas(filas, form)
    if not conclusion.aristas:
        return _respuesta(
            False,
            "No encontré columnas mapeables (se esperan "
            f"'{CAMPO_PROVEEDOR_A}'/'{CAMPO_PROVEEDOR_B}' o "
            f"'{CAMPO_PROVEEDOR}'+'{CAMPO_LICITACION}').",
        )

    corrida_id = _corrida_id(cuerpo)
    plan = cuerpo.get("scheduled_plan") or {}
    proveniencia = {"titulo": plan.get("title"), "url": plan.get("url"),
                    "query": plan.get("query"), "tipo": cuerpo.get("type")}

    try:
        if form.get("modo") == "revision":
            _repositorio().encolar_revision(corrida_id, conclusion)
            mensaje = f"{corrida_id}: encolada a revisión humana (RevisionPendiente)."
        else:
            _repositorio().persistir(corrida_id, conclusion,
                                     consulta_looker=proveniencia)
            mensaje = (f"{corrida_id}: {len(conclusion.nodos)} nodos y "
                       f"{len(conclusion.aristas)} aristas escritas al grafo "
                       f"(score {conclusion.score:.2f}).")
        if truncadas:
            mensaje += (f" Aviso: se procesaron {len(filas)} de {total} filas "
                        f"(MAX_FILAS={MAX_FILAS}).")
    except Exception as exc:
        # Error de base: 503 para que Looker reintente. Es seguro: la misma
        # corrida_id hace que el reintento converja, no que duplique.
        _bitacora("ERROR", "persistencia_fallida", corrida=corrida_id,
                  tipo=type(exc).__name__, detalle=str(exc)[:400])
        raise HTTPException(status_code=503,
                            detail=f"error temporal escribiendo {corrida_id}; "
                                   f"Looker reintentará")

    _bitacora("INFO", "corrida_procesada", corrida=corrida_id,
              nodos=len(conclusion.nodos), aristas=len(conclusion.aristas),
              filas=len(filas), truncadas=truncadas,
              modo=form.get("modo", "auto"))
    return _respuesta(True, mensaje)


# ── 4. Action de celda (LookML `action:`) ──

@app.post("/accion/celda")
async def celda(request: Request,
                authorization: str | None = Header(default=None)):
    _autorizar(authorization)
    try:
        cuerpo = await request.json()
    except Exception:
        return _respuesta(False, "El cuerpo no es JSON válido.")
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
        score=_a_float(datos.get("score"), 0.5),
        resumen=str(datos.get("notas") or ""),
    )
    # Doble clic o reintento del mismo marcado = misma corrida (idempotente).
    corrida_id = _corrida_id({"celda": {"origen": origen, "destino": destino,
                                        "notas": conclusion.resumen}})
    try:
        _repositorio().persistir(corrida_id, conclusion,
                                 consulta_looker={"tipo": "cell"})
    except Exception as exc:
        _bitacora("ERROR", "persistencia_fallida", corrida=corrida_id,
                  tipo=type(exc).__name__, detalle=str(exc)[:400])
        raise HTTPException(status_code=503, detail="error temporal; reintenta")
    return _respuesta(True, f"{corrida_id}: arista {origen} -[COLUDIDO_CON]-> "
                            f"{destino} escrita.")


# ── Helpers deterministas ──

def _respuesta(exito: bool, mensaje: str) -> dict:
    return {"looker": {"success": exito, "message": mensaje}}


def _corrida_id(cuerpo: dict) -> str:
    """Hash del contenido: mismo payload -> misma corrida.

    Esto vuelve inocuos los reintentos de Looker y los dobles disparos de un
    schedule: el grafo converge. Efecto colateral deliberado: mandar la
    conclusion IDENTICA dos veces deduplica a una sola corrida; para forzar
    una corrida nueva basta cambiar las notas del form.
    """
    plan = cuerpo.get("scheduled_plan") or {}
    base = json.dumps({
        "plan": plan.get("scheduled_plan_id") or plan.get("query_id") or "",
        "adjunto": (cuerpo.get("attachment") or {}).get("data") or "",
        "form": cuerpo.get("form_params") or {},
        "celda": cuerpo.get("celda") or {},
    }, sort_keys=True, ensure_ascii=False, default=str)
    return "looker-" + hashlib.sha256(base.encode()).hexdigest()[:16]


def _a_float(valor, defecto: float) -> float:
    """Coercion tolerante: 0.85, '0.85', '85%', None, celdas raras."""
    if isinstance(valor, bool) or valor is None:
        return defecto
    if isinstance(valor, (int, float)):
        return float(valor)
    try:
        texto = str(valor).strip().replace("%", "")
        numero = float(texto)
        return numero / 100.0 if "%" in str(valor) else numero
    except (TypeError, ValueError):
        return defecto


def _valor_celda(v):
    """json_detail manda celdas como {'value': x, 'rendered': '...'}."""
    if isinstance(v, dict):
        return v.get("value", v.get("rendered"))
    return v


def _filas_de_payload(cuerpo: dict) -> tuple[list[dict], int]:
    """Regresa (filas_normalizadas_hasta_MAX_FILAS, total_original)."""
    crudo = (cuerpo.get("attachment") or {}).get("data")
    if not crudo:
        return [], 0
    try:
        parseado = json.loads(crudo) if isinstance(crudo, str) else crudo
    except json.JSONDecodeError:
        return [], 0
    filas = parseado.get("data", []) if isinstance(parseado, dict) else parseado
    filas = [f for f in (filas or []) if isinstance(f, dict)]
    total = len(filas)

    limpias: list[dict] = []
    for fila in filas[:MAX_FILAS]:
        limpias.append({llave.rsplit(".", 1)[-1]: _valor_celda(valor)
                        for llave, valor in fila.items()})
    return limpias, total


def _conclusion_desde_filas(filas: list[dict], form: dict) -> ConclusionColusion:
    """Conversion determinista filas -> conclusion (pares o bipartita)."""
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

        if CAMPO_SCORE in fila and fila.get(CAMPO_SCORE) is not None:
            scores.append(_a_float(fila.get(CAMPO_SCORE), 0.5))

    score = (sum(scores) / len(scores)) if scores \
        else _a_float(form.get("score"), 0.5)

    return ConclusionColusion(
        nodos=[Implicado(tipo=t, id=i) for (t, i) in sorted(nodos)],
        aristas=aristas,
        score=min(max(score, 0.0), 1.0),
        resumen=str(form.get("notas") or ""),
    )
