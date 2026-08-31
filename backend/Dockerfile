FROM python:3.11-slim

WORKDIR /app

COPY pyproject.toml requirements.txt ./
COPY src ./src

RUN pip install --no-cache-dir .

ENV BMSTU_RESULT_DIR=/app/data/result
EXPOSE 8000
VOLUME ["/app/data/result"]

CMD ["bmstu-api", "--host", "0.0.0.0", "--port", "8000"]
