"""Logica comun del chat: extraer texto/filas del stream de la CA API y
detonar la action de Looker (el mismo /accion/execute registrado en el
Action Hub, mismo token, misma auditoria Corrida/RevisionPendiente).

Sin dependencias de UI: esto lo usan tanto app.py (boton, humano detona)
como raiz_adk.py (tool, el agente detona).
"""
from __future__ import annotations

import json
import re
import urllib.request


# ── Extraccion del stream de la Conversational Analytics API ──

def a_dict(mensaje) -> dict:
    """Convierte un proto-plus Message a dict plano de Python."""
    try:
        import proto
        return proto.Message.to_dict(mensaje, preserving_proto_field_name=True)
    except Exception:
        return mensaje if isinstance(mensaje, dict) else {}


def extraer(mensaje) -> tuple[str, list[dict]]:
    """De un Message del stream, regresa (texto, filas_de_datos).

    El stream trae system_message con variantes: text (partes de texto),
    data (DataMessage.result.data = filas), chart, error, schema...
    Solo nos interesan texto y filas; lo demas se ignora.
    """
    d = a_dict(mensaje)
    sm = d.get("system_message") or {}
    texto = ""
    filas: list[dict] = []

    if "text" in sm:
        texto = "".join(sm["text"].get("parts") or [])
    if "error" in sm:
        texto = f"[error del agente] {sm['error'].get('text', '')}"
    if "data" in sm:
        resultado = (sm["data"] or {}).get("result") or {}
        filas = [f for f in (resultado.get("data") or []) if isinstance(f, dict)]

    return texto, filas


# ── Detonacion de la action ──

def payload_action(filas: list[dict], modo: str = "revision",
                   score: float | str = 0.5, notas: str = "",
                   titulo: str = "chat conversational analytics") -> dict:
    """Arma el mismo ActionRequest que Looker mandaria desde Send/Schedule.

    Las filas van como attachment json plano ({campo: valor}); la action ya
    sabe mapearlas por sufijo (proveedor_a/proveedor_b o
    proveedor+licitacion_id). modo='revision' por defecto: en el camino
    conversacional el guardrail es encolar a revision humana salvo peticion
    explicita de escribir directo.
    """
    return {
        "type": "query",
        "scheduled_plan": {"title": titulo, "url": "", "query": {}},
        "attachment": {"mimetype": "application/json",
                       "data": json.dumps(filas, ensure_ascii=False, default=str)},
        "form_params": {"modo": "auto" if modo == "auto" else "revision",
                        "score": str(score), "notas": notas},
    }


def detonar_action(url_action: str, token: str, filas: list[dict],
                   modo: str = "revision", score: float | str = 0.5,
                   notas: str = "") -> dict:
    """POST al /accion/execute de la action. Regresa {'success':..,'message':..}."""
    if not filas:
        return {"success": False,
                "message": "No hay filas de datos en la conversación todavía."}
    cuerpo = json.dumps(payload_action(filas, modo, score, notas)).encode()
    peticion = urllib.request.Request(
        url_action.rstrip("/") + "/accion/execute",
        data=cuerpo,
        headers={"Content-Type": "application/json",
                 "Authorization": f'Token token="{token}"'},
        method="POST",
    )
    try:
        with urllib.request.urlopen(peticion, timeout=60) as r:
            respuesta = json.loads(r.read().decode())
    except Exception as exc:  # red, 4xx/5xx, timeouts
        return {"success": False, "message": f"No se pudo llamar la action: {exc}"}
    return respuesta.get("looker", {"success": False,
                                    "message": "respuesta inesperada de la action"})


def id_recurso_agente(proyecto: str, ubicacion: str, agente: str) -> str:
    """Acepta el id corto o el nombre completo del data agent de la CA API."""
    if re.match(r"^projects/.+/locations/.+/dataAgents/.+$", agente):
        return agente
    return f"projects/{proyecto}/locations/{ubicacion}/dataAgents/{agente}"
