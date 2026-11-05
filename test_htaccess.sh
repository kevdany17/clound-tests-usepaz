#!/usr/bin/env bash
# =============================================================
# test_htaccess.sh — Verifica las reglas de .htaccess
#
# USO: bash test_htaccess.sh [BASE_URL]
#   BASE_URL por defecto: http://localhost  (Apache sirviendo la raíz del proyecto)
# =============================================================

BASE="${1:-http://localhost}"
PASS=0
FAIL=0

check() {
    local desc="$1"
    local expected_code="$2"
    local url="$3"
    shift 3
    local extra_args=("$@")

    actual=$(curl -s -o /dev/null -w "%{http_code}" "${extra_args[@]}" "$url")

    if [ "$actual" = "$expected_code" ]; then
        echo "  ✅ PASS [$actual] — $desc"
        ((PASS++))
    else
        echo "  ❌ FAIL [got $actual, want $expected_code] — $desc"
        ((FAIL++))
    fi
}

echo ""
echo "============================================================"
echo " Test suite: .htaccess — Bloqueo fuera de /app/"
echo " Base URL: $BASE"
echo "============================================================"
echo ""

echo "── [A] Accesos que deben estar PERMITIDOS (200) ───────────"
check "index.html en /app/"               200  "$BASE/app/index.html"
check "config.js cargado como <script>"   200  "$BASE/app/config.js" \
    -H "Sec-Fetch-Dest: script" \
    -H "Sec-Fetch-Mode: no-cors"
check "app.js cargado como <script>"      200  "$BASE/app/app.js" \
    -H "Sec-Fetch-Dest: script" \
    -H "Sec-Fetch-Mode: no-cors"

echo ""
echo "── [B] Accesos que deben estar BLOQUEADOS (403) ───────────"
check "Raíz / bloqueada"                  403  "$BASE/"
check "/main.py bloqueado"               403  "$BASE/main.py"
check "/.env bloqueado"                  403  "$BASE/.env"
check "/.htaccess bloqueado"             403  "$BASE/.htaccess"
check "/docs/ bloqueado"                 403  "$BASE/docs/"
check "/.git/ bloqueado"                 403  "$BASE/.git/"
check "/pyproject.toml bloqueado"        403  "$BASE/pyproject.toml"

echo ""
echo "── [C] Protección de config.js: navegación directa ────────"
check "config.js navegación directa (Sec-Fetch-Dest: document) → 403" \
    403 "$BASE/app/config.js" \
    -H "Sec-Fetch-Dest: document" \
    -H "Sec-Fetch-Mode: navigate"

echo ""
echo "── [D] Traversal / paths maliciosos ───────────────────────"
check "Path traversal /app/../main.py"   403  "$BASE/app/../main.py"
check "URL encoded /%2e%2e/main.py"      403  "$BASE/%2e%2e/main.py"

echo ""
echo "============================================================"
echo " Resultados: $PASS pasaron, $FAIL fallaron"
echo "============================================================"
echo ""

[ "$FAIL" -eq 0 ] && exit 0 || exit 1

