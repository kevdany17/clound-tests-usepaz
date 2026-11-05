"""
simulate_htaccess.py
Simula la lógica de los .htaccess sin necesitar Apache corriendo.
Verifica qué URIs pasan o se bloquean según las reglas implementadas.
"""
import re

ROOT_HTACCESS_RULES = """
Reglas raíz:
  1. Bloquear dotfiles: patrón (^|/)\.
  2. Permitir si URI empieza con /app/
  3. Bloquear todo lo demás
"""

APP_HTACCESS_RULES = """
Reglas /app/:
  1. Bloquear dotfiles dentro de /app/
  2. Si URI termina en config.js Y Sec-Fetch-Dest NO es 'script' NI vacío → 403
"""

def root_htaccess(uri: str) -> int:
    """Devuelve 200 (allow) o 403 (deny) según .htaccess raíz."""
    # Regla 2: bloquear dotfiles (^|\/)\.
    if re.search(r'(^|\/)\\.', uri) or re.match(r'^/\\.', uri):
        return 403
    # Regla 3: permitir si empieza con /app/
    if uri.lower().startswith('/app/'):
        return 200
    # Regla 4: bloquear todo lo demás
    return 403

def app_htaccess(uri: str, sec_fetch_dest: str = "") -> int:
    """Devuelve 200 (allow) o 403 (deny) según .htaccess /app/."""
    # Regla: bloquear dotfiles dentro de /app/
    basename = uri.split('/')[-1]
    if basename.startswith('.'):
        return 403
    # Regla: proteger config.js de navegación directa
    if re.search(r'config\.js$', uri, re.IGNORECASE):
        if sec_fetch_dest and sec_fetch_dest.lower() != 'script':
            return 403
    return 200

def evaluate(uri: str, sec_fetch_dest: str = "") -> tuple[int, str]:
    """Evalúa ambas capas de .htaccess."""
    code = root_htaccess(uri)
    if code == 403:
        return 403, "BLOQUEADO por raíz"
    # Si llegamos aquí, la URI está bajo /app/ → aplicar reglas de /app/
    code2 = app_htaccess(uri, sec_fetch_dest)
    if code2 == 403:
        return 403, "BLOQUEADO por /app/.htaccess"
    return 200, "PERMITIDO"

TESTS = [
    # (descripción, uri, sec_fetch_dest, resultado_esperado)
    ("index.html en /app/",              "/app/index.html",  "",         200),
    ("config.js como <script>",          "/app/config.js",   "script",   200),
    ("config.js como <script> vacío",    "/app/config.js",   "",         200),
    ("app.js como <script>",             "/app/app.js",      "script",   200),
    ("config.js navegación directa",     "/app/config.js",   "document", 403),
    ("config.js fetch navigate",         "/app/config.js",   "navigate", 403),
    ("Raíz /",                           "/",                "",         403),
    ("/main.py",                         "/main.py",         "",         403),
    ("/.env",                            "/.env",            "",         403),
    ("/.htaccess",                       "/.htaccess",       "",         403),
    ("/docs/",                           "/docs/",           "",         403),
    ("/.git/config",                     "/.git/config",     "",         403),
    ("/pyproject.toml",                  "/pyproject.toml",  "",         403),
    ("Path traversal /app/../main.py",   "/app/../main.py",  "",         403),
]

print()
print("=" * 65)
print(" Simulación de reglas .htaccess")
print("=" * 65)

passed = 0
failed = 0

for desc, uri, sfd, expected in TESTS:
    code, reason = evaluate(uri, sfd)
    # Path traversal: normalizar URI antes de evaluar
    if '..' in uri:
        import posixpath
        normalized = posixpath.normpath(uri)
        code, reason = evaluate(normalized, sfd)

    status = "✅ PASS" if code == expected else "❌ FAIL"
    if code == expected:
        passed += 1
    else:
        failed += 1
    sfd_label = f" [Sec-Fetch-Dest: {sfd}]" if sfd else ""
    print(f"  {status} [{code}] {desc}{sfd_label}")
    if code != expected:
        print(f"         → esperado {expected}, obtenido {code} ({reason})")

print()
print(f"  Resultados: {passed} pasaron, {failed} fallaron")
print("=" * 65)
print()

