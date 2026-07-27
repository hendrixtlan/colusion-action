# colusion-action: un agente en Looker + una action + un grafo

Version minima del patron de [fleet-agent](https://github.com/hendrixtlan/fleet-agent):
en lugar de flotas de agentes ADK en Cloud Run Jobs, **un solo data agent de
Conversational Analytics dentro de Looker** hace el analisis, y una **action
custom** (Action API de Looker, servida desde Cloud Run) escribe las
conclusiones de colusion a un grafo: **Spanner Graph** por defecto, **AlloyDB**
como alternativa de costo. El principio se conserva: *el LLM propone, el codigo
dispone* — el agente solo arma consultas gobernadas por LookML; toda escritura
al grafo es codigo determinista e idempotente con proveniencia (nodo `Corrida`).

```
analista ⇄ data agent (Conversational Analytics, Looker)
                │  consulta gobernada (Explore)
                ▼
        Send / Schedule ──► Action "Escribir conclusión al grafo de colusión"
                                    │  POST /accion/execute (Cloud Run)
                                    ▼
                      filas → nodos/aristas (determinista)
                                    │
                     ┌──────────────┴──────────────┐
                     ▼                             ▼
             Spanner Graph (GQL)          AlloyDB (SQL + WITH RECURSIVE)
             GrafoColusion                mismas tablas, ON CONFLICT
```

## Instalación end to end (runbook)

```bash
# 0. Prerrequisitos: gcloud autenticado, proyecto con billing,
#    credenciales API de Looker (client id/secret) y permisos de Owner/Editor.
gcloud auth login && gcloud auth application-default login

# 1. Infraestructura + action (APIs, base, secreto, Cloud Run)
export PROYECTO=mi-proyecto REGION=us-central1 BACKEND=spanner
./instalar/desplegar.sh          # imprime URL y token al final

# 2. Probar SIN Looker (si esto pasa, la tubería completa funciona)
./instalar/probar.sh             # list → execute → lee ColudidoCon del grafo

# 3. Registro en Looker (manual, una sola vez):
#    Admin → Platform → Actions → Add Action Hub → URL + token → Test.
#    Desde aquí ya funcionan Explore→Send, schedules y la action de celda.

# 4. (Para detonar desde el chat) crear el data agent de la CA API:
export LOOKER_BASE_URL=https://tuempresa.cloud.looker.com \
       EXPLORES="compras:licitaciones" DATA_AGENT_ID=colusion
python3 instalar/crear_agente.py # imprime el DATA_AGENT_ID completo

# 5. Correr el chat (local, o a Cloud Run con chat/Dockerfile)
cd chat && pip install -r requirements.txt
export GOOGLE_CLOUD_PROJECT=$PROYECTO LOOKER_CLIENT_ID=... LOOKER_CLIENT_SECRET=... \
       ACTION_URL=<URL del paso 1> ACTION_HUB_TOKEN=<token del paso 1>
streamlit run app.py             # variante agente-detona: adk web (raiz_adk.py)
```

Orden de dependencias: la base y la action no necesitan nada de Looker; el
paso 3 habilita los caminos nativos; los pasos 4–5 solo hacen falta para
detonar desde el chat. `desplegar.sh` es idempotente: reejecutarlo no
duplica recursos.



```
app/          servicio Action API (FastAPI) para Cloud Run
  main.py         endpoints: / (lista), /accion/form, /accion/execute, /accion/celda
  contratos.py    ConclusionColusion, Implicado, Arista (Pydantic)
  repositorio.py  puerto GrafoRepositorio + adaptadores Spanner y AlloyDB
sql/
instalar/     desplegar.sh (infra+deploy), probar.sh (e2e sin Looker), crear_agente.py
chat/         app.py (boton detona), raiz_adk.py (agente detona), comun.py
  spanner_graph.sql   DDL + CREATE PROPERTY GRAPH + consultas GQL de ejemplo
  alloydb.sql         DDL espejo + consultas SQL recursivas equivalentes
```

## 1. Base de datos

### Opcion A — Spanner Graph (por defecto)

Spanner Graph requiere **edicion Enterprise** y dialecto **GoogleSQL**.
Con 100 processing units alcanza para arrancar:

```bash
gcloud spanner instances create colusion-graph \
  --config=regional-us-central1 --processing-units=100 \
  --edition=ENTERPRISE --description="Grafo de colusion"

gcloud spanner databases create colusion --instance=colusion-graph \
  --ddl-file=sql/spanner_graph.sql
```

> Nota si reutilizas el `spanner.tf` de fleet-agent: agrega
> `edition = "ENTERPRISE"` al `google_spanner_instance`, o el
> `CREATE PROPERTY GRAPH` fallara.

### Opcion B — AlloyDB (si el costo de Spanner asusta)

```bash
gcloud alloydb clusters create colusion --region=us-central1 \
  --password=<contrasena-postgres>
gcloud alloydb instances create colusion-primaria --cluster=colusion \
  --region=us-central1 --instance-type=PRIMARY --cpu-count=2
psql "$ALLOYDB_DSN" -f sql/alloydb.sql
```

AlloyDB gestionado no trae extension de grafos, asi que el grafo vive en
tablas de nodos/aristas y los recorridos usan `WITH RECURSIVE` (ver
`sql/alloydb.sql`). El esquema es espejo del de Spanner: migrar despues es
copiar tablas y agregar el `CREATE PROPERTY GRAPH`.

## 2. Desplegar la action en Cloud Run

```bash
# token compartido entre Looker y el servicio
openssl rand -hex 24 | gcloud secrets create action-hub-token --data-file=-

gcloud run deploy colusion-action --source app/ --region us-central1 \
  --allow-unauthenticated \
  --set-secrets ACTION_HUB_TOKEN=action-hub-token:latest \
  --set-env-vars GRAFO_BACKEND=spanner,GOOGLE_CLOUD_PROJECT=<proyecto>,SPANNER_INSTANCE=colusion-graph,SPANNER_DATABASE=colusion

# segunda pasada: fijar URL_BASE con la URL que Cloud Run asigno
gcloud run services update colusion-action --region us-central1 \
  --update-env-vars URL_BASE=https://colusion-action-XXXX.run.app
```

Para AlloyDB: `GRAFO_BACKEND=alloydb` y `ALLOYDB_DSN=host=... dbname=colusion
user=... password=... sslmode=require` (con IP privada + VPC connector, o el
AlloyDB Auth Proxy como sidecar). Da al service account del servicio
`roles/spanner.databaseUser` o `roles/alloydb.client` segun el backend.

`--allow-unauthenticated` es necesario porque Looker no firma peticiones IAM
de Google; la autenticacion real es el token del Action Hub, que `main.py`
valida en cada peticion. Opcional: restringir ingress con Cloud Armor a las
IPs de tu instancia de Looker.

## 3. Registrar en Looker

1. **Admin → Platform → Actions → "Add Action Hub"** (hasta abajo).
2. Action Hub URL: la URL raiz del servicio (`https://colusion-action-XXXX.run.app`).
3. En **Configure Authorization**, pega el mismo token del secreto.
4. Habilita la action "Escribir conclusión al grafo de colusión" y usa **Test**.

## 4. Como la usa el agente (tres caminos)

**a) Conversacional → Send.** El analista conversa con el data agent
(Conversational Analytics) sobre el Explore de licitaciones: *"¿qué pares de
proveedores comparten más del 80% de licitaciones y alternan ganador?"*. El
agente arma la consulta gobernada; el analista la abre en el Explore y con el
engrane **Send** elige la action. El form pregunta modo (directo / revisión
humana), score y notas → eso se persiste como `Corrida` + aristas.

**b) Schedules = flotas.** Guarda la consulta como Look y programala con la
action como destino. Cada schedule equivale a una "flota" de fleet-agent, sin
Cloud Scheduler ni Jobs: Looker ya trae el cron.

**c) Celda (LookML).** Para marcar una colusion puntual desde cualquier tabla:

```lookml
dimension: proveedor_id {
  sql: ${TABLE}.proveedor_id ;;
  action: {
    label: "Marcar colusión en el grafo"
    url: "https://colusion-action-XXXX.run.app/accion/celda"
    form_param: { name: "coludido_con" type: string label: "Coludido con (proveedor_id)" required: yes }
    form_param: { name: "notas" type: textarea label: "Notas del analista" }
  }
}
```

### Columnas que la action sabe mapear

Por sufijo del nombre de campo (configurable por env vars `CAMPO_*`):

| Forma | Campos minimos | Se escribe |
|---|---|---|
| pares | `proveedor_a`, `proveedor_b` (+`licitacion_id`, `score`) | `COLUDIDO_CON` (+`PARTICIPO_EN`) |
| bipartita | `proveedor`, `licitacion_id` | `PARTICIPO_EN`; los anillos se descubren luego con GQL/SQL |

El resto de columnas de cada fila viaja como `props` de la arista (la
evidencia queda pegada a la relacion).

### Instrucciones sugeridas para el data agent

En Looker → Conversations → Manage agents → New agent, sobre el Explore de
licitaciones, algo como:

> Eres un analista antimonopolio. Señales de colusión que debes buscar:
> proveedores que comparten alta proporción de licitaciones, alternancia de
> ganador (rotación de posturas), diferencias de postura constantes,
> retiros sistemáticos. Cuando propongas una lista de pares sospechosos,
> incluye siempre las columnas proveedor_a, proveedor_b, licitacion_id y una
> medida de score entre 0 y 1, porque ese es el formato que la action
> "Escribir conclusión al grafo de colusión" sabe convertir en aristas.

Agrega golden queries con esas consultas verificadas para anclar el patron.

## 5. Detonar la action desde el chat (carpeta `chat/`)

El chat nativo de Conversational Analytics **dentro** de Looker no puede
invocar actions custom del Action Hub (sus unicos disparos automaticos hoy
son los agentic workflows en preview, con destinos email/Slack/app movil).
Para detonar desde el chat se construye un chat propio del mismo agente;
ambas variantes pegan al mismo `/accion/execute` con el mismo token:

**a) `chat/app.py` — el humano detona (recomendado para arrancar).**
Front Streamlit que conversa con el data agent via la Conversational
Analytics API (fuente Looker: mismos Explores, instrucciones y golden
queries), conserva las ultimas filas que el agente devolvio y un boton
"Escribir conclusion al grafo" las manda a la action. Determinista: ningun
LLM decide escrituras.

```bash
cd chat && pip install -r requirements.txt
export GOOGLE_CLOUD_PROJECT=... CA_LOCATION=global DATA_AGENT_ID=colusion \
       LOOKER_CLIENT_ID=... LOOKER_CLIENT_SECRET=... \
       ACTION_URL=https://colusion-action-XXXX.run.app ACTION_HUB_TOKEN=...
streamlit run app.py
```

Nota: los agentes creados dentro de Looker no son visibles fuera de Looker;
para este camino el data agent se crea como recurso de la CA API con fuente
Looker (mismas instrucciones), o bien se usa el patron equivalente con los
endpoints `ConversationalAnalytics` del API de Looker si prefieres que el
agente siga gestionado en Looker.

**b) `chat/raiz_adk.py` — el agente detona (patron "governed" de ADK).**
Agente raiz con `DataAgentToolset` (tool `ask_data_agent`) + la tool custom
`escribir_grafo_colusion`. El usuario puede decir *"y escribe esa conclusion
al grafo"* y el agente llama la tool. Guardrail: la tool escribe en modo
`revision` (RevisionPendiente) salvo peticion explicita de escritura
directa, y la conversion filas→aristas sigue siendo la de la action.
Probar local con `adk web`.

Este chat puede embeberse de vuelta en Looker (extension framework / iframe)
para que los analistas no salgan de Looker.

## A prueba de balas: garantias y politica de fallas

**Idempotencia real.** `corrida_id` es un hash del contenido del payload
(plan + adjunto + form). Looker reintenta webhooks fallidos y un schedule
puede disparar dos veces: con corridas deterministas el grafo converge en
vez de duplicarse. Efecto deliberado: la conclusion identica dos veces
deduplica a una corrida; cambiar las notas fuerza una nueva. Aplica tambien
al doble clic de la action de celda.

**Politica de errores (quien reintenta y cuando).** Payload invalido o
columnas no mapeables → HTTP 200 con `success:false` y explicacion
(reintentar no ayuda; no hay tormenta de retries). Error de base →
HTTP 503 para que Looker SI reintente — es seguro por la idempotencia.
Ademas el repositorio reintenta internamente errores transitorios
(Aborted, ServiceUnavailable, Deadline, OperationalError...) con backoff
exponencial, 3 intentos.

**Limites explicitos.** `MAX_BYTES` (20 MB) por peticion y `MAX_FILAS`
(2000) procesadas con aviso en el mensaje; Spanner escribe en lotes de
`LOTE_ESCRITURA` (500) filas por commit para no rozar los limites de
mutaciones por transaccion. Cada commit es idempotente: si truena a la
mitad, el reintento converge.

**Celdas hostiles.** `{"value": x, "rendered": "..."}`, scores como
"0.85" o "85%", nulos, columnas extra: todo se normaliza o viaja como
props; nada tira el endpoint (ver `app/pruebas.py`).

**Operacion.** `GET /` = vivo; `GET /listo` = readiness que verifica la
base (usalo como uptime check y para el probe de Cloud Run). Logs JSON
estructurados con `severity`, `evento`, `corrida` — filtrables en Cloud
Logging; alerta sugerida: `severity>=ERROR AND jsonPayload.evento="persistencia_fallida"`.
Token comparado en tiempo constante.

**Verificacion continua.** `cd app && python3 -m pytest pruebas.py`
(15 pruebas de estas garantias, sin GCP) y `./instalar/probar.sh` como
aceptacion post-deploy: salud, 401, escritura, doble disparo con
`COUNT(*)==1`, ruta de revision y lectura del grafo. Corre la aceptacion
despues de cada deploy y antes de cada demo.

## Nota de costos (el miedo a Spanner)

El miedo suele venir del minimo historico de 1 nodo. Hoy Spanner arranca en
100 processing units (una decima de nodo) — del orden de decenas de dolares al
mes en una region tipica, mas storage — aunque Graph exige edicion Enterprise,
algo mas cara por PU que Standard. La instancia minima de AlloyDB (2 vCPU) no
es gratis tampoco; a esta escala los dos quedan en el mismo orden de magnitud,
asi que la eleccion real es GQL nativo y cero ops (Spanner) contra ecosistema
Postgres conocido (AlloyDB). Valida cifras del dia en la calculadora de precios
de Google Cloud antes de prometerle nada al cliente.

## Seguridad y auditoria

- Nada probabilistico escribe: el agente no tiene credenciales de la base.
- Toda escritura cuelga de `Corrida` (quien, cuando, con que consulta).
- Modo "revisión" del form → `RevisionPendiente`, y nada toca el grafo hasta
  aprobar (equivalente al camino ambar de fleet-agent).
- Token de Action Hub validado en cada endpoint; rota el secreto sin redeploy.
