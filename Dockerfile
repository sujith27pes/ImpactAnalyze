FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && useradd --create-home impact
COPY studio ./studio
COPY examples ./examples
RUN mkdir -p /app/data && chown impact:impact /app/data
USER impact
EXPOSE 8080
CMD ["python", "-m", "uvicorn", "studio.api:app", "--host", "0.0.0.0", "--port", "8080"]
