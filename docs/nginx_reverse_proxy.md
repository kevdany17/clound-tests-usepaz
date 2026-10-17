# Arquitectura de Nginx como Reverse Proxy y Seguridad en Python

Este documento explica los fundamentos de arquitectura web sobre por qué Python/FastAPI no se ejecuta directamente en Nginx, qué función cumple un **Reverse Proxy** y cómo protege tu aplicación frente a vulnerabilidades basadas en encabezados HTTP.

---

## 1. Servidor Web vs. Servidor de Aplicaciones

Para entender la arquitectura, es necesario distinguir los dos roles:

### A. Nginx (Servidor Web / Reverse Proxy)
* Está programado en **C**.
* Su propósito es procesar sockets de red a escala masiva, enrutar conexiones TCP/HTTP, cifrar y descifrar SSL/TLS y despachar archivos estáticos desde el disco con uso mínimo de memoria.
* **No contiene un intérprete de Python:** Nginx no entiende de tipos de datos, objetos, variables, ni la sintaxis de FastAPI (`async def`, `@app.get`).

### B. Uvicorn / Gunicorn (Servidor de Aplicación ASGI)
* Está programado en **Python y C** (usando librerías como `uvloop` y `httptools`).
* Proporciona la interfaz **ASGI** (Asynchronous Server Gateway Interface), comunicando la especificación del protocolo web con el código fuente en Python ([main.py](file:///Users/kevdany17/Documents/Courses/given/usepaz/gestion_db/SendEmail/main.py)).

> **Conclusión:** No es posible ejecutar el código de FastAPI "dentro" de Nginx porque Nginx no interpreta Python. Se requiere un servidor ASGI como Uvicorn para ejecutar la app, y Nginx actúa como intermediario.

---

## 2. ¿Qué es un Reverse Proxy?

* **Forward Proxy (Proxy convencional):** Se ubica del lado del cliente. Los usuarios de una red navegan a través de él para salir a Internet.
* **Reverse Proxy (Proxy inverso):** Se ubica del lado del servidor. Recibe todo el tráfico entrante de Internet en los puertos públicos estándar (`80` y `443`) y lo reenvía internamente al servidor de aplicación (`127.0.0.1:8000`).

```
[ Cliente / Internet ]
         │ (HTTP :80 / HTTPS :443)
         ▼
┌─────────────────────────────────┐
│       NGINX (Reverse Proxy)     │  <-- Puerto público
└─────────────────────────────────┘
         │ (Red local interna / Socket Unix)
         ▼
┌─────────────────────────────────┐
│    UVICORN (Servidor ASGI)      │  <-- Oculto en 127.0.0.1:8000
│     App FastAPI (main.py)       │
└─────────────────────────────────┘
```

---

## 3. Ventajas de colocar Nginx delante de Uvicorn

| Aspecto | Con Uvicorn Directo (Sin Nginx) | Con Nginx como Reverse Proxy |
| :--- | :--- | :--- |
| **Terminación SSL/TLS** | Consume CPU de Python descifrando cada paquete HTTPS. | Nginx maneja TLS en lenguaje C de forma ultrarrápida y se renueva solo con Certbot. |
| **Ataques de Conexión Lenta (Slowloris)** | Clientes con conexiones lentas retienen workers de Python ocupados por segundos. | Nginx almacena en búfer (Buffering) la petición y sólo se la pasa a Python cuando está completa. |
| **Mitigación de Spoofing** | Uvicorn acepta cualquier encabezado HTTP que el cliente envíe. | Nginx sobrescribe y sanitiza encabezados críticos como `X-Real-IP`. |
| **Múltiples Servicios** | Solo una aplicación puede ocupar el puerto 80 o 443 a la vez. | Nginx puede alojar múltiples dominios y APIs en el mismo servidor. |
| **Protección Perimetral** | Los errores y trazas de la aplicación quedan expuestos a Internet. | Nginx oculta la infraestructura interna y maneja páginas de error limpias. |

---

## 4. Análisis de la Configuración del Reverse Proxy

El bloque de configuración en Nginx define el comportamiento del proxy:

```nginx
location / {
    # 1. Dirección del servidor ASGI interno
    proxy_pass http://127.0.0.1:8000;

    # 2. Uso de HTTP/1.1 para mantener conexiones abiertas eficientes (Keep-Alive)
    proxy_http_version 1.1;

    # 3. Soporte para WebSockets y Upgrade de conexión
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection 'upgrade';

    # 4. Host legítimo recibido en la petición
    proxy_set_header Host $host;

    # 5. IP real del socket TCP del cliente externo (Sobreescribe intentos de spoofing)
    proxy_set_header X-Real-IP $remote_addr;

    # 6. Cadena de IPs acumuladas por proxies intermedios
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;

    # 7. Protocolo original (http o https) para que la app sepa si la conexión fue cifrada
    proxy_set_header X-Forwarded-Proto $scheme;

    # 8. Tiempos de espera para evitar conexiones colgadas
    proxy_connect_timeout 60s;
    proxy_send_timeout 60s;
    proxy_read_timeout 60s;
}
```

---

## 5. Ejercicio Práctico: Vulnerabilidad de Encabezados

En el archivo [main.py](file:///Users/kevdany17/Documents/Courses/given/usepaz/gestion_db/SendEmail/main.py) se encuentra el endpoint `/vulnerable/admin`, diseñado para evidenciar la diferencia entre exponer la app directamente o protegerla con Nginx.

El código simula un panel administrativo restringido exclusivamente a la IP local `127.0.0.1`, pero comete el error de **confiar ciegamente en el encabezado `X-Forwarded-For`** y generar enlaces con el encabezado **`Host`**:

```python
forwarded_for = request.headers.get("x-forwarded-for")
client_ip = forwarded_for.split(",")[0].strip() if forwarded_for else request.client.host
```

### Escenario A: Ataque conectando directo a Uvicorn (Sin Nginx)
Si Uvicorn se expone a Internet en el puerto 8000:
```bash
curl -i -H "X-Forwarded-For: 127.0.0.1" \
        -H "Host: atacante.com" \
        http://<IP_SERVIDOR>:8000/vulnerable/admin
```

* ❌ **Bypass de Seguridad:** Python lee el encabezado manipulado, asume que el cliente es `127.0.0.1`, y otorga acceso:
  ```json
  {
    "detected_client_ip": "127.0.0.1",
    "admin_access_granted": true,
    "secret_data": "CONFIDENCIAL_DATABASE_PASS_98765"
  }
  ```
* ❌ **Host Header Poisoning:** Genera enlaces apuntando al dominio del atacante (`https://atacante.com/...`).

---

### Escenario B: Conectando a través de Nginx como Reverse Proxy
Si la petición pasa por Nginx en el puerto 80:
```bash
curl -i -H "X-Forwarded-For: 127.0.0.1" \
        -H "Host: atacante.com" \
        http://<IP_SERVIDOR>/vulnerable/admin
```

* 🛡️ **Protección:** Nginx ejecuta:
  ```nginx
  proxy_set_header X-Real-IP $remote_addr;
  proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
  ```
  Nginx toma la IP real del socket TCP del cliente (`$remote_addr`) y reemplaza o anexa la IP verdadera, neutralizando el intento de suplantación.
* Si el encabezado `Host` no coincide con el `server_name` configurado, Nginx lo rechaza o normaliza con `$host`.
* **Resultado en la API:**
  ```json
  {
    "detected_client_ip": "<IP_REAL_DEL_CLIENTE>",
    "admin_access_granted": false,
    "secret_data": "ACCESO DENEGADO (IP no autorizada)"
  }
  ```
