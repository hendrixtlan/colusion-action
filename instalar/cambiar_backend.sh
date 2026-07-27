#!/usr/bin/env bash
# Cambio de backend EN VIVO del servicio desplegado (la jugada de media demo).
#
#   PROYECTO=... REGION=... ./instalar/cambiar_backend.sh alloydb "host=... dbname=colusion ..."
#   PROYECTO=... REGION=... ./instalar/cambiar_backend.sh spanner
#
# Solo actualiza variables (nunca borra: las del otro backend quedan inertes,
# el codigo lee GRAFO_BACKEND primero). Nueva revision en ~30-60 s y espera
# /listo contra la base nueva. OJO: cada backend es su propia base; el cambio
# arranca el grafo de ese backend tal como este (no migra datos).
set -euo pipefail
PROYECTO="${PROYECTO:?exporta PROYECTO}"
REGION="${REGION:-us-central1}"
DESTINO="${1:?uso: cambiar_backend.sh spanner|alloydb [DSN]}"
AQUI="$(cd "$(dirname "$0")" && pwd)"
source "${AQUI}/fases.sh"

case "$DESTINO" in
  spanner)
    VARS="GRAFO_BACKEND=spanner,SPANNER_INSTANCE=${INSTANCIA_SPANNER:-colusion-graph},SPANNER_DATABASE=${BD_SPANNER:-colusion}"
    ;;
  alloydb)
    DSN="${2:-${ALLOYDB_DSN:-}}"
    [ -n "$DSN" ] || { echo "falta el DSN de AlloyDB (arg 2 o ALLOYDB_DSN)"; exit 1; }
    VARS="GRAFO_BACKEND=alloydb,ALLOYDB_DSN=${DSN}"
    FLAGS_RED=()
    [ -n "${RED:-}" ] && FLAGS_RED=(--network="$RED" --subnet="${SUBRED:-$RED}" \
                                    --vpc-egress=private-ranges-only)
    ;;
  *) echo "backend desconocido: $DESTINO"; exit 1 ;;
esac

echo "── Cambiando colusion-action a ${DESTINO} ──"
gcloud run services update colusion-action --region "$REGION" --project "$PROYECTO" \
  --update-env-vars "$VARS" "${FLAGS_RED[@]:-}" >/dev/null
URL="$(ligar_url_y_verificar colusion-action)"
echo "✔ ${URL} respondiendo /listo contra ${DESTINO}"
echo "Cierra el momento: BACKEND=${DESTINO} PROYECTO=${PROYECTO} REGION=${REGION} ${AQUI}/probar.sh"
