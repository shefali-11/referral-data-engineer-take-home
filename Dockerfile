FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY your_script.py .
COPY data ./data

RUN mkdir -p /app/output /app/profiling

CMD ["python", "your_script.py", "--input-dir", "data", "--output-dir", "output", "--profiling-dir", "profiling"]
