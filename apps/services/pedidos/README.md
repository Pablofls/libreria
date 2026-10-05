# Microservicio de pedidos (puerto 5005)

Pedidos con lineas y control de stock (`sp_ajustar_stock`) en una sola transaccion. Estados: pendiente, pagado, enviado, cancelado.

Cabecera del codigo (`app.py`) lista las rutas. Todo en JSON.

## Seguridad (ejercicio guiado de servicios)

- JWT HS256 emitido por `apps/services/login` (20 min, claims `user_id` y
  `role_id`; admin = 1, lector = 2). Renovable con `POST /token/refresh`.
- `JWT_SECRET_KEY` por variable de entorno, el mismo valor en todos los
  servicios; sin el no arranca. Nunca en el codigo.
- Se verifica firma, algoritmo (fijo), expiracion, emisor y claims antes de
  tocar datos. **401** token ausente o invalido, **403** rol insuficiente.
- CORS: solo los origenes de `CORS_ORIGENES`; vacio = ninguno, nunca `*`.
- Sin contrasenas ni tokens en logs; errores sin SQL ni stack.
- HTTPS: se activa en el proxy (`deploy/nginx-library.conf`); mientras tanto
  el servicio habla HTTP.

## Local

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env     # completar DB_PASSWORD y JWT_SECRET_KEY
python3 app.py           # http://127.0.0.1:5005/health
python3 pruebas.py       # seguridad, sin base de datos
```

Despliegue en la VM: seccion "Microservicios Users, Authors, Pedidos y Pagos"
del README principal y `deploy/libreria-pedidos.service`.
