FROM python:3.12-slim
WORKDIR /app
RUN pip install --no-cache-dir "datasette>=0.65"
COPY . .
RUN python serve/build_public_db.py
EXPOSE 8002
CMD ["sh", "-c", "datasette serve data/public/atlas.db \
  --metadata serve/metadata.yaml \
  --template-dir serve/templates \
  --static static:serve/static \
  --plugins-dir serve/plugins \
  --setting max_returned_rows 10000 \
  --host 0.0.0.0 --port ${PORT:-8002}"]
