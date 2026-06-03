# Tableau MCP sidecar — Entra/api-key front door + Entra->Tableau identity passthrough.
# Runs in front of the OFFICIAL Tableau MCP image; this container is the public ingress.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=9000

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY config.py identity.py proxy.py ./

# Drop privileges.
RUN useradd --create-home --uid 10001 appuser
USER appuser

EXPOSE 9000

# --factory builds + validates the config at startup; bad config fails the container loudly.
CMD ["sh", "-c", "uvicorn --factory proxy:create_app --host 0.0.0.0 --port ${PORT}"]
