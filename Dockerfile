FROM python:3.11-slim

WORKDIR /app

# System deps for RDKit and chemistry libs
RUN apt-get update && apt-get install -y --no-install-recommends \
    libxrender1 \
    libxext6 \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml .
RUN pip install --no-cache-dir -e .

COPY . .

EXPOSE 8001

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001"]
