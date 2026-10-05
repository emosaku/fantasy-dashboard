# Build context is this directory (ingest/) -- gcloud run jobs deploy --source ingest/
# uses this Dockerfile directly. ingest/requirements.txt is a lean subset of the repo
# root requirements.txt (no streamlit/plotly) so the deployed image only carries what
# the job itself needs.
#
# `COPY . ./ingest` re-nests this directory's own contents one level deeper inside the
# image -- that's deliberate, not a typo: it reproduces the ingest.* package layout
# main.py's imports expect (from ingest.transform import ...), even though the build
# context here is already the ingest/ folder.
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . ./ingest

CMD ["python", "-m", "ingest.main"]
