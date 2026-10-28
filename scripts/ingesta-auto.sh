#!/usr/bin/env bash
# Ingesta automática del Second Brain (lanzada por un timer de systemd).
# 1. Si no hay fuentes pendientes en data/raw/, termina sin llamar al agente.
# 2. Commitea las capturas nuevas de raw/ en el repo privado (papel de "proceso de captura").
# 3. Lanza Claude Code en modo no interactivo con permisos mínimos para ejecutar la INGESTA de CLAUDE.md.
# 4. Commitea y sube el resultado (lo hace el script, así Claude no necesita permisos de git).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DATA="$ROOT/data"
CLAUDE_BIN="${CLAUDE_BIN:-$HOME/.local/bin/claude}"
cd "$ROOT"

# Evita dos ingestas a la vez
exec 9>"${XDG_RUNTIME_DIR:-/tmp}/hive-ingesta.lock"
flock -n 9 || { echo "Ya hay una ingesta en marcha"; exit 0; }

pending=()
for f in "$DATA"/raw/*.md; do
  [ -e "$f" ] || continue
  name="$(basename "$f")"
  [ "$name" = "_procesado.md" ] && continue
  grep -qF -- "$name" "$DATA/raw/_procesado.md" 2>/dev/null || pending+=("$name")
done

if [ ${#pending[@]} -eq 0 ]; then
  echo "Nada pendiente de ingerir"
  exit 0
fi
echo "Pendientes (${#pending[@]}): ${pending[*]}"

git -C "$DATA" add raw/
if ! git -C "$DATA" diff --cached --quiet; then
  git -C "$DATA" commit -q -m "captura: ${#pending[@]} fuente(s) pendiente(s) ($(date +%F))"
fi

# Permisos mínimos: el contenido de raw/ no es fiable (posible prompt injection),
# así que sin red, sin shell ni git, y escritura solo en el wiki y en _procesado.md
# (las reglas Edit(...) cubren todas las herramientas que escriben archivos).
"$CLAUDE_BIN" -p "ingiere lo nuevo de raw/

Esta es una ejecución automática sin supervisión: sigue CLAUDE.md al pie de la letra, no hagas preguntas y termina con el resumen corto.
No hagas commit ni push: el script que te lanza se encarga de git al terminar." \
  --permission-mode default \
  --allowedTools \
    "Read(CLAUDE.md)" "Read(data/**)" "Glob" "Grep" \
    "Edit(data/wiki/**)" "Edit(data/raw/_procesado.md)" \
  --disallowedTools "Bash" "WebFetch" "WebSearch" "Agent"

git -C "$DATA" add wiki/ raw/_procesado.md
if ! git -C "$DATA" diff --cached --quiet; then
  git -C "$DATA" commit -q -m "ingesta automática: ${#pending[@]} fuente(s) ($(date +%F))"
fi
git -C "$DATA" push -q || echo "AVISO: el push al repo privado ha fallado; los commits quedan en local"
