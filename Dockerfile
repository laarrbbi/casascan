# CasaScan en un servidor (por ejemplo un VPS en España):
#   docker build -t casascan .
#   docker run -d -p 8000:8000 -e CASASCAN_PASSWORD=tu-clave -v casascan:/data casascan
# y abre http://IP-DEL-SERVIDOR:8000 (usuario cualquiera, contraseña la de CASASCAN_PASSWORD).
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt waitress curl_cffi
COPY casascan ./casascan
COPY config.example.yaml ./
ENV PYTHONPATH=/app
VOLUME /data
WORKDIR /data
EXPOSE 8000
CMD ["python", "-m", "casascan", "web", "--host", "0.0.0.0", "--puerto", "8000", "--no-abrir", "-c", "/data/config.yaml"]
