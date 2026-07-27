#!/usr/bin/env python3
"""Crea (o actualiza informando) el data agent de la Conversational Analytics
API con fuente Looker — la pieza que usan chat/app.py y chat/raiz_adk.py.

Variables de entorno:
  PROYECTO           proyecto GCP (o GOOGLE_CLOUD_PROJECT)
  CA_LOCATION        'global' (default)
  DATA_AGENT_ID      id corto, p.ej. 'colusion'
  LOOKER_BASE_URL    https://tuempresa.cloud.looker.com
  EXPLORES           pares modelo:explore separados por coma,
                     p.ej. 'compras:licitaciones,compras:posturas'
  INSTRUCCIONES_MD   (opcional) ruta a un .md con las instrucciones

Autenticacion: ADC (gcloud auth application-default login) con permiso
en la Conversational Analytics API. Las credenciales de Looker NO van aqui:
se mandan en cada chat (asi cada llamada respeta permisos de Looker).
"""
from __future__ import annotations

import os
import sys

from google.api_core import exceptions
from google.cloud import geminidataanalytics as g

INSTRUCCIONES_DEFAULT = """Eres un analista antimonopolio.
Señales de colusión que debes buscar: proveedores que comparten alta
proporción de licitaciones, alternancia de ganador (rotación de posturas),
diferencias de postura constantes, retiros sistemáticos.
Cuando propongas pares sospechosos incluye siempre las columnas
proveedor_a, proveedor_b, licitacion_id y un score entre 0 y 1: ese es el
formato que la action "Escribir conclusión al grafo de colusión" convierte
en aristas del grafo."""


def construir_agente() -> tuple[str, str, g.DataAgent]:
    proyecto = os.environ.get("PROYECTO") or os.environ["GOOGLE_CLOUD_PROJECT"]
    ubicacion = os.environ.get("CA_LOCATION", "global")
    base_url = os.environ["LOOKER_BASE_URL"].rstrip("/")

    referencias = []
    for par in os.environ["EXPLORES"].split(","):
        modelo, explore = par.strip().split(":", 1)
        referencias.append(g.LookerExploreReference(
            looker_instance_uri=base_url, lookml_model=modelo, explore=explore))

    ruta_md = os.environ.get("INSTRUCCIONES_MD", "")
    instrucciones = (open(ruta_md, encoding="utf-8").read()
                     if ruta_md else INSTRUCCIONES_DEFAULT)

    contexto = g.Context(
        system_instruction=instrucciones,
        datasource_references=g.DatasourceReferences(
            looker=g.LookerExploreReferences(explore_references=referencias)),
    )
    agente = g.DataAgent(
        display_name="Agente de colusión",
        description="Analista antimonopolio sobre Explores de Looker",
        data_analytics_agent=g.DataAnalyticsAgent(published_context=contexto),
    )
    return proyecto, ubicacion, agente


def main() -> int:
    proyecto, ubicacion, agente = construir_agente()
    agente_id = os.environ.get("DATA_AGENT_ID", "colusion")
    cliente = g.DataAgentServiceClient()
    peticion = g.CreateDataAgentRequest(
        parent=f"projects/{proyecto}/locations/{ubicacion}",
        data_agent_id=agente_id,
        data_agent=agente,
    )
    try:
        operacion = cliente.create_data_agent(request=peticion)
        resultado = operacion.result() if hasattr(operacion, "result") else operacion
        nombre = getattr(resultado, "name", "") or \
            f"projects/{proyecto}/locations/{ubicacion}/dataAgents/{agente_id}"
    except exceptions.AlreadyExists:
        nombre = f"projects/{proyecto}/locations/{ubicacion}/dataAgents/{agente_id}"
        print(f"El agente ya existía; se reutiliza: {nombre}")
    print("\nDATA_AGENT_ID para el chat:\n  export DATA_AGENT_ID=" + nombre)
    return 0


if __name__ == "__main__":
    sys.exit(main())
