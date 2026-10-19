# GPS en tiempo real (WebSockets)

Simulación de vehículos moviéndose por Monterrey. **Es independiente de la
plataforma de la librería**: sólo comparte el repositorio para pasarlo a la VM.

```
 GPSapp/gps_app.py ──ws──►  microservice (Flask, :5900)  ──ws──►  Map/index.html
 (1 proceso = 1 vehículo)   /ws/gps          /ws/map              (Leaflet + OSM)
```

| Carpeta | Qué es |
|---|---|
| `microservice/` | Flask + `flask-sock`. Recibe posiciones y las retransmite. También sirve el mapa en `/`. Puerto **5900** |
| `GPSapp/` | App simple en Python que simula un vehículo y manda lat/lon de Monterrey cada segundo |
| `Map/` | Página con el mapa que muestra todos los vehículos moviéndose |
| `deploy/` | Unidad de systemd del microservicio |

## Protocolo

**`/ws/gps`** (la app GPS envía, continuamente):

```json
{"id": "auto-1", "lat": 25.6866, "lon": -100.3161}
```

Se rechaza (respuesta `{"tipo":"error","mensaje":…}`) lo que no sea JSON válido,
no traiga `id` o salga de Monterrey (lat 25.50–25.85, lon −100.50…−100.15).
Al cerrarse la conexión, el vehículo desaparece del mapa.

**`/ws/map`** (la página recibe): `{"tipo":"snapshot","vehiculos":[…]}` al
conectar, luego `{"tipo":"posicion","id","lat","lon","ts"}` en cada
actualización y `{"tipo":"baja","id"}` cuando un vehículo se desconecta.

`GET /health` devuelve el número de vehículos y visores conectados.

## Despliegue en la VM

Un comando por bloque. Desde la raíz del repo clonado en la VM:

```bash
cd /opt/udem/libreria && git pull
```

```bash
cd gps/microservice && python3 -m venv .venv
```

```bash
.venv/bin/pip install -r requirements.txt
```

```bash
sudo restorecon -R /opt/udem/libreria/gps
```

```bash
sudo cp /opt/udem/libreria/gps/deploy/libreria-gps.service /etc/systemd/system/
```

```bash
sudo systemctl daemon-reload
```

```bash
sudo systemctl enable --now libreria-gps
```

Comprobar:

```bash
curl -s http://127.0.0.1:5900/health
```

### Abrir el puerto 5900

En `firewalld` de la VM:

```bash
sudo firewall-cmd --permanent --add-port=5900/tcp
```

```bash
sudo firewall-cmd --reload
```

Y en GCP (desde donde tengas `gcloud`), una regla de ingreso para `tcp:5900`:

```bash
gcloud compute firewall-rules create libreria-permitir-gps --allow=tcp:5900 --source-ranges=0.0.0.0/0
```

(Si prefieres limitarla a tu IP, cambia `--source-ranges`; recuerda que la tuya
cambia seguido.)

## Lanzar los vehículos

En la VM, con el venv de la app GPS:

```bash
cd /opt/udem/libreria/gps/GPSapp && python3 -m venv .venv
```

```bash
.venv/bin/pip install -r requirements.txt
```

Un vehículo por terminal (o con `&` para dejarlos en segundo plano):

```bash
.venv/bin/python gps_app.py --id auto-1
```

```bash
.venv/bin/python gps_app.py --id auto-2
```

```bash
.venv/bin/python gps_app.py --id auto-3
```

También pueden correr desde tu Mac apuntando a la VM:
`python gps_app.py --id auto-4 --url ws://<IP-DE-LA-VM>:5900/ws/gps`.
Opciones: `--intervalo` (segundos entre envíos, 1 por omisión).

## Ver el mapa

Abre `http://<IP-DE-LA-VM>:5900/` en el navegador. Cada vehículo aparece con su
etiqueta, color y estela; la lista lateral muestra sus coordenadas y al hacer
clic centra el mapa en él. Si el WebSocket se cae, la página reconecta sola.

## Notas

- Una sola instancia (`--workers 1`) porque las posiciones viven en memoria; los
  hilos de gunicorn atienden los WebSockets.
- El mapa carga Leaflet (unpkg) y los tiles de OpenStreetMap: el navegador que
  lo abra necesita internet.
- Sin HTTPS el tráfico va en claro; es una simulación sin datos sensibles. Tras
  un proxy con TLS la página usa `wss://` automáticamente.
