# AgentCore — cloud deployment (Phase 8)
# Runs the SAME runtime as local dev/prod: `python main.py serve`
FROM python:3.12-slim

WORKDIR /app

# deps first for layer caching
COPY pyproject.toml requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# source (excludes data/, logs/, .env via .dockerignore)
COPY . .

# runtime data dir
RUN mkdir -p data logs

# the runtime serves the dashboard + REST/WS APIs (no hot reload in prod)
EXPOSE 8000
ENV AGENTCORE_PORT=8000

# healthcheck against the runtime health endpoint
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=3).status==200 else 1)" || exit 1

CMD ["python", "main.py", "serve"]
