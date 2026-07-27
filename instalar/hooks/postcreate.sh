#!/usr/bin/env bash
# Hook postcreate del boton: el servicio ya existe (K_SERVICE) y las env vars
# del app.json (incluido ACTION_HUB_TOKEN generado) estan en este shell.
# Deja el servicio en su forma final e imprime el bloque de registro.
set -euo pipefail
PROYECTO="$GOOGLE_CLOUD_PROJECT"
REGION="$GOOGLE_CLOUD_REGION"
source "$APP_DIR/instalar/fases.sh"

SA_EMAIL="colusion-action@${PROYECTO}.iam.gserviceaccount.com"
echo "── [botón] service account mínima en el servicio ──"
gcloud run services update "$K_SERVICE" --region "$REGION" --project "$PROYECTO" \
  --service-account "$SA_EMAIL" >/dev/null

echo "── [botón] espejar token en Secret Manager (para probar.sh) ──"
TOKEN="$(asegurar_secreto "${ACTION_HUB_TOKEN:-}")"

echo "── [botón] URL_BASE + verificación /listo ──"
URL="$(ligar_url_y_verificar "$K_SERVICE")"
resumen_registro "$URL" "$TOKEN"
