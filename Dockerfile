FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

# Offline by default (stub model, TF-IDF retrieval). For real runs pass keys at run time, never bake them in:
#   docker run --rm --env-file .env -v "$PWD/out:/app/out" support-ticket-pipeline \
#     sh -c "python run_pipeline.py --out-dir out && python validate.py --out-dir out"
CMD ["sh", "-c", "python run_pipeline.py --provider stub --out-dir out && python validate.py --out-dir out"]
