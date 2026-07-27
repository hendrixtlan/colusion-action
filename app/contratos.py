"""Contratos de datos de la action: la ontologia operativa de colusion.

Mismo principio que fleet-agent/contratos.py: todo lo que se persiste al grafo
esta tipado aqui. La diferencia es quien lo produce: en fleet-agent lo proponia
un LLM (patronador con output_schema); aqui lo construye codigo determinista a
partir de las filas que Looker entrega a la action. El agente conversacional
solo arma la consulta; nunca toca la base.
"""
from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class TipoNodo(str, Enum):
    PROVEEDOR = "Proveedor"
    LICITACION = "Licitacion"


class TipoArista(str, Enum):
    COLUDIDO_CON = "COLUDIDO_CON"    # Proveedor -> Proveedor  props: senales, montos...
    PARTICIPO_EN = "PARTICIPO_EN"    # Proveedor -> Licitacion props: monto, postura...


class Implicado(BaseModel):
    tipo: TipoNodo
    id: str
    props: dict = Field(default_factory=dict)


class Arista(BaseModel):
    origen: str
    destino: str
    tipo: TipoArista
    props: dict = Field(default_factory=dict)


class ConclusionColusion(BaseModel):
    """Lo unico que el repositorio acepta escribir. Ver repositorio.py."""

    nodos: list[Implicado] = Field(default_factory=list)
    aristas: list[Arista] = Field(default_factory=list)
    score: float = Field(default=0.5, ge=0.0, le=1.0,
                         description="Severidad global de la conclusion")
    resumen: str = ""                 # notas del analista (form de la action)
