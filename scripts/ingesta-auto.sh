#!/usr/bin/env bash
# Ingesta automática del Second Brain (lanzada por un timer de systemd).
# 1. Si no hay fuentes pendientes en data/raw/, termina sin llamar al agente.
# 2. Commitea las capturas nuevas de raw/ en el repo privado (papel de "proceso de captura").
# 3. Lanza Claude Code en modo no interactivo con permisos mínimos para ejecutar la INGESTA de CLAUDE.md.
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
# así que sin red, sin shell general y escritura solo en el wiki y en _procesado.md.
"$CLAUDE_BIN" -p "ingiere lo nuevo de raw/

Esta es una ejecución automática sin supervisión: sigue CLAUDE.md al pie de la letra, no hagas preguntas y termina con el resumen corto." \
  --permission-mode default \
  --allowedTools \
    "Read(CLAUDE.md)" "Read(data/**)" "Glob" "Grep" \
    "Edit(data/wiki/**)" "Write(data/wiki/**)" \
    "Edit(data/raw/_procesado.md)" "Write(data/raw/_procesado.md)" \
    "Bash(git -C data status:*)" "Bash(git -C data diff:*)" "Bash(git -C data log:*)" \
    "Bash(git -C data add:*)" "Bash(git -C data commit:*)" "Bash(git -C data push)" \
    "Bash(ls:*)" \
  --disallowedTools "WebFetch" "WebSearch" "Agent"
