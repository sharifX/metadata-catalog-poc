FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY catalog ./catalog
ENV PYTHONUNBUFFERED=1
# The same image runs as harvester or API; docker-compose.yml picks the command.
CMD ["uvicorn", "catalog.api:app", "--host", "0.0.0.0", "--port", "8000"]
