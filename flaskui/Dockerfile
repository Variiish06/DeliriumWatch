FROM python:3.11-slim

WORKDIR /app

# System deps for SHAP + matplotlib
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application (models, templates, static, code)
COPY . .

# Cloud Run listens on PORT env var
EXPOSE 8080
ENV PORT=8080

# Use gunicorn — 1 worker due to memory constraints of SHAP+models
CMD ["gunicorn", \
     "--bind", "0.0.0.0:8080", \
     "--workers", "1", \
     "--threads", "2", \
     "--timeout", "180", \
     "app:app"]
