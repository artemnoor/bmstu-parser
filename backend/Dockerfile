FROM python:3.11-slim

WORKDIR /app

COPY pyproject.toml requirements.txt ./
COPY src ./src

RUN apt-get update \
    && apt-get install -y --no-install-recommends poppler-utils \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir .

ENV BMSTU_RESULT_DIR=/app/data/result
ENV BMSTU_API_HOST=0.0.0.0
EXPOSE 8000
VOLUME ["/app/data/result"]

CMD ["bmstu-api", "--host", "0.0.0.0", "--port", "8000"]
