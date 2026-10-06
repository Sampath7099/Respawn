FROM python:3.12-slim
WORKDIR /srv/backend
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/ .
# ranker features are shared with training; the trained model is mounted at /srv/recsys/artifacts
COPY recsys/features.py /srv/recsys/features.py
# --proxy-headers: behind nginx, request.client.host becomes the real client IP (rate limits)
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8010", "--workers", "4", \
     "--proxy-headers", "--forwarded-allow-ips", "*"]
