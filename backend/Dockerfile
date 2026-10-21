FROM python:3.12-slim

WORKDIR /app
COPY README.md /app/README.md
COPY backend/pyproject.toml /app/pyproject.toml
COPY backend/src /app/src
RUN python -m pip install --no-cache-dir ".[dev]"

RUN mkdir -p /data
ENV AGENTEVAL_DATABASE_URL=sqlite:////data/agenteval.db
ENV AGENTEVAL_TASKS_ROOT=/app/tasks
EXPOSE 8000
CMD ["uvicorn", "agenteval.api:app", "--host", "0.0.0.0", "--port", "8000"]
