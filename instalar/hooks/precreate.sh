#!/usr/bin/env bash
# Hook precreate del boton "Run on Google Cloud": corre en Cloud Shell con la
# sesion del usuario, ANTES de crear el servicio. Prepara toda la infra.
# El boton expone: GOOGLE_CLOUD_PROJECT, GOOGLE_CLOUD_REGION, APP_DIR.
set -euo pipefail
PROYECTO="$GOOGLE_CLOUD_PROJECT"
REGION="$GOOGLE_CLOUD_REGION"
source "$APP_DIR/instalar/fases.sh"

echo "── [botón] APIs ──";              habilitar_apis
echo "── [botón] identidad ──";         preparar_identidad >/dev/null
echo "── [botón] Spanner + grafo ──";   preparar_spanner "$APP_DIR/sql/spanner_graph.sql"
echo "── [botón] infra lista; el botón construye y crea el servicio ──"
