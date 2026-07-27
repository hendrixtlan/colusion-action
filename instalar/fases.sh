#!/usr/bin/env bash
# Fases compartidas del despliegue. UNA fuente de verdad: las usan
# desplegar.sh (CLI) y los hooks del boton "Run on Google Cloud".
# Todas idempotentes. Requieren: PROYECTO, REGION.

SA="colusion-action"

habilitar_apis() {
  gcloud services enable run.googleapis.com cloudbuild.googleapis.com \
    artifactregistry.googleapis.com secretmanager.googleapis.com \
    geminidataanalytics.googleapis.com spanner.googleapis.com \
    --project "$PROYECTO"
}

preparar_identidad() {
  local sa_email="${SA}@${PROYECTO}.iam.gserviceaccount.com"
  gcloud iam service-accounts describe "$sa_email" --project "$PROYECTO" >/dev/null 2>&1 \
    || gcloud iam service-accounts create "$SA" --project "$PROYECTO" \
         --display-name "Action colusion"
  gcloud projects add-iam-policy-binding "$PROYECTO" \
    --member="serviceAccount:${sa_email}" \
    --role=roles/spanner.databaseUser >/dev/null
  echo "$sa_email"
}

# asegurar_secreto [VALOR]: crea el secreto (aleatorio si no hay VALOR) o
# agrega version si VALOR viene y el secreto ya existe. Imprime el valor.
asegurar_secreto() {
  local valor="${1:-}"
  if ! gcloud secrets describe action-hub-token --project "$PROYECTO" >/dev/null 2>&1; then
    [ -n "$valor" ] || valor="$(openssl rand -hex 24)"
    printf '%s' "$valor" | gcloud secrets create action-hub-token \
      --project "$PROYECTO" --data-file=-
  elif [ -n "$valor" ]; then
    local actual
    actual="$(gcloud secrets versions access latest --secret action-hub-token \
              --project "$PROYECTO" 2>/dev/null || true)"
    [ "$actual" = "$valor" ] || printf '%s' "$valor" | gcloud secrets versions add \
      action-hub-token --project "$PROYECTO" --data-file=-
  fi
  gcloud secrets versions access latest --secret action-hub-token --project "$PROYECTO"
}

preparar_spanner() {
  local instancia="${INSTANCIA_SPANNER:-colusion-graph}"
  local bd="${BD_SPANNER:-colusion}"
  local ddl="$1"   # ruta a sql/spanner_graph.sql
  gcloud spanner instances describe "$instancia" --project "$PROYECTO" >/dev/null 2>&1 \
    || gcloud spanner instances create "$instancia" --project "$PROYECTO" \
         --config="regional-${REGION}" --processing-units=100 \
         --edition=ENTERPRISE --description="Grafo de colusion"
  gcloud spanner databases describe "$bd" --instance="$instancia" \
      --project "$PROYECTO" >/dev/null 2>&1 \
    || gcloud spanner databases create "$bd" --instance="$instancia" \
         --project "$PROYECTO" --ddl-file="$ddl"
}

# ligar_url_y_verificar SERVICIO: fija URL_BASE en el servicio y espera /listo
ligar_url_y_verificar() {
  local servicio="$1" url
  url="$(gcloud run services describe "$servicio" --region "$REGION" \
         --project "$PROYECTO" --format='value(status.url)')"
  gcloud run services update "$servicio" --region "$REGION" --project "$PROYECTO" \
    --update-env-vars "URL_BASE=${url},GOOGLE_CLOUD_PROJECT=${PROYECTO}" >/dev/null
  for _ in 1 2 3 4 5 6; do
    curl -sf "${url}/listo" >/dev/null && { echo "$url"; return 0; }
    sleep 5
  done
  echo "$url"
  echo "aviso: /listo aún no responde; revisa logs del servicio" >&2
}

resumen_registro() {
  local url="$1" token="$2"
  cat <<FIN

════════════════════════════════════════════════════════════
Servicio listo y verificado: ${url}

Único paso manual restante (Looker, una vez):
  Admin → Platform → Actions → Add Action Hub
    URL:   ${url}
    Token: ${token}
  Habilita "Escribir conclusión al grafo de colusión" → Test.

Aceptación end to end:  PROYECTO=${PROYECTO} REGION=${REGION} ./instalar/probar.sh
════════════════════════════════════════════════════════════
FIN
}
