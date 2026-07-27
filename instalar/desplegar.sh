#!/usr/bin/env bash
# Despliegue end to end por CLI (misma logica que el boton: fases.sh).
#
#   export PROYECTO=mi-proyecto REGION=us-central1 BACKEND=spanner
#   ./instalar/desplegar.sh
#
# BACKEND=alloydb crea cluster+instancia (requiere red con Private Services
# Access) y espera ALLOYDB_DSN exportado antes del deploy.
# Idempotente: reejecutar retoma donde quedo.
set -euo pipefail
FASE="preflight"
trap 'echo "✖ Falló en: ${FASE}. Corrige la causa y reejecuta: el script es idempotente." >&2' ERR

PROYECTO="${PROYECTO:?exporta PROYECTO=tu-proyecto-gcp}"
REGION="${REGION:-us-central1}"
BACKEND="${BACKEND:-spanner}"
SERVICIO="colusion-action"
AQUI="$(cd "$(dirname "$0")" && pwd)"
source "${AQUI}/fases.sh"

# ── Preflight: fallar aqui es barato; fallar a la mitad es caro ──
command -v gcloud >/dev/null  || { echo "falta gcloud (instala Cloud SDK)"; exit 1; }
command -v openssl >/dev/null || { echo "falta openssl"; exit 1; }
command -v python3 >/dev/null || { echo "falta python3"; exit 1; }
CUENTA="$(gcloud auth list --filter=status:ACTIVE --format='value(account)')"
[ -n "$CUENTA" ] || { echo "no hay sesión activa: gcloud auth login"; exit 1; }
gcloud projects describe "$PROYECTO" >/dev/null \
  || { echo "el proyecto $PROYECTO no existe o $CUENTA no tiene acceso"; exit 1; }
echo "Preflight OK: $CUENTA → $PROYECTO ($REGION, backend=$BACKEND)"
gcloud config set project "$PROYECTO" >/dev/null

FASE="Fase 1: APIs"; echo "── ${FASE} ──"
habilitar_apis
[ "$BACKEND" = "alloydb" ] && gcloud services enable alloydb.googleapis.com

FASE="Fase 2: identidad y token"; echo "── ${FASE} ──"
SA_EMAIL="$(preparar_identidad)"
TOKEN="$(asegurar_secreto)"
gcloud secrets add-iam-policy-binding action-hub-token \
  --member="serviceAccount:${SA_EMAIL}" --role=roles/secretmanager.secretAccessor >/dev/null

FASE="Fase 3: base de datos (${BACKEND})"; echo "── ${FASE} ──"
ENV_BD=""
if [ "$BACKEND" = "spanner" ]; then
  preparar_spanner "${AQUI}/../sql/spanner_graph.sql"
  ENV_BD="SPANNER_INSTANCE=${INSTANCIA_SPANNER:-colusion-graph},SPANNER_DATABASE=${BD_SPANNER:-colusion}"
else
  echo "  Prerrequisito AlloyDB: la red debe tener Private Services Access."
  gcloud alloydb clusters describe colusion --region="$REGION" >/dev/null 2>&1 \
    || gcloud alloydb clusters create colusion --region="$REGION" \
         --password="${ALLOYDB_PASSWORD:?exporta ALLOYDB_PASSWORD}" \
         --network="${RED:-default}"
  gcloud alloydb instances describe colusion-primaria --cluster=colusion \
    --region="$REGION" >/dev/null 2>&1 \
    || gcloud alloydb instances create colusion-primaria --cluster=colusion \
         --region="$REGION" --instance-type=PRIMARY --cpu-count=2
  echo "  Ahora: psql \"\$ALLOYDB_DSN\" -f ${AQUI}/../sql/alloydb.sql"
  : "${ALLOYDB_DSN:?exporta ALLOYDB_DSN y reejecuta}"
  ENV_BD="ALLOYDB_DSN=${ALLOYDB_DSN}"
fi

FASE="Fase 4: Cloud Run"; echo "── ${FASE} ──"
FLAGS_RED=()
[ "$BACKEND" = "alloydb" ] && FLAGS_RED=(--network="${RED:-default}" \
  --subnet="${SUBRED:-default}" --vpc-egress=private-ranges-only)
gcloud run deploy "$SERVICIO" --source "${AQUI}/../app" --region "$REGION" \
  --allow-unauthenticated --service-account "$SA_EMAIL" \
  --set-secrets ACTION_HUB_TOKEN=action-hub-token:latest \
  --set-env-vars "GRAFO_BACKEND=${BACKEND},GOOGLE_CLOUD_PROJECT=${PROYECTO},${ENV_BD}" \
  "${FLAGS_RED[@]}"

FASE="Fase 5: URL y verificación"; echo "── ${FASE} ──"
URL="$(ligar_url_y_verificar "$SERVICIO")"
resumen_registro "$URL" "$TOKEN"
