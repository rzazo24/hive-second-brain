# Hive2nd Brain

Un "segundo cerebro" personal: tú aportas fuentes (artículos, notas, páginas web) y un agente de IA (Claude Code) las compila en un wiki de markdown estructurado y enlazado.

Este repositorio es **público** y contiene solo la estructura: las instrucciones del agente y la interfaz web. El contenido (fuentes y wiki) vive en un repositorio **privado** enlazado como submódulo en `data/`.

```
CLAUDE.md     Instrucciones del agente: ingesta, consulta, lint, convenciones
app/          Interfaz web (servidor Python sin dependencias + PWA)
data/         Submódulo privado
  raw/        Fuentes en bruto
  wiki/       Wiki generado: fuentes/, entidades/, conceptos/, sintesis/
  output/     Informes generados bajo petición
```

## Flujo

1. **Captura:** añade fuentes en `data/raw/` (a mano o desde la web).
2. **Ingesta:** pide al agente `ingiere lo nuevo de raw/`.
3. **Consulta:** navega el wiki desde la web o pregunta al agente.

## Interfaz web

```bash
python3 app/server.py          # http://127.0.0.1:8765
```

Solo escucha en localhost. Para usarla desde otros dispositivos, publícala en tu red privada, por ejemplo con `tailscale serve --bg 8765`. No tiene autenticación: no la expongas a internet.

Funciones: navegación por secciones, búsqueda (`Ctrl K`), formulario para añadir fuentes a `raw/`, tema claro/oscuro, interfaz específica para móvil e instalación como PWA con lectura sin conexión.

## Usar la plantilla con tu propio contenido

```bash
git clone https://github.com/rzazo24/hive-second-brain.git
cd hive-second-brain
# Sustituye el submódulo por tu propio repo privado con la estructura raw/ wiki/ output/
git submodule deinit -f data && git rm -f data
git submodule add https://github.com/<tu-usuario>/<tu-repo-privado>.git data
```
