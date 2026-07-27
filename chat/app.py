"""Chat propio del data agent (Conversational Analytics API, fuente Looker)
con el boton "Escribir conclusion al grafo" — el camino donde el HUMANO detona.

Por que existe: el chat nativo de Conversational Analytics dentro de Looker
hoy no puede invocar actions custom del Action Hub. Este front minimo habla
con el MISMO tipo de agente (data agent con Explores de Looker, instrucciones
y golden queries) via la CA API, conserva las ultimas filas que el agente
devolvio, y el boton las manda al /accion/execute de la action — identico
payload, token y auditoria que el camino Explore -> Send.

Variables de entorno:
  GOOGLE_CLOUD_PROJECT   proyecto GCP
  CA_LOCATION            'global' (default)
  DATA_AGENT_ID          id corto o nombre completo del data agent
  LOOKER_CLIENT_ID/SECRET  credenciales API de Looker (fuente del agente)
  ACTION_URL             https://colusion-action-XXXX.run.app
  ACTION_HUB_TOKEN       el mismo token registrado en el Action Hub

Correr:  streamlit run app.py   (o en Cloud Run con el Dockerfile de app/
adaptado: CMD streamlit run chat/app.py --server.port $PORT)
"""
from __future__ import annotations

import os

import streamlit as st
from google.cloud import geminidataanalytics as gda

from comun import detonar_action, extraer, id_recurso_agente

PROYECTO = os.environ["GOOGLE_CLOUD_PROJECT"]
UBICACION = os.environ.get("CA_LOCATION", "global")
AGENTE = id_recurso_agente(PROYECTO, UBICACION, os.environ["DATA_AGENT_ID"])
ACTION_URL = os.environ["ACTION_URL"]
ACTION_TOKEN = os.environ.get("ACTION_HUB_TOKEN", "")

st.set_page_config(page_title="Agente de colusión", page_icon="🕸️")
st.title("Agente de colusión")
st.caption("Conversational Analytics (fuente Looker) + action → GrafoColusion")

if "historial" not in st.session_state:
    st.session_state.historial = []     # lista de gda.Message (multi-turno)
    st.session_state.transcript = []    # [(rol, texto)] para pintar
    st.session_state.ultimas_filas = [] # ultimo resultado tabular del agente


@st.cache_resource
def _cliente() -> gda.DataChatServiceClient:
    return gda.DataChatServiceClient()


def _credenciales_looker() -> gda.Credentials:
    return gda.Credentials(oauth=gda.OAuthCredentials(
        secret=gda.OAuthCredentials.SecretBased(
            client_id=os.environ["LOOKER_CLIENT_ID"],
            client_secret=os.environ["LOOKER_CLIENT_SECRET"],
        )))


def preguntar(texto: str) -> None:
    """Chat sin estado gestionado: mandamos todo el historial en cada turno."""
    st.session_state.historial.append(
        gda.Message(user_message=gda.UserMessage(text=texto)))
    st.session_state.transcript.append(("user", texto))

    peticion = gda.ChatRequest(
        parent=f"projects/{PROYECTO}/locations/{UBICACION}",
        messages=st.session_state.historial,
        data_agent_context=gda.DataAgentContext(data_agent=AGENTE),
        credentials=_credenciales_looker(),  # fuente Looker del agente
    )
    respuesta_texto, filas_turno = [], []
    for mensaje in _cliente().chat(request=peticion):
        st.session_state.historial.append(mensaje)
        texto_m, filas_m = extraer(mensaje)
        if texto_m:
            respuesta_texto.append(texto_m)
        if filas_m:
            filas_turno = filas_m

    if filas_turno:
        st.session_state.ultimas_filas = filas_turno
    st.session_state.transcript.append(
        ("assistant", "\n\n".join(respuesta_texto) or "(sin texto)"))


# ── UI ──

for rol, texto in st.session_state.transcript:
    with st.chat_message(rol):
        st.markdown(texto)

if st.session_state.ultimas_filas:
    with st.expander(f"Último resultado ({len(st.session_state.ultimas_filas)} filas)"):
        st.dataframe(st.session_state.ultimas_filas)

with st.sidebar:
    st.subheader("Escribir al grafo")
    st.caption("Manda el último resultado tabular a la action registrada "
               "en el Action Hub (misma auditoría: nodo Corrida).")
    modo = st.radio("Modo", ["revision", "auto"], horizontal=True,
                    help="revision → RevisionPendiente; auto → directo al grafo")
    score = st.slider("Score si el resultado no trae columna score",
                      0.0, 1.0, 0.5, 0.05)
    notas = st.text_area("Conclusión del analista")
    if st.button("🕸️ Escribir conclusión al grafo",
                 disabled=not st.session_state.ultimas_filas,
                 use_container_width=True):
        r = detonar_action(ACTION_URL, ACTION_TOKEN,
                           st.session_state.ultimas_filas, modo, score, notas)
        (st.success if r.get("success") else st.error)(r.get("message", ""))

if pregunta := st.chat_input("Pregunta sobre licitaciones y proveedores…"):
    preguntar(pregunta)
    st.rerun()
