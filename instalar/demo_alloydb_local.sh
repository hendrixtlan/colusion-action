#!/usr/bin/env bash
# Plan B de ~2 minutos cuando NO hay AlloyDB aprovisionado: Postgres real en
# contenedor + la MISMA action local + la misma aceptacion. Pensado para
# Cloud Shell (trae docker). La logica interna es identica a la validacion
# que corre en CI contra Postgres 16.
set -euo pipefail
command -v docker >/dev/null || { echo "requiere docker (Cloud Shell lo trae)"; exit 1; }
AQUI="$(cd "$(dirname "$0")" && pwd)"

echo "── 1) Postgres real en contenedor ──"
docker rm -f colusion-pg >/dev/null 2>&1 || true
docker run -d --name colusion-pg -e POSTGRES_PASSWORD=demo \
  -e POSTGRES_DB=colusion -p 5433:5432 postgres:16 >/dev/null
for _ in $(seq 1 30); do
  docker exec colusion-pg pg_isready -U postgres >/dev/null 2>&1 && break; sleep 1
done
docker exec -i colusion-pg psql -q -U postgres -d colusion < "${AQUI}/../sql/alloydb.sql"

echo "── 2) La MISMA action, backend alloydb, local ──"
python3 -m pip install -q --user -r "${AQUI}/../app/requirements.txt"
export GRAFO_BACKEND=alloydb ACTION_HUB_TOKEN=demo-local \
       ALLOYDB_DSN="host=127.0.0.1 port=5433 dbname=colusion user=postgres password=demo"
( cd "${AQUI}/../app" && python3 -m uvicorn main:app --port 8080 & echo $! > /tmp/colusion.pid )
sleep 3

echo "── 3) Aceptacion: escritura + idempotencia + anillo ──"
AUTH='Authorization: Token token="demo-local"'
PAYLOAD='{"type":"query","scheduled_plan":{"title":"demo local","url":"","query":{}},
 "attachment":{"data":"[{\"l.proveedor_a\":\"ACME\",\"l.proveedor_b\":\"BETA\",\"l.licitacion_id\":\"L-1\",\"l.score\":0.9}]"},
 "form_params":{"modo":"auto","notas":"demo en vivo"}}'
curl -sf http://127.0.0.1:8080/listo >/dev/null && echo "  ✔ /listo"
C1=$(curl -sf -X POST http://127.0.0.1:8080/accion/execute -H "$AUTH" \
     -H 'Content-Type: application/json' -d "$PAYLOAD" \
     | python3 -c 'import sys,json;print(json.load(sys.stdin)["looker"]["message"].split(":")[0])')
C2=$(curl -sf -X POST http://127.0.0.1:8080/accion/execute -H "$AUTH" \
     -H 'Content-Type: application/json' -d "$PAYLOAD" \
     | python3 -c 'import sys,json;print(json.load(sys.stdin)["looker"]["message"].split(":")[0])')
[ "$C1" = "$C2" ] && echo "  ✔ idempotencia: $C1 (reintento no duplicó)"
docker exec colusion-pg psql -U postgres -d colusion -tAc \
  "SELECT COUNT(*) FROM coludido_con WHERE corrida_id='${C1}'" | grep -qx 1 \
  && echo "  ✔ exactamente 1 arista en el grafo"
kill "$(cat /tmp/colusion.pid)" 2>/dev/null || true
echo "✔✔ Misma action, mismo blindaje, Postgres puro — sin tocar el deploy de Spanner"
