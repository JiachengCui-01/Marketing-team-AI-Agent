FROM mcr.microsoft.com/playwright/python:v1.61.0-noble

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

WORKDIR /app

COPY . /app
RUN pip install --no-cache-dir -e . && \
    mkdir -p /var/data/rembg && \
    chown -R pwuser:pwuser /app /var/data

# Render mounts the persistent disk after the image has been built, so the
# image-time chown above cannot set the ownership of the mounted filesystem.
# Start as root only long enough to repair that ownership, then drop privileges
# before starting the API and Chromium.
USER root

CMD ["bash", "-lc", "chown -R pwuser:pwuser /var/data && exec runuser --preserve-environment -u pwuser -- uvicorn server.main:app --host 0.0.0.0 --port ${PORT:-10000}"]
