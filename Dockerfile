FROM python:3.11-slim
WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY airq ./airq
RUN pip install --no-cache-dir ".[mqtt]"
ENTRYPOINT ["python", "-m", "airq"]
CMD ["run", "--mock", "--sink", "mqtt", "--sink", "influx"]
