FROM python:3.11-slim
WORKDIR /app
# git: architect_committer.py (app/agent_swarm/services/) shells out to
# real `git` commands (fetch/checkout/commit/push) for the Architect's
# commit/PR pipeline -- python:3.11-slim doesn't include it by default,
# confirmed live (`docker run --rm python:3.11-slim which git` finds
# nothing). Without this, POST /architect/run's commit step would fail
# with "git: command not found" the moment a real GITHUB_TOKEN and
# ARCHITECT_AUTO_COMMIT_ENABLED=true actually let it try.
RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
# sentence-transformers (app/search/embeddings.py) pulls in torch, and
# the default PyPI torch wheel bundles full CUDA runtime libraries
# (several GB) even though this service never touches a GPU -- installing
# the CPU-only build first satisfies that dependency without pip ever
# resolving the CUDA one.
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
