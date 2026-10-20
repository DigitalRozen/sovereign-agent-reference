FROM python:3.13.13-slim

RUN useradd --uid 10001 --create-home app
WORKDIR /app

COPY pyproject.toml ./
COPY scripted_llm ./scripted_llm
RUN pip install --no-cache-dir .

USER 10001
EXPOSE 8000
CMD ["uvicorn", "scripted_llm.app:app", "--host", "0.0.0.0", "--port", "8000"]
