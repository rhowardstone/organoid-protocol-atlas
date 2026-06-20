# Public Organoid Protocol Atlas — Datasette over the LICENSE-SAFE (CC-only) subset.
# The DB is BUILT from committed license-safe JSONL exports at image build (we never
# commit a generated .db). /ask degrades gracefully when no local model is configured.
FROM python:3.12-slim

WORKDIR /app

# Serve layer only needs Datasette (the DB builder uses stdlib). Keep the image lean.
RUN pip install --no-cache-dir "datasette>=0.65"

COPY . .

# Build the public KG from the committed CC-only exports (data/public/atlas.db).
RUN python serve/build_public_db.py

EXPOSE 8002
# Render (and most PaaS) inject $PORT; default to 8002 locally.
CMD ["sh", "-c", "datasette serve data/public/atlas.db \
  --metadata serve/metadata.yaml \
  --template-dir serve/templates \
  --static static:serve/static \
  --plugins-dir serve/plugins \
  --host 0.0.0.0 --port ${PORT:-8002}"]
