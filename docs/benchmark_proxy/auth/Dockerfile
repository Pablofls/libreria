# Validador de JWT con el mismo stack que los servicios de la VM
# (Flask + PyJWT + gunicorn, 2 workers x 8 hilos como deploy/libreria-pedidos.service).
FROM python:3.12-slim
RUN pip install --no-cache-dir flask==3.0.3 pyjwt==2.9.0 gunicorn==23.0.0
WORKDIR /app
COPY validador.py .
CMD ["gunicorn", "--workers", "2", "--threads", "8", "--bind", "0.0.0.0:9000", "validador:app"]
