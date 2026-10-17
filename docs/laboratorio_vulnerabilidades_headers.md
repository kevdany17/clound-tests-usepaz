# Laboratorio Práctico: Vulnerabilidad de Encabezados HTTP (Uvicorn vs. Nginx)

Este documento acompaña al archivo [main.py](file:///Users/kevdany17/Documents/Courses/given/usepaz/gestion_db/SendEmail/main.py). Presenta un laboratorio práctico con **dos casos de vulnerabilidades reales** comunes en servicios de correo y autenticación:

1. **Host Header Poisoning** (Envenenamiento de enlaces de recuperación de contraseña - CWE-644).
2. **IP Spoofing vía X-Forwarded-For** (Bypass de listas blancas para envíos internos no autorizados - CWE-290).

---

## 1. Fundamento de las Vulnerabilidades

### Caso A: Envenenamiento de Enlace (Password Reset Poisoning)
* **El error común:** Cuando un usuario pide restablecer su contraseña, muchos desarrolladores construyen el enlace del correo dinámicamente leyendo el encabezado `Host` que envía el navegador del cliente:
  ```python
  domain = request.headers.get("host")
  reset_link = f"https://{domain}/auth/confirm-reset?token={token}"
  ```
* **El ataque:** Un atacante envía la solicitud de restablecimiento para la cuenta de la víctima (`victima@empresa.com`), pero manipula el encabezado HTTP: `Host: atacante-phishing.com`.
* **El impacto:** La víctima recibe un correo oficial y legítimo de la empresa, pero el botón *"Restablecer mi contraseña"* la redirige al servidor del atacante, entregándole el token secreto al hacer clic.

---

### Caso B: Suplantación de IP (IP Spoofing / CWE-290)
* **El error común:** Un microservicio interno permite envíos de correo masivos sin autenticación si la petición proviene de `127.0.0.1` o la Intranet. Para obtener la IP, el código hace:
  ```python
  client_ip = request.headers.get("x-forwarded-for") or request.client.host
  ```
* **El ataque:** Un atacante remoto desde Internet envía una petición agregando manualmente:
  `-H "X-Forwarded-For: 127.0.0.1"`.
* **El impacto:** El servidor de aplicaciones cree ciegamente que la petición nació internamente en el servidor local y ejecuta el envío privilegiado sin pedir credenciales.

---

## 2. Paso a Paso del Laboratorio

Asegúrate de tener instaladas las dependencias e inicia las pruebas en tu máquina o servidor Lightsail.

---

### FASE 1: Pruebas con Uvicorn Directo (Sin Nginx)

Inicia Uvicorn exponiéndolo en el puerto `8000`:
```bash
uvicorn main:app --host 0.0.0.0 --port 8000
```

Abre otra terminal y ejecuta las siguientes pruebas de ataque:

#### Prueba 1.1: Atacar el endpoint de Restablecimiento de Contraseña
```bash
curl -s -X POST http://localhost:8000/api/v1/auth/password-reset \
  -H "Content-Type: application/json" \
  -H "Host: atacante-phishing.com" \
  -d '{"email": "victima@empresa.com"}' | jq
```

**Resultado obtenido (Vulnerable):**
```json
{
  "status": "email_queued",
  "recipient": "victima@empresa.com",
  "email_preview": {
    "action_url": "https://atacante-phishing.com/auth/confirm-reset?token=9b2a7..."
  },
  "security_analysis": {
    "host_header_used": "atacante-phishing.com",
    "is_potentially_poisoned": true
  }
}
```
> ❌ **Fallo:** La aplicación generó el correo legítimo con la URL del atacante.

---

#### Prueba 1.2: Intentar Envío Masivo sin cabecera (Comportamiento normal)
```bash
curl -s -X POST http://localhost:8000/api/v1/internal/broadcast-email \
  -H "Content-Type: application/json" \
  -d '{"subject": "Aviso Urgente", "recipient_count": 5000, "message": "Texto"}' | jq
```
*(Si lo ejecutas desde una IP remota, responderá `403 Forbidden` porque tu IP no es `127.0.0.1`).*

---

#### Prueba 1.3: Atacar el Envío Masivo con IP Spoofing
Simula ser un atacante remoto falseando la cabecera `X-Forwarded-For`:
```bash
curl -s -X POST http://localhost:8000/api/v1/internal/broadcast-email \
  -H "Content-Type: application/json" \
  -H "X-Forwarded-For: 127.0.0.1" \
  -d '{"subject": "Spam no deseado", "recipient_count": 5000, "message": "Promoción maliciosa"}' | jq
```

**Resultado obtenido (Vulnerable):**
```json
{
  "status": "broadcast_started",
  "authorized_by_ip": "127.0.0.1",
  "spoofing_successful": true,
  "result": {
    "recipients_queued": 5000,
    "secret_smtp_relay_used": "smtp.internal.corp:587 (Privilegiado sin cuota)"
  }
}
```
> ❌ **Fallo:** Uvicorn confió en la cabecera arbitraria del cliente y autorizó el envío masivo.

---

### FASE 2: Pruebas con Nginx como Reverse Proxy

Ahora conecta Nginx delante de Uvicorn (con Uvicorn escuchando únicamente en `127.0.0.1:8000`).

La configuración de Nginx en `/etc/nginx/sites-available/sendemail` debe ser:

```nginx
server {
    listen 80;
    server_name tu-dominio.com; # Dominio legítimo esperado

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;

        # 1. Normaliza el Host con el nombre oficial del servidor
        proxy_set_header Host $host;

        # 2. PISA y descarta cualquier X-Real-IP enviada por el atacante
        proxy_set_header X-Real-IP $remote_addr;

        # 3. Agrega la IP real física de la conexión TCP a la cadena de proxies
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;

        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

Repite los ataques haciendo las peticiones al puerto público de **Nginx** (puerto `80`):

#### Prueba 2.1: Atacar el Restablecimiento de Contraseña a través de Nginx
```bash
curl -s -X POST http://<IP_O_DOMINIO>/api/v1/auth/password-reset \
  -H "Content-Type: application/json" \
  -H "Host: atacante-phishing.com" \
  -d '{"email": "victima@empresa.com"}' | jq
```

**Resultado obtenido (Protegido):**
* Nginx verifica que `Host: atacante-phishing.com` no corresponde con el bloque `server_name tu-dominio.com` y **descarta la petición** (HTTP 404/400).
* O bien, mediante `proxy_set_header Host $host;`, Nginx reemplaza el valor con el dominio legítimo antes de pasarlo a Python.
* La URL en el correo contendrá siempre el dominio seguro: `https://tu-dominio.com/...`.

---

#### Prueba 2.2: Atacar con IP Spoofing a través de Nginx
```bash
curl -s -X POST http://<IP_O_DOMINIO>/api/v1/internal/broadcast-email \
  -H "Content-Type: application/json" \
  -H "X-Forwarded-For: 127.0.0.1" \
  -d '{"subject": "Spam no deseado", "recipient_count": 5000, "message": "Hola"}' | jq
```

**Resultado obtenido (Protegido):**
```json
{
  "detail": {
    "error": "Acceso denegado: Este endpoint solo puede ser invocado desde la red interna.",
    "your_detected_ip": "<TU_IP_PUBLICA_REAL>",
    "tcp_socket_ip": "127.0.0.1"
  }
}
```
> 🛡️ **Protegido:** Nginx usó `$remote_addr` (la IP real del socket TCP entre el cliente y el servidor, imposible de alterar a nivel HTTP) y sobreescribió la cabecera. La aplicación detectó la IP pública real y bloqueó el acceso con **HTTP 403 Forbidden**.

---

## 3. Diagnóstico en Tiempo Real

Puedes inspeccionar qué cabeceras están llegando a tu aplicación y si estás protegido ejecutando:

```bash
curl -s http://<IP_O_DOMINIO>/api/v1/diagnostics/inspect-connection | jq
```

El JSON resultante te indicará:
* `"is_behind_local_reverse_proxy"`: `true` si la conexión la entrega Nginx localmente.
* `"actual_tcp_socket_remote_address"`: `127.0.0.1` cuando proviene del proxy Nginx.
* `"is_ip_spoofed"`: Alerta automática si hay una discrepancia sospechosa entre la IP física y las cabeceras declaradas.

---

## 4. Buenas Prácticas de Defensa en Profundidad (Python + Nginx)

Aunque Nginx actúa como escudo perimetral, la mejor práctica en DevOps y Seguridad es implementar **Defensa en Profundidad**:

1. **En Nginx:**  
   Nunca omitas `proxy_set_header X-Real-IP $remote_addr;`. Configura un bloque `server` por defecto que responda con código `444` (cerrar conexión) a peticiones con `Host` desconocido.
2. **En FastAPI:**  
   Agrega el middleware `TrustedHostMiddleware` en Python para rechazar solicitudes cuyo `Host` no esté en la lista blanca:
   ```python
   from fastapi.middleware.trustedhost import TrustedHostMiddleware

   app.add_middleware(
       TrustedHostMiddleware,
       allowed_hosts=["tu-dominio.com", "api.tu-dominio.com", "localhost"]
   )
   ```
3. **No utilices la IP del cliente para autorización crítica:**  
   Para endpoints privilegiados (como envíos masivos), utiliza autenticación fuerte (Tokens Bearer, API Keys con roles o mTLS) en lugar de depender únicamente de una lista blanca de direcciones IP.
