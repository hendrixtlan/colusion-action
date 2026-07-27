"""Agente raiz ADK — el camino donde EL AGENTE detona la action.

Patron oficial "governed integration": el agente raiz usa el toolset
DataAgentToolset (tool ask_data_agent) para consultar el data agent
pre-configurado de la Conversational Analytics API (fuente Looker), y una
tool custom `escribir_grafo_colusion` que pega al /accion/execute de la
misma action del Action Hub. Asi el usuario puede decir en el chat:

    "dame los pares con >80% de licitaciones compartidas
     y escribe esa conclusión al grafo"

Guardrail (el LLM propone, el codigo dispone): la tool escribe en
modo 'revision' (RevisionPendiente) salvo que el usuario pida explicitamente
escribir directo; la conversion filas->aristas sigue siendo la de la action,
determinista e idempotente. El agente nunca tiene credenciales de la base.

Correr local:  cd chat && adk web   (ADK descubre agente/ → root_agent)
Variables: GOOGLE_CLOUD_PROJECT, CA_LOCATION, DATA_AGENT_ID,
           ACTION_URL, ACTION_HUB_TOKEN, MODELO (default gemini-2.5-flash)

Nota: los agentes creados DENTRO de Looker no son visibles fuera de Looker;
para este camino el data agent se define como recurso de la CA API con las
mismas instrucciones y golden queries (fuente: los mismos Explores).
"""
from __future__ import annotations

import json
import os
import sys

from google.adk.agents import Agent
from google.adk.tools.data_agent import DataAgentToolset

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from comun import detonar_action, id_recurso_agente

_AGENTE_DATOS = id_recurso_agente(
    os.environ.get("GOOGLE_CLOUD_PROJECT", ""),
    os.environ.get("CA_LOCATION", "global"),
    os.environ.get("DATA_AGENT_ID", ""),
)


def escribir_grafo_colusion(filas_json: str, notas: str = "",
                            modo: str = "revision",
                            score: float = 0.5) -> dict:
    """Escribe una conclusion de colusion al grafo via la action de Looker.

    Args:
        filas_json: JSON con la lista de filas tal como las devolvio
            ask_data_agent. Cada fila debe traer proveedor_a y proveedor_b
            (y opcionalmente licitacion_id, score), o bien proveedor y
            licitacion_id.
        notas: conclusion del analista en una o dos frases.
        modo: 'revision' (default, encola a revision humana) o 'auto'
            (directo al grafo). Usa 'auto' SOLO si el usuario pidio
            explicitamente escribir directo sin revision.
        score: severidad 0 a 1 si las filas no traen columna score.

    Returns:
        dict con success y message de la action.
    """
    try:
        filas = json.loads(filas_json)
        if isinstance(filas, dict):
            filas = filas.get("data") or filas.get("filas") or []
    except json.JSONDecodeError:
        return {"success": False, "message": "filas_json no es JSON válido"}
    return detonar_action(os.environ["ACTION_URL"],
                          os.environ.get("ACTION_HUB_TOKEN", ""),
                          filas, modo=modo, score=score, notas=notas)


root_agent = Agent(
    name="colusion_raiz",
    model=os.environ.get("MODELO", "gemini-2.5-flash"),
    description="Analista antimonopolio: consulta Looker y persiste "
                "conclusiones de colusión al grafo.",
    instruction=f"""Eres un analista antimonopolio.

Para preguntas de datos usa la tool ask_data_agent con el data agent
'{_AGENTE_DATOS}'. Señales de colusión: proveedores que comparten alta
proporción de licitaciones, alternancia de ganador (rotación de posturas),
diferencias de postura constantes, retiros sistemáticos. Pide siempre que
los resultados incluyan proveedor_a, proveedor_b, licitacion_id y un score
entre 0 y 1.

Cuando el usuario pida guardar, registrar o escribir una conclusión al
grafo, llama escribir_grafo_colusion pasando en filas_json exactamente las
filas del último resultado (sin inventar ni completar valores). Usa
modo='revision' por defecto; modo='auto' solo si el usuario dijo
explícitamente que se escriba directo sin revisión humana. Nunca escribas
al grafo sin que el usuario lo haya pedido en este turno o el anterior.""",
    tools=[DataAgentToolset(), escribir_grafo_colusion],
)
