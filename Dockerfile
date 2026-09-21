# RVG Gateway — Docker image
# Works on Railway, Fly.io, Render, any container host

FROM python:3.12-slim

WORKDIR /app

# Install system deps for cryptography
RUN apt-get update && apt-get install -y --no-install-recommends \
    libffi-dev libssl-dev gcc \
    && rm -rf /var/lib/apt/lists/*

# Install Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy app
COPY . .

# Create /data for state
RUN mkdir -p /data

# Expose port (Railway/Render set PORT env var)
ENV PORT=8000
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD curl -f http://localhost:${PORT:-8000}/health || exit 1

# Run
CMD ["python3", "daemon.py", "--serve"]
