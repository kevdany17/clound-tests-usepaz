# Laboratorio Práctico: Ataques de Denegación de Servicio (DoS) y Mitigaciones en Nginx y FastAPI

En este laboratorio aprenderás a:

* **Generar un ataque DoS sencillo** contra una API FastAPI expuesta directamente con Uvicorn.
* **Detectar y mitigar** dicho ataque usando **Nginx como Reverse Proxy** y **middlewares de limitación** en FastAPI.
* Comparar **ventajas y desventajas** de cada capa de defensa.

---

## 1. ¿Qué es un DoS y por qué nos interesa?

* **DoS (Denial‑of‑Service)** es cualquier ataque que satura los recursos de un servidor (CPU, memoria, ancho de banda, sockets) impidiendo que usuarios legítimos accedan al servicio.
* En un entorno **micro‑servicio** (FastAPI + Uvicorn) el ataque puede manifestarse como:
  * **Saturación de workers** (todos los procesos `uvicorn` consumen CPU esperando I/O).
  * **Agotamiento de sockets** (el kernel alcanza el límite de conexiones concurrentes).
  * **Consumo de memoria** por buffers de petición grandes.
* **Nginx** se usa típicamente como *primer nivel* de defensa porque está escrito en C, es extremadamente eficiente y permite aplicar controles de **rate‑limit**, **conexiones simultáneas** y **timeout** antes de que la petición llegue a la aplicación.

---

## 2. Preparación del entorno

1. **Asegúrate de tener la aplicación FastAPI en ejecución** (sin Nginx) para observar el comportamiento vulnerable.
   ```bash
   uvicorn main:app --host 0.0.0.0 --port 8000
   ```
2. **Instala las dependencias para el script de ataque** (solo `requests` y `concurrent.futures`).
   ```bash
   python3 -m venv dos_env && source dos_env/bin/activate
   pip install requests
   ```
3. **Crea una carpeta `scripts/` dentro del proyecto** para guardar el script de generación de tráfico.

---

## 3. Script de generación DoS (Python)

Guarda el siguiente archivo como `scripts/dos_flood.py` (puedes usar `bash` o `ab` también, pero el script Python muestra claramente cómo se saturan los workers):

```python
#!/usr/bin/env python3
"""Simple DoS flood against a FastAPI endpoint.

- Lanza N peticiones concurrentes sin esperar respuesta.
- Cada petición hace un `GET /health` (muy liviano).
- Ajusta `CONCURRENCY` y `DURATION` para escalar la carga.
"""
import argparse
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests

URL = "http://127.0.0.1:8000/health"


def request_one(session: requests.Session):
    try:
        resp = session.get(URL, timeout=2)
        return resp.status_code
    except Exception as e:
        return f"error: {e}"


def run_flood(concurrency: int, duration: int):
    end_time = time.time() + duration
    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        with requests.Session() as session:
            futures = []
            while time.time() < end_time:
                # Lanzamos una petición sin bloquear (fire‑and‑forget)
                futures.append(executor.submit(request_one, session))
                # Opcional: limitar la velocidad de disparo
                # time.sleep(0.001)
            # Esperamos a que terminen todas (solo para reporte)
            results = [f.result() for f in as_completed(futures)]
            print(f"Total solicitudes enviadas: {len(results)}")
            print(f"Códigos de respuesta: {set(results)}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="DoS flood generator")
    parser.add_argument("-c", "--concurrency", type=int, default=200,
                        help="Número máximo de hilos concurrentes (workers)")
    parser.add_argument("-d", "--duration", type=int, default=30,
                        help="Duración de la prueba en segundos")
    args = parser.parse_args()
    print(f"Iniciando DoS: {args.concurrency} hilos por {args.duration}s")
    run_flood(args.concurrency, args.duration)
```

### Cómo ejecutarlo
```bash
python scripts/dos_flood.py --concurrency 500 --duration 60
```
> **Resultado esperado (Uvicorn sin protección):**
> * El número de respuestas exitosas (200) caerá rápidamente.
> * Verás errores de `connection reset` o `ReadTimeout`.
> * En la terminal raíz de Uvicorn observarás que los workers quedan saturados y aparecen mensajes como `Task exception was never retrieved`.

---

## 4. Mitigación con Nginx (Reverse Proxy)

### 4.1 Configuración básica de rate‑limit y conexiones
Añade (o modifica) el sitio `/etc/nginx/sites-available/sendemail`:

```nginx
server {
    listen 80;
    server_name tu-dominio.com;   # Cambia al dominio real o a la IP estática

    # ---- LÍMITES DE SOLICITUDES ----
    # Limita a 10 solicitudes por segundo por IP (burst permite 20 de golpe)
    limit_req_zone $binary_remote_addr zone=req_limit:10m rate=10r/s;
    limit_req   zone=req_limit burst=20 nodelay;

    # Limita el número de conexiones simultáneas por IP a 25
    limit_conn_zone $binary_remote_addr zone=conn_limit:10m;
    limit_conn   conn_limit 25;

    # Opcional: tiempo de espera de lectura (evita clients que envían datos lentamente)
    client_body_timeout 10s;
    client_header_timeout 10s;
    send_timeout 10s;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_buffering on;            # Nginx bufferiza la respuesta antes de enviarla
        proxy_buffers 8 16k;
        proxy_busy_buffers_size 32k;
    }
}
```

### 4.2 Paso a paso para probar la mitigación
1. **Recarga Nginx**:
   ```bash
   sudo nginx -t && sudo systemctl reload nginx
   ```
2. **Ejecuta de nuevo el script DoS** (ahora apuntando al puerto 80, sin `:8000`).
   ```bash
   python scripts/dos_flood.py --concurrency 500 --duration 60
   ```
3. **Observa la salida del script**: Verás muchos códigos `429` (Too Many Requests) y la tasa de respuestas “200” se mantendrá estable.
4. **Revisa los logs de Nginx** (`/var/log/nginx/access.log`) para confirmar que las peticiones fueron filtradas por `limit_req`/`limit_conn`.

---

## 5. Mitigación a nivel de FastAPI

Aunque Nginx es la primera línea de defensa, también puedes **defender la aplicación internamente**.

### 5.1 Middleware de Rate‑Limit con `slowapi`
Instala la biblioteca:
```bash
pip install slowapi[redis]
```
> *Requisito:* un backend de Redis para almacenar contadores. En pruebas locales puedes usar `redis-server`.

Añade al inicio de `main.py`:
```python
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from fastapi import Request, HTTPException
from starlette.responses import JSONResponse

limiter = Limiter(key_func=get_remote_address, default_limits=["10/minute"])
app.state.limiter = limiter
app.add_exception_handler(429, _rate_limit_exceeded_handler)

# Ejemplo de endpoint protegido
@app.get("/protected")
@limiter.limit("5/minute")
async def protected_endpoint(request: Request):
    return {"msg": "Este endpoint está limitado a 5 peticiones por minuto por IP"}
```

### 5.2 Ventajas / Desventajas
| Capa | Ventajas | Desventajas |
|------|----------|------------|
| **Nginx** | - Muy bajo consumo de CPU/memoria.<br>- Filtra tráfico antes de llegar a la app.<br>- Configuración sencilla con `limit_req`/`limit_conn`.<br>- Funciona también para otros protocolos (HTTP/2, websockets). | - Sólo controla por IP; ataques distribuidos (DDoS) pueden evadirlo.
| **FastAPI Middleware** | - Gran flexibilidad (puedes aplicar lógica basada en rutas, JWT, usuario, etc.).<br>- Evita que *cualquier* ruta (incluyendo websockets) se ejecute si supera límites.
| - Consume recursos de la propia aplicación (CPU y memoria) antes de que Nginx bloquee.<br>- Necesita un backend persistente (Redis, Memcached) para contadores distribuidos.

---

## 6. Paso a Paso Completo del Laboratorio

| Paso | Acción | Comando / Configuración | Resultado esperado |
|------|--------|-------------------------|--------------------|
| 1 | **Lanzar Uvicorn sin protección** | `uvicorn main:app --host 0.0.0.0 --port 8000` | API responde rápidamente a `/health`.
| 2 | **Ejecutar script DoS** | `python scripts/dos_flood.py --concurrency 500 --duration 30` | El número de respuestas `200` cae; Uvicorn muestra warnings de **workers saturados**.
| 3 | **Instalar y configurar Nginx** | Ver bloque de configuración en la sección 4.1 y recargar. | Nginx acepta peticiones y aplica `limit_req`/`limit_conn`.
| 4 | **Ejecutar DoS contra Nginx** | `python scripts/dos_flood.py --concurrency 500 --duration 30` (apuntar al puerto 80) | El script muestra mayor cantidad de códigos `429`. Los logs de Nginx indican peticiones limitadas.
| 5 | **Agregar middleware `slowapi`** | `pip install slowapi[redis]` y modificar `main.py` (sección 5.1). | Nuevos endpoints pueden limitarse de forma granular.
| 6 | **Re‑ejecutar DoS (directo a FastAPI con middleware)** | `uvicorn main:app --host 0.0.0.0 --port 8000` → script DoS → observar códigos `429` devueltos por FastAPI. | Se demuestra defensa en la propia app, aunque el proceso sigue consumiendo CPU.
| 7 | **Comparar métricas** | `top`, `htop`, `nginx -s reload`, logs de acceso. | Nginx mantiene bajo uso de CPU; FastAPI + middleware consume más.

---

## 7. Conclusiones y Buenas Prácticas

1. **Siempre emplea un Reverse Proxy (Nginx, HAProxy, Caddy)** como primera línea de defensa. Es el filtro más barato y eficaz contra ataques volumétricos.
2. **Combina capas:** Nginx para *rate‑limiting* global y FastAPI para *rate‑limiting específico* (por usuario, ruta o método).
3. **Monitorea** los sockets y la latencia con herramientas como `netstat`, `ss`, `htop` y los logs de Nginx.
4. **Ajusta los límites** según el tráfico esperado: un sitio con 100 rps legítimos necesita un límite mucho mayor que uno con 5 rps.
5. **Considera DDoS mitigación externa** (AWS Shield, Cloudflare) cuando el origen del ataque es distribuido y supera la capacidad de tu infraestructura.

---

## 8. Referencias rápidas
* **Nginx docs – limit_req:** https://nginx.org/en/docs/http/ngx_http_limit_req_module.html
* **SlowAPI – FastAPI rate limiting:** https://slowapi.readthedocs.io/en/latest/
* **OWASP – Denial of Service:** https://owasp.org/www-project-top-ten/ (CWE‑400)
* **RFC 7230 – HTTP/1.1 – Header field parsing:** https://tools.ietf.org/html/rfc7230

---

Con este laboratorio podrás experimentar con un ataque DoS real, observar su impacto y aplicar distintas estrategias de mitigación tanto a nivel de **Nginx** como de **FastAPI**.
