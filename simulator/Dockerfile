FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1
WORKDIR /app
RUN pip install --no-cache-dir confluent-kafka==2.6.1
COPY *.py ./
CMD ["python", "simulator.py"]
