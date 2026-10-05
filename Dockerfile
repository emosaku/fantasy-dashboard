# The dashboard's image (Step 7), deployed to Cloud Run with:
#   gcloud run deploy fantasy-dash --source . ...   (full command: docs/step7-deploy.md)
# Built from the repo root because it needs app/ AND .streamlit/config.toml (the
# theme). .gcloudignore keeps everything else -- and every secret -- out of the upload.
# The ingest job has its own image (ingest/Dockerfile).
#
# Logins are NOT baked in: Cloud Run mounts them from Secret Manager at
# /root/.streamlit/secrets.toml, Streamlit's global secrets file. (Mounting into the
# app's own .streamlit/ would hide config.toml, since a mount takes over its folder.)
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /srv

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY .streamlit/config.toml .streamlit/config.toml
COPY app/ app/

# Cloud Run sends traffic to $PORT (8080 by default).
CMD exec streamlit run app/Home.py \
    --server.port="${PORT:-8080}" \
    --server.address=0.0.0.0 \
    --server.headless=true \
    --browser.gatherUsageStats=false
