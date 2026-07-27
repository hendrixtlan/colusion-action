# Instalar colusion-action (guiado)

Este tutorial corre en Cloud Shell con el repo ya clonado. Cuatro pasos.

## 1. Elegir proyecto y desplegar

```bash
export PROYECTO=$(gcloud config get-value project)
export REGION=us-central1 BACKEND=spanner
./instalar/desplegar.sh
```

Crea APIs, service account, token, Spanner Enterprise (100 PU) con el
grafo, y el servicio en Cloud Run. Al final imprime **URL y token**:
guardalos.

## 2. Aceptacion end to end (sin Looker)

```bash
./instalar/probar.sh
```

Verifica salud, 401 sin token, escritura, **idempotencia ante reintentos**
(mismo payload dos veces → 1 sola arista) y la ruta de revision humana.
Si esto imprime `✔✔ ACEPTACION COMPLETA`, la tuberia funciona.

## 3. Registrar en Looker (unico paso manual)

En tu instancia de Looker: **Admin → Platform → Actions → Add Action Hub**,
pega la URL y el token del paso 1, habilita la action y presiona **Test**.
Desde aqui ya funcionan Explore → Send, schedules y la action de celda.

## 4. (Opcional) Detonar desde el chat

```bash
export LOOKER_BASE_URL=https://TU_INSTANCIA.cloud.looker.com \
       EXPLORES="modelo:explore" DATA_AGENT_ID=colusion
python3 instalar/crear_agente.py
cd chat && pip install -r requirements.txt
export GOOGLE_CLOUD_PROJECT=$PROYECTO LOOKER_CLIENT_ID=... LOOKER_CLIENT_SECRET=... \
       ACTION_URL=<URL del paso 1> ACTION_HUB_TOKEN=<token del paso 1>
streamlit run app.py
```

Listo: agente → action → grafo, con auditoria completa por `Corrida`.
