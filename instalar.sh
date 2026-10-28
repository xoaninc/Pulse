#!/bin/bash
# Instala todo DENTRO de esta carpeta (.venv/ y .python/). Para desinstalar, borra la carpeta.
set -euo pipefail
cd "$(dirname "$0")"
DIR="$(pwd)"

echo "== Cazador de arte involuntario · instalación =="

# 1) Espacio libre: entorno (~1,2 GB) + modelo (~0,4 GB) + margen de 3 GB para que macOS respire
libre_kb=$(df -Pk "$DIR" | awk 'NR==2 {print $4}')
libre_gb=$(( libre_kb / 1024 / 1024 ))
echo "Espacio libre en el disco: ${libre_gb} GB"
if [ "$libre_kb" -lt $(( 5 * 1024 * 1024 )) ]; then
  echo "✗ Hacen falta unos 5 GB libres (2 GB para la app + margen de seguridad)."
  echo "  Libera espacio (Ajustes del Sistema → General → Almacenamiento) y vuelve a ejecutar ./instalar.sh"
  exit 1
fi

# 2) uv: gestor de Python rápido (no toca el Python del sistema)
export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
if ! command -v uv >/dev/null 2>&1; then
  echo "· Instalando uv (gestor de Python)…"
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
fi

# 3) Python 3.12 y librerías, todo dentro de la carpeta; la caché de descargas se borra al final
export UV_PYTHON_INSTALL_DIR="$DIR/.python"
export UV_CACHE_DIR="$DIR/.uv-cache"
export UV_LINK_MODE=copy
echo "· Creando el entorno (Python 3.12)…"
uv venv .venv --python 3.12 --quiet --allow-existing
echo "· Instalando librerías (PyTorch, CLIP, osxphotos…). Tarda unos minutos."
uv pip install --python .venv/bin/python -r requirements.txt
rm -rf "$DIR/.uv-cache"

# 4) Comprobación
.venv/bin/python - <<'PY'
import torch, open_clip, PIL, reportlab
mps = getattr(torch.backends, "mps", None)
print(f"✓ PyTorch {torch.__version__} · aceleración Apple (MPS): {'sí' if mps and mps.is_available() else 'no (irá por CPU)'}")
try:
    import osxphotos
    print(f"✓ osxphotos {osxphotos.__version__}")
except Exception as e:
    print(f"! osxphotos no disponible: {e}")
PY
chmod +x arte Empezar.command 2>/dev/null || true
du -sh .venv .python 2>/dev/null | sed 's/^/  ocupa: /'
echo
echo "Listo. Ahora:"
echo "  1) Da «Acceso total al disco» a la Terminal (lo explica el README)."
echo "  2) ./arte analizar"
echo "  3) ./arte galeria"
