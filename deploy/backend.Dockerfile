FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libglib2.0-0 \
        libgl1 \
        libsm6 \
        libxext6 \
        libxrender1 \
    && rm -rf /var/lib/apt/lists/*

COPY plantbackend/requirements.txt /tmp/requirements.txt
RUN pip install --upgrade pip \
    && pip install -r /tmp/requirements.txt

COPY deploy/backend-entrypoint.sh /usr/local/bin/backend-entrypoint.sh
COPY plantbackend /opt/plantbackend-seed
COPY plantbackend /app/plantbackend
RUN mkdir -p \
    /app/plantbackend/models \
    /app/plantbackend/annotation_datasets \
    /app/plantbackend/training_runs \
    /app/plantbackend/runtime \
    /opt/plantbackend-seed/models \
    /opt/plantbackend-seed/annotation_datasets \
    /opt/plantbackend-seed/training_runs \
    /opt/plantbackend-seed/runtime \
    && chmod +x /usr/local/bin/backend-entrypoint.sh

EXPOSE 7800

CMD ["/usr/local/bin/backend-entrypoint.sh"]
