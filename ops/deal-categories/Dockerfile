ARG BASE_IMAGE=crawler-image:latest
FROM ${BASE_IMAGE}
COPY gadmin/categories /app/gadmin/categories
COPY gadmin/metrics /app/gadmin/metrics
COPY gadmin/products /app/gadmin/products
COPY gadmin/thumbnails/__init__.py gadmin/thumbnails/fetch.py /app/gadmin/thumbnails/
COPY gadmin/deals /app/gadmin/deals
ENV PYTHONPATH=/app DJANGO_SETTINGS_MODULE=gadmin.categories.settings PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
ENTRYPOINT []
CMD ["python", "-m", "gadmin.categories.worker"]
