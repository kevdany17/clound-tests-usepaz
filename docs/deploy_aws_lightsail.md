# Guía de Despliegue en AWS Lightsail con Nginx y Systemd

Esta guía detalla el dimensionamiento de recursos y el procedimiento técnico paso a paso para desplegar en producción el microservicio FastAPI ([main.py](file:///Users/kevdany17/Documents/Courses/given/usepaz/gestion_db/SendEmail/main.py)).

---

## 1. Dimensionamiento y Elección del Servidor (Capacity Planning)

FastAPI es un framework asíncrono (ASGI) basado en `Starlette` y `AnyIO`, caracterizado por su alta eficiencia en tareas de Entrada/Salida (I/O Bound), tales como el envío de correos vía SMTP o peticiones HTTP a APIs de terceros.

### A. Memoria RAM
La memoria necesaria se calcula sumando el consumo base del sistema y el de la aplicación:

$$\text{RAM Total} = \text{RAM}_{\text{OS}} + \text{RAM}_{\text{Nginx}} + (N_{\text{workers}} \times \text{RAM}_{\text{worker}}) + \text{Margen de Seguridad (25\%)}$$

* **Sistema Operativo (Ubuntu Minimal):** ~150 – 250 MB.
* **Nginx:** ~15 – 30 MB.
* **Worker Uvicorn (FastAPI):**
  * Consumo base: ~50 – 70 MB por worker.
  * En carga con librerías de emails y plantillas (Jinja2, aiosmtplib): ~90 – 130 MB por worker.
* **Ejemplo para 2 workers:**  
  $$200\text{ MB} + 25\text{ MB} + (2 \times 110\text{ MB}) = 445\text{ MB}$$
  Con margen de seguridad del 25%: **~560 MB**.

### B. Procesador (vCPU)
FastAPI gestiona la concurrencia asíncrona mediante un bucle de eventos (`asyncio` event loop).
* **Fórmula estándar para workers ASGI en producción:**
  $$\text{Workers} = (2 \times \text{vCPUs}) + 1$$
  *(Para 1 vCPU, 2 workers ofrecen redundancia y estabilidad sin saturar la CPU).*
* **Capacidad estimada:** 1 vCPU en Lightsail soporta entre **200 y 600 solicitudes por segundo (RPS)** para respuestas JSON estándar y delegación de tareas en segundo plano (`BackgroundTasks`).

### C. Almacenamiento en Disco (SSD)
* **Ubuntu Server Base:** ~3.0 – 4.5 GB.
* **Python, uv/virtualenv y librerías:** ~300 – 600 MB.
* **Espacio de Intercambio (Swapfile):** 1 – 2 GB (recomendado para prevenir fallos OOM).
* **Logs del sistema y Nginx:** ~1 – 2 GB (rotados con `logrotate`).
* **Total mínimo requerido:** **~8 – 10 GB**.

---

### Tabla Comparativa de Planes en AWS Lightsail

| Tipo de Carga | Plan Sugerido | Especificaciones | Costo Aprox. | Recomendación |
| :--- | :--- | :--- | :--- | :--- |
| **Pruebas / MVP** | **Básico** | 1 vCPU, 1 GB RAM, 40 GB SSD | ~$5 USD/mes | **Mínimo recomendado** para instalar paquetes y compilar sin bloqueos por memoria. |
| **Producción Media** | **Estándar** | 2 vCPU, 2 GB RAM, 60 GB SSD | ~$10 USD/mes | Recomendado para tráfico sostenido y múltiples workers redundantes. |

---

## 2. Paso a Paso del Despliegue

### Paso 1: Creación de la Instancia en AWS Lightsail
1. Inicia sesión en la [Consola de AWS Lightsail](https://lightsail.aws.amazon.com/).
2. Haz clic en **Create instance**.
3. Selecciona la plataforma **Linux/Unix** y en Blueprint selecciona **OS Only** > **Ubuntu 24.04 LTS** (o 22.04 LTS).
4. Elige el plan de **$5 USD/mes** (1 vCPU, 1 GB RAM).
5. Asigna una **IP Estática**:
   * Dirígete a la pestaña **Networking** de la instancia.
   * Haz clic en **Create static IP** y asígnala a tu instancia para que la IP pública no cambie tras reinicios.
6. En la pestaña **IPv4 Firewall**, abre las siguientes reglas de red:
   * **TCP 22** (SSH)
   * **TCP 80** (HTTP)
   * **TCP 443** (HTTPS)

---

### Paso 2: Preparación del Servidor
Conéctate mediante SSH y actualiza el sistema:

```bash
# 1. Actualización de paquetes
sudo apt update && sudo apt upgrade -y

# 2. Instalación de paquetes esenciales
sudo apt install -y python3-pip python3-venv nginx git curl ufw

# 3. Configuración de 1 GB de memoria Swap (protección contra OOM)
sudo fallocate -l 1G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab

# 4. Configurar el Firewall local UFW
sudo ufw allow 'Nginx Full'
sudo ufw allow OpenSSH
sudo ufw --force enable
```

---

### Paso 3: Clonar el Proyecto y Preparar el Entorno
```bash
# Crear directorio de la aplicación
sudo mkdir -p /var/www/sendemail
sudo chown -R $USER:$USER /var/www/sendemail
cd /var/www/sendemail

# Clonar el repositorio
git clone <URL_DE_TU_REPOSITORIO> .

# Crear y activar entorno virtual
python3 -m venv .venv
source .venv/bin/activate

# Instalar dependencias del proyecto
pip install --upgrade pip
pip install "fastapi[standard]" uvicorn gunicorn
```

---

### Paso 4: Configurar el Demonio con Systemd
Systemd asegura que la aplicación se inicie automáticamente tras un reinicio del servidor y se recupere automáticamente si ocurre un error fatal.

Crea el archivo de unidad del servicio:
```bash
sudo nano /etc/systemd/system/sendemail.service
```

Pega el siguiente contenido (asegúrate de que `User` coincida con tu usuario, habitualmente `ubuntu`):

```ini
[Unit]
Description=FastAPI SendEmail Daemon
After=network.target

[Service]
User=ubuntu
Group=www-data
WorkingDirectory=/var/www/sendemail
Environment="PATH=/var/www/sendemail/.venv/bin"
ExecStart=/var/www/sendemail/.venv/bin/gunicorn main:app \
    --workers 2 \
    --worker-class uvicorn.workers.UvicornWorker \
    --bind 127.0.0.1:8000 \
    --access-logfile /var/log/sendemail_access.log \
    --error-logfile /var/log/sendemail_error.log

Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Habilita e inicia el servicio:
```bash
sudo systemctl daemon-reload
sudo systemctl start sendemail
sudo systemctl enable sendemail

# Comprobar estado de ejecución
sudo systemctl status sendemail
```

---

### Paso 5: Configurar Nginx como Reverse Proxy
Crea el bloque de configuración del sitio:

```bash
sudo nano /etc/nginx/sites-available/sendemail
```

Pega la configuración:

```nginx
server {
    listen 80;
    server_name tu-dominio.com www.tu-dominio.com; # O la IP estática si aún no tienes dominio

    client_max_body_size 10M;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_cache_bypass $http_upgrade;

        proxy_connect_timeout 60s;
        proxy_send_timeout 60s;
        proxy_read_timeout 60s;
    }
}
```

Activa el sitio y recarga Nginx:
```bash
sudo ln -s /etc/nginx/sites-available/sendemail /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t
sudo systemctl reload nginx
```

---

### Paso 6: Configurar Certificado SSL Gratuito (HTTPS con Certbot)
Si cuentas con un dominio apuntando a la IP de Lightsail:

```bash
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d tu-dominio.com -d www.tu-dominio.com
```

Certbot configurará automáticamente la renovación periódica y redirigirá todo el tráfico HTTP al puerto HTTPS seguro.

---

### Paso 7: Verificación
Prueba el servicio desde cualquier máquina externa:
```bash
curl http://<TU_IP_O_DOMINIO>/health
# Respuesta esperada: {"message":"I am alive"}
```
