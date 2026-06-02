# Tableau-Fabric-AI-Bridge MCP server.
# Build context = repo root (so we can copy the shared skill scripts in):
#   docker build -f Play1/Dockerfile -t tableau-fabric-mcp .
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    MCP_TRANSPORT=http \
    PORT=8000 \
    TABLEAU_SCRIPTS_DIR=/app/tableau_scripts

WORKDIR /app

# Install dependencies first for better layer caching.
COPY Play1/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# The MCP server code.
COPY Play1/server.py /app/server.py

# The single source of truth: the live-tested Tableau client/auth/VDS skill scripts.
COPY .github/skills/tableau-datasource-profiler/scripts/profile_datasource.py /app/tableau_scripts/profile_datasource.py
COPY .github/skills/tableau-datasource-profiler/scripts/query_datasource.py /app/tableau_scripts/query_datasource.py

# Run as a non-root user.
RUN useradd --create-home --uid 10001 appuser && chown -R appuser /app
USER appuser

EXPOSE 8000

# Container Apps / any platform sends traffic to $PORT; the server reads it.
CMD ["python", "/app/server.py"]
