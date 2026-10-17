import uuid
from typing import Optional
from fastapi import FastAPI, Request, HTTPException, status
from pydantic import BaseModel, EmailStr
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(
    title="SendEmail Service - Laboratorio DevOps & Seguridad",
    description="Servicio de demostración para pruebas de Reverse Proxy (Nginx) y vulnerabilidades de encabezados.",
    version="1.1.0"
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],          # o ["*"] para permitir todos (solo pruebas)
    allow_credentials=False,
    allow_methods=["*"],            # GET, POST, PUT, DELETE, …
    allow_headers=["*"],            # Content-Type, Authorization, …
)
# ------------------------------------------------------------------------------
# MODELOS DE DATOS
# ------------------------------------------------------------------------------
class PasswordResetRequest(BaseModel):
    email: str

class BroadcastEmailRequest(BaseModel):
    subject: str
    recipient_count: int
    message: str


# ------------------------------------------------------------------------------
# HELPER DE IP (ANTIPATRÓN COMÚN EN PRODUCCIÓN)
# ------------------------------------------------------------------------------
def get_client_ip_vulnerable(request: Request) -> str:
    """
    ANTIPATRÓN DE SEGURIDAD (CWE-290):
    Confiar ciegamente en 'X-Forwarded-For' o 'X-Real-IP' sin validar si provienen
    de un Reverse Proxy de confianza local.
    """
    x_forwarded_for = request.headers.get("x-forwarded-for")
    if x_forwarded_for:
        # Toma la primera IP de la cadena declarada por el cliente
        return x_forwarded_for.split(",")[0].strip()
    
    x_real_ip = request.headers.get("x-real-ip")
    if x_real_ip:
        return x_real_ip.strip()
    
    return request.client.host if request.client else "unknown"


# ------------------------------------------------------------------------------
# ENDPOINTS PÚBLICOS ESTÁNDAR
# ------------------------------------------------------------------------------
@app.get("/")
async def root():
    return {
        "service": "SendEmail API",
        "status": "online",
        "documentation": "/docs"
    }

@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": "sendemail"}


# ------------------------------------------------------------------------------
# CASO 1: ENVENENAMIENTO DE ENLACE DE RESTABLECIMIENTO (HOST HEADER POISONING)
# ------------------------------------------------------------------------------
@app.post("/api/v1/auth/password-reset", status_code=status.HTTP_200_OK)
async def request_password_reset(payload: PasswordResetRequest, request: Request):
    """
    CASO REAL: Password Reset Link Poisoning (CWE-644 / CWE-601).
    
    En sistemas de envío de correo, cuando un usuario solicita recuperar su contraseña,
    el backend genera un token y construye un enlace de restablecimiento.
    
    Vulnerabilidad:
    Si la aplicación construye la URL usando el encabezado 'Host' enviado por el cliente:
    `domain = request.headers.get('host')`
    
    - En Uvicorn Directo: Un atacante envía `Host: evil-phishing.com`. El correo que recibe la víctima
      tendrá un enlace hacia el servidor del atacante, robando el token al hacer clic.
    - Con Nginx configurado: Nginx restringe el 'server_name' o sobreescribe 'Host $host' con el dominio legítimo.
    """
    token = str(uuid.uuid4())
    
    # ANTIPATRÓN: Leer directamente el Host del cliente
    untrusted_host = request.headers.get("host", "localhost:8000")
    
    # Construcción de la URL de recuperación que viajaría en el correo
    poisoned_reset_url = f"https://{untrusted_host}/auth/confirm-reset?token={token}"
    
    # Simulación del cuerpo del correo que se despacharía
    simulated_email_body = (
        f"Hola, recibimos una solicitud para restablecer tu contraseña.\n"
        f"Haz clic en el siguiente enlace para continuar:\n{poisoned_reset_url}\n"
        f"Si no solicitaste este cambio, ignora este mensaje."
    )
    
    return {
        "status": "email_queued",
        "recipient": payload.email,
        "token_generated": token,
        "email_preview": {
            "subject": "Restablecer tu contraseña",
            "body": simulated_email_body,
            "action_url": poisoned_reset_url
        },
        "security_analysis": {
            "host_header_used": untrusted_host,
            "is_potentially_poisoned": "evil" in untrusted_host or "attacker" in untrusted_host or "hacker" in untrusted_host,
            "warning": "Si 'host_header_used' no coincide con tu dominio oficial, el correo enviará a la víctima al sitio del atacante."
        }
    }


# ------------------------------------------------------------------------------
# CASO 2: BYPASS DE LISTA BLANCA DE IPS INTERNAS (IP SPOOFING)
# ------------------------------------------------------------------------------
@app.post("/api/v1/internal/broadcast-email")
async def internal_broadcast_email(payload: BroadcastEmailRequest, request: Request):
    """
    CASO REAL: Bypass de Acceso Interno por Suplantación de IP (CWE-290).
    
    Muchas empresas tienen endpoints de envío masivo o monitoreo protegidos
    únicamente por lista blanca de IPs (ej: solo la Intranet o Localhost pueden enviar masivos
    sin requerir API Key corporativa).
    
    Vulnerabilidad:
    - En Uvicorn Directo: El atacante envía `-H "X-Forwarded-For: 127.0.0.1"` y engaña a la aplicación.
    - Con Nginx: Nginx sanitiza la cabecera forzando `proxy_set_header X-Real-IP $remote_addr`, bloqueando el bypass.
    """
    client_ip = get_client_ip_vulnerable(request)
    socket_ip = request.client.host if request.client else "unknown"
    
    # Regla de seguridad: Solo localhost o la VPC interna pueden ejecutar este endpoint
    TRUSTED_INTERNAL_IPS = ["127.0.0.1", "localhost", "::1", "10.0.0.1"]
    
    if client_ip not in TRUSTED_INTERNAL_IPS:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": "Acceso denegado: Este endpoint solo puede ser invocado desde la red interna.",
                "your_detected_ip": client_ip,
                "tcp_socket_ip": socket_ip
            }
        )
    
    # Si la IP es falsificada con éxito, la operación se autoriza indebidamente:
    return {
        "status": "broadcast_started",
        "authorized_by_ip": client_ip,
        "tcp_socket_ip": socket_ip,
        "spoofing_successful": socket_ip != "127.0.0.1" and client_ip == "127.0.0.1",
        "result": {
            "recipients_queued": payload.recipient_count,
            "subject": payload.subject,
            "secret_smtp_relay_used": "smtp.internal.corp:587 (Privilegiado sin cuota)"
        },
        "security_warning": "¡ALERTA! Si spoofing_successful es true, un atacante remoto ejecutó un envío privilegiado falsificando la cabecera X-Forwarded-For."
    }


# ------------------------------------------------------------------------------
# DIAGNÓSTICO: INSPECCIÓN DE CABECERAS Y DETECCIÓN DE ENTORNO
# ------------------------------------------------------------------------------
@app.get("/api/v1/diagnostics/inspect-connection")
async def inspect_connection(request: Request):
    """
    Inspecciona detalladamente el origen de la conexión y muestra si el tráfico
    está pasando por un Reverse Proxy legítimo o está expuesto directamente.
    """
    socket_ip = request.client.host if request.client else "unknown"
    client_ip = get_client_ip_vulnerable(request)
    is_behind_reverse_proxy = socket_ip in ["127.0.0.1", "::1"]
    
    return {
        "architecture_diagnosis": {
            "is_behind_local_reverse_proxy": is_behind_reverse_proxy,
            "architecture_mode": "Protegido por Nginx (Reverse Proxy)" if is_behind_reverse_proxy else "¡PELIGRO! Uvicorn expuesto directamente a Internet",
        },
        "ip_analysis": {
            "client_ip_detected_by_app": client_ip,
            "actual_tcp_socket_remote_address": socket_ip,
            "is_ip_spoofed": socket_ip != "127.0.0.1" and client_ip in ["127.0.0.1", "localhost"]
        },
        "headers_received": dict(request.headers),
        "test_commands": {
            "test_spoofing": f"curl -X POST -H 'Content-Type: application/json' -H 'X-Forwarded-For: 127.0.0.1' -d '{{\"subject\": \"Spam Masivo\", \"recipient_count\": 5000, \"message\": \"Hola\"}}' http://<TU_HOST>/api/v1/internal/broadcast-email",
            "test_host_poisoning": f"curl -X POST -H 'Content-Type: application/json' -H 'Host: atacante-phishing.com' -d '{{\"email\": \"victima@empresa.com\"}}' http://<TU_HOST>/api/v1/auth/password-reset"
        }
    }