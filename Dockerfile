FROM mcr.microsoft.com/playwright/python:v1.61.0-noble

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

WORKDIR /app

COPY . /app
RUN pip install --no-cache-dir -e . && \
    mkdir -p /var/data/rembg && \
    chown -R pwuser:pwuser /app /var/data

USER pwuser

CMD ["bash", "-lc", "uvicorn server.main:app --host 0.0.0.0 --port ${PORT:-10000}"]
