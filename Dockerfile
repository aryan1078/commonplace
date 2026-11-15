# One image for every Python service; the command picks which one runs:
#   docker run <image> docnode --port 50051
#   docker run <image> gateway --docnodes docnode:50051 --assist assist:50061
FROM python:3.12-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY proto proto
COPY scripts scripts
RUN python scripts/gen_proto.py

COPY run.py .
COPY config config
COPY services services
COPY clients clients

ENTRYPOINT ["python", "run.py"]
