# League Lab's dashboard image, deployed to Cloud Run as the `league-lab` service
# (docs/multiLeagueDocs/phase1.md has the full deploy command). Built from the repo
# root: it needs app/, the ingest package's ESPN client and category catalog (used
# when a league is registered), and .streamlit/config.toml (the theme).
# .gcloudignore keeps everything else -- and every secret -- out of the upload.
# The ingest job has its own image (ingest/Dockerfile).
#
# Sign-in settings are NOT baked in: Cloud Run mounts them from Secret Manager at
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
COPY ingest/__init__.py ingest/catalog.py ingest/espn_client.py ingest/
COPY app/ app/

# Cloud Run sends traffic to $PORT (8080 by default).
CMD exec streamlit run app/Home.py \
    --server.port="${PORT:-8080}" \
    --server.address=0.0.0.0 \
    --server.headless=true \
    --browser.gatherUsageStats=false
