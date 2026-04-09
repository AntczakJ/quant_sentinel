# ══════════════════════════════════════════════════════════════════════════════
#  Quant Sentinel — Multi-stage Docker build
#
#  Stage 1: Build frontend (Node.js)
#  Stage 2: Production runtime (Python + nginx-served frontend)
#
#  Usage:
#    docker build -t quant-sentinel .
#    docker run -p 8000:8000 --env-file .env quant-sentinel
# ══════════════════════════════════════════════════════════════════════════════

# ── Stage 1: Frontend build ──────────────────────────────────────────────────
FROM node:20-alpine AS frontend-builder

WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --legacy-peer-deps

COPY frontend/ ./
RUN npm run build


# ── Stage 2: Production runtime ──────────────────────────────────────────────
FROM python:3.13-slim AS runtime

# System dependencies for bcrypt, numpy, etc.
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ libffi-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies (cached layer)
# Filter out Windows-only packages (DirectML) and install Linux equivalents
COPY requirements.txt ./
RUN grep -v "onnxruntime-directml" requirements.txt > requirements_linux.txt && \
    pip install --no-cache-dir -r requirements_linux.txt && \
    pip install --no-cache-dir onnxruntime && \
    rm requirements_linux.txt

# Copy application code
COPY src/ ./src/
COPY api/ ./api/
COPY run.py train_all.py pyproject.toml ./
COPY .env.example ./.env.example

# Copy models (if exist — training may happen inside container)
COPY models/ ./models/

# Copy pre-built frontend from Stage 1
COPY --from=frontend-builder /app/frontend/dist ./frontend/dist

# Create data directories with proper permissions
RUN mkdir -p data logs data/backups && chmod -R 777 data logs

# Expose API port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import requests; r=requests.get('http://localhost:8000/api/health', timeout=3); r.raise_for_status()" || exit 1

# Production entrypoint: uvicorn (no reload, workers=2)
CMD ["python", "-m", "uvicorn", "api.main:app", \
     "--host", "0.0.0.0", \
     "--port", "8000", \
     "--workers", "2", \
     "--log-level", "info", \
     "--access-log", \
     "--no-server-header"]
