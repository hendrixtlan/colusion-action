#!/usr/bin/env bash
# Despliegue end to end de colusion-action.
#
# Uso:
#   export PROYECTO=mi-proyecto REGION=us-central1 BACKEND=spanner
#   ./desplegar.sh
#
# BACKEND=spanner (default) crea instancia+base y despliega todo.
# BACKEND=alloydb crea cluster+instancia (requiere red con Private Services
#   Access ya configurado) y espera ALLOYDB_DSN exportado antes del deploy.
#
# Idempotente a proposito: cada recurso se crea solo si no existe.
set -euo pipefail
FASE="preflight"
trap 'echo "✖ Falló en: ${FASE}. Corrige la causa y reejecuta: el script es idempotente y retoma donde quedó." >&2' ERR

PROYECTO="${PROYECTO:?exporta PROYECTO=tu-proyecto-gcp}"
REGION="${REGION:-us-central1}"
BACKEND="${BACKEND:-spanner}"
SERVICIO="colusion-action"
SA="colusion-action"
SA_EMAIL="${SA}@${PROYECTO}.iam.gserviceaccount.com"
INSTANCIA_SPANNER="${INSTANCIA_SPANNER:-colusion-graph}"
BD_SPANNER="${BD_SPANNER:-colusion}"
AQUI="$(cd "$(dirname "$0")" && pwd)"

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
gcloud services enable run.googleapis.com cloudbuild.googleapis.com \
  artifactregistry.googleapis.com secretmanager.googleapis.com \
  geminidataanalytics.googleapis.com \
  $( [ "$BACKEND" = "spanner" ] && echo spanner.googleapis.com || echo alloydb.googleapis.com )

FASE="Fase 2: service account y token del Action Hub"; echo "── ${FASE} ──"
gcloud iam service-accounts describe "$SA_EMAIL" >/dev/null 2>&1 \
  || gcloud iam service-accounts create "$SA" --display-name "Action colusion"
gcloud secrets describe action-hub-token >/dev/null 2>&1 \
  || openssl rand -hex 24 | gcloud secrets create action-hub-token --data-file=-
gcloud secrets add-iam-policy-binding action-hub-token \
  --member="serviceAccount:${SA_EMAIL}" --role=roles/secretmanager.secretAccessor >/dev/null

FASE="Fase 3: base de datos (${BACKEND})"; echo "── ${FASE} ──"
ENV_BD=""
if [ "$BACKEND" = "spanner" ]; then
  gcloud spanner instances describe "$INSTANCIA_SPANNER" >/dev/null 2>&1 \
    || gcloud spanner instances create "$INSTANCIA_SPANNER" \
         --config="regional-${REGION}" --processing-units=100 \
         --edition=ENTERPRISE --description="Grafo de colusion"
  gcloud spanner databases describe "$BD_SPANNER" --instance="$INSTANCIA_SPANNER" >/dev/null 2>&1 \
    || gcloud spanner databases create "$BD_SPANNER" --instance="$INSTANCIA_SPANNER" \
         --ddl-file="${AQUI}/../sql/spanner_graph.sql"
  gcloud projects add-iam-policy-binding "$PROYECTO" \
    --member="serviceAccount:${SA_EMAIL}" --role=roles/spanner.databaseUser >/dev/null
  ENV_BD="SPANNER_INSTANCE=${INSTANCIA_SPANNER},SPANNER_DATABASE=${BD_SPANNER}"
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
  : "${ALLOYDB_DSN:?exporta ALLOYDB_DSN (host=IP_privada dbname=colusion user=postgres password=... sslmode=require) y reejecuta}"
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

URL="$(gcloud run services describe "$SERVICIO" --region "$REGION" --format='value(status.url)')"
gcloud run services update "$SERVICIO" --region "$REGION" \
  --update-env-vars "URL_BASE=${URL}" >/dev/null

TOKEN="$(gcloud secrets versions access latest --secret action-hub-token)"
cat <<FIN

════════════════════════════════════════════════════════════
Listo. Registra el Action Hub en Looker (paso manual, una vez):
  Admin → Platform → Actions → Add Action Hub
    URL:   ${URL}
    Token: ${TOKEN}
  Habilita "Escribir conclusión al grafo de colusión" y presiona Test.

Siguiente: ./probar.sh   (prueba end to end sin Looker)
Para el chat: python3 crear_agente.py y luego chat/app.py (ver README).
════════════════════════════════════════════════════════════
FIN
