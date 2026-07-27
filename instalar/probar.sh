#!/usr/bin/env bash
# Prueba de ACEPTACION end to end contra el servicio desplegado (sin Looker).
# Falla con exit != 0 si cualquier garantia no se cumple:
#   salud, autenticacion, escritura, IDEMPOTENCIA ante reintentos,
#   ruta de revision humana y lectura del grafo.
set -euo pipefail
PROYECTO="${PROYECTO:?exporta PROYECTO}"
REGION="${REGION:-us-central1}"
INSTANCIA_SPANNER="${INSTANCIA_SPANNER:-colusion-graph}"
BD_SPANNER="${BD_SPANNER:-colusion}"
BACKEND="${BACKEND:-spanner}"

URL="$(gcloud run services describe colusion-action --region "$REGION" --format='value(status.url)')"
TOKEN="$(gcloud secrets versions access latest --secret action-hub-token)"
AUTH="Authorization: Token token=\"${TOKEN}\""
ok()   { echo "  ✔ $1"; }
fallo(){ echo "  ✖ $1" >&2; exit 1; }
corrida_de(){ python3 -c 'import sys,json;print(json.load(sys.stdin)["looker"]["message"].split(":")[0])'; }

SUFIJO="$(date +%s)"   # payload unico por corrida de prueba
PAYLOAD=$(python3 - "$SUFIJO" <<'PY'
import json, sys
s = sys.argv[1]
filas = [{"licitaciones.proveedor_a": "ACME", "licitaciones.proveedor_b": "BETA",
          "licitaciones.licitacion_id": f"L-DEMO-{s}", "licitaciones.score": 0.85}]
print(json.dumps({"type": "query",
  "scheduled_plan": {"title": "prueba aceptacion", "url": "", "query": {}},
  "attachment": {"mimetype": "application/json", "data": json.dumps(filas)},
  "form_params": {"modo": "auto", "notas": f"aceptacion {s}"}}))
PY
)

echo "── 1) Salud y readiness ──"
curl -sf "$URL/" >/dev/null            && ok "vivo (GET /)"
curl -sf "$URL/listo" >/dev/null       && ok "listo (base alcanzable)"

echo "── 2) Autenticacion ──"
CODIGO=$(curl -s -o /dev/null -w '%{http_code}' -X POST "$URL/")
[ "$CODIGO" = "401" ] && ok "sin token → 401" || fallo "sin token devolvió $CODIGO"
curl -sf -X POST "$URL/" -H "$AUTH" | grep -q escribir_grafo_colusion \
  && ok "lista de actions con token"

echo "── 3) Escritura ──"
R1=$(curl -sf -X POST "$URL/accion/execute" -H "$AUTH" -H "Content-Type: application/json" -d "$PAYLOAD")
echo "$R1" | grep -q '"success": true' || fallo "execute no fue success: $R1"
C1=$(echo "$R1" | corrida_de); ok "corrida $C1 escrita"

echo "── 4) Idempotencia (simula el reintento de Looker) ──"
C2=$(curl -sf -X POST "$URL/accion/execute" -H "$AUTH" -H "Content-Type: application/json" -d "$PAYLOAD" | corrida_de)
[ "$C1" = "$C2" ] && ok "mismo payload → misma corrida ($C1)" \
  || fallo "reintento generó corrida distinta: $C1 vs $C2"

echo "── 5) Ruta de revision humana ──"
PAYLOAD_REV=${PAYLOAD/'"modo": "auto"'/'"modo": "revision"'}
curl -sf -X POST "$URL/accion/execute" -H "$AUTH" -H "Content-Type: application/json" \
  -d "$PAYLOAD_REV" | grep -q RevisionPendiente && ok "encolada a RevisionPendiente"

if [ "$BACKEND" = "spanner" ]; then
  echo "── 6) El grafo dice la verdad ──"
  N=$(gcloud spanner databases execute-sql "$BD_SPANNER" --instance="$INSTANCIA_SPANNER" \
      --format='value(rows)' \
      --sql="SELECT COUNT(*) FROM ColudidoCon WHERE corrida_id='${C1}'" | tr -d "[]'")
  [ "$N" = "1" ] && ok "exactamente 1 arista para $C1 (sin duplicados)" \
    || fallo "esperaba 1 arista para $C1, hay: $N"
else
  echo "── 6) Verifica en AlloyDB: SELECT COUNT(*) FROM coludido_con WHERE corrida_id='${C1}'; (debe ser 1) ──"
fi

echo
echo "✔✔ ACEPTACION COMPLETA: end to end a prueba de balas"
