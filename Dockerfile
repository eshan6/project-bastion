# Project Bastion — HF Space (Docker)
# Build = clone v3 → install deps → regenerate seed-42 world (deterministic,
# byte-identical to committed canonical tables) → train Stage 3 → serve.
# Factory-rebuild the Space to pick up new commits on v3.
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
RUN git clone --depth 1 --branch v3 https://github.com/eshan6/project-bastion.git .

RUN pip install --no-cache-dir -r requirements.txt

# Regenerate the canonical world (fills the gitignored tables: weather_daily,
# pass_status_daily, consumption_daily, tempo_daily, aws_plan, pass_closures,
# wd_events) and stage them where the loaders read.
RUN cd stage2_world && python generate.py \
    && cp output/*.parquet data/

# Train Stage 3 (deterministic; ~60s) so model artifacts match the code.
RUN cd stage3_models && python train.py

# HF runs the container as uid 1000 — runtime dirs must be writable.
RUN chmod -R 777 /app

EXPOSE 7860
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "7860"]
