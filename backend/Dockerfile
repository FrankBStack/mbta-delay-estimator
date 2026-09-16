FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

# gtfs_static writes its download to /app/.cache
RUN useradd --system --uid 1000 app && mkdir -p /app/.cache && chown -R app:app /app
USER app

EXPOSE 8010
# behind nginx and Caddy: trust X-Forwarded-Proto so anything the app builds
# from the request URL says https, not http
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8010", \
     "--proxy-headers", "--forwarded-allow-ips", "*"]
