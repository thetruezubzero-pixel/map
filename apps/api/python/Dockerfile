FROM python:3.11-slim
WORKDIR /app
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
