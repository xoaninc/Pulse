#!/bin/bash
# Instala todo DENTRO de esta carpeta (.uv/, .python/, .venv/). Para desinstalar, borra la carpeta.
set -euo pipefail
cd "$(dirname "$0")"
DIR="$(pwd)"
trap 'echo; echo "✗ La instalación no ha terminado. Comprueba la conexión a internet y vuelve a ejecutar ./instalar.sh (aprovecha lo ya descargado)."' ERR

echo "== Cazador de arte involuntario · instalación =="

# 0) ¿Carpeta dentro de iCloud Drive? (Escritorio y Documentos suelen sincronizarse)
case "$DIR" in
  "$HOME/Documents"*|"$HOME/Desktop"*|"$HOME/Library/Mobile Documents"*)
    echo "⚠ Esta carpeta está en Escritorio/Documentos, que en muchos Mac se sincronizan con iCloud Drive."
    echo "  Subiría ~2 GB a tu iCloud y macOS podría quitar archivos del disco cuando falte espacio."
    echo "  Mejor muévela a tu carpeta de inicio y repite allí la instalación:"
    echo "      mv \"$DIR\" ~/arte-involuntario && cd ~/arte-involuntario && ./instalar.sh"
    read -r -p "  ¿Seguir aquí de todos modos? [s/N] " r || r=""
    case "$r" in s|S|si|sí|SI|Sí) ;; *) trap - ERR; exit 1 ;; esac
    ;;
esac

# 1) Espacio libre: entorno (~1,3 GB) + modelo (~0,4 GB) + margen para que macOS respire
libre_kb=$(df -Pk "$DIR" | awk 'NR==2 {print $4}')
if [ "$(uname)" = "Darwin" ]; then
  # Ajustes cuenta también el espacio «purgable» (cachés de iCloud, instantáneas) que macOS libera solo
  imp_kb=$(osascript -l JavaScript -e "ObjC.import('Foundation');
    var u = \$.NSURL.fileURLWithPath('$DIR'); var k = \$.NSURLVolumeAvailableCapacityForImportantUsageKey;
    var d = u.resourceValuesForKeysError(\$([k]), null); var v = d.objectForKey(k);
    v ? Math.floor(ObjC.unwrap(v) / 1024) : 0" 2>/dev/null || echo 0)
  case "$imp_kb" in ''|*[!0-9]*) imp_kb=0 ;; esac
  [ "$imp_kb" -gt "$libre_kb" ] && libre_kb=$imp_kb
fi
libre_gb=$(( libre_kb / 1024 / 1024 ))
echo "Espacio libre en el disco: ${libre_gb} GB"
minimo_gb=4
# ya instalada (actualización): solo se revisan las librerías, basta con mucho menos
[ -f .venv/.instalacion-ok ] && minimo_gb=1
if [ "$libre_kb" -lt $(( minimo_gb * 1024 * 1024 )) ]; then
  trap - ERR
  if [ "$minimo_gb" -eq 4 ]; then
    echo "✗ Hacen falta unos 4 GB libres (2 GB para la app + margen de seguridad)."
  else
    echo "✗ Queda menos de 1 GB libre: no sigo para no llenar el disco."
  fi
  echo "  Vacía la Papelera o borra descargas/vídeos grandes y vuelve a ejecutar ./instalar.sh"
  echo "  (Ajustes del Sistema → General → Almacenamiento te dice qué ocupa más)."
  exit 1
fi

# 2) uv: gestor de Python rápido. Si no lo tienes, se instala dentro de esta carpeta.
export PATH="$DIR/.uv:$HOME/.local/bin:$PATH"
if ! command -v uv >/dev/null 2>&1; then
  echo "· Descargando uv (gestor de Python, ~40 MB)…"
  curl -LsSf https://astral.sh/uv/install.sh | env UV_INSTALL_DIR="$DIR/.uv" UV_NO_MODIFY_PATH=1 INSTALLER_NO_MODIFY_PATH=1 sh >/dev/null
fi

# 3) Python 3.12 y librerías, todo dentro de la carpeta; la caché de descargas se borra al final
export UV_PYTHON_INSTALL_DIR="$DIR/.python"
export UV_CACHE_DIR="$DIR/.uv-cache"
rm -f .venv/.instalacion-ok
echo "· Creando el entorno (Python 3.12)…"
uv venv .venv --python 3.12 --quiet --allow-existing
echo "· Instalando librerías (PyTorch, CLIP, osxphotos…). Tarda unos minutos."
uv pip install --python .venv/bin/python -r requirements.txt
rm -rf "$DIR/.uv-cache"

# 4) Comprobación
.venv/bin/python - <<'PY'
import torch, open_clip, PIL, reportlab
mps = getattr(torch.backends, "mps", None)
print(f"✓ PyTorch {torch.__version__} · aceleración Apple (MPS): {'sí' if mps and mps.is_available() else 'no (irá por CPU, más lento)'}")
try:
    import osxphotos
    print(f"✓ osxphotos {osxphotos.__version__}")
except Exception as e:
    print(f"! osxphotos no disponible: {e}")
PY
chmod +x arte Empezar.command 2>/dev/null || true
# quitar la «cuarentena» de los archivos descargados para que el doble clic funcione
[ "$(uname)" = "Darwin" ] && xattr -dr com.apple.quarantine "$DIR" 2>/dev/null || true
touch .venv/.instalacion-ok
trap - ERR
du -sh .venv .python .uv 2>/dev/null | sed "s/^/  ocupa: /" || true
echo
echo "Listo. Ahora:"
echo "  1) Da «Acceso total al disco» a la Terminal (lo explica el README) y reabre la Terminal."
echo "  2) ./arte analizar"
echo "  3) ./arte galeria"
