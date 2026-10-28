"""Rutas del proyecto.

Todo lo que la app genera vive dentro de la carpeta del proyecto (datos/ y salida/),
así que para liberar espacio basta con `./arte limpiar` o borrar la carpeta entera.
"""
from __future__ import annotations

import os
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
DATOS = Path(os.environ.get("ARTE_DATOS", RAIZ / "datos")).expanduser()
SALIDA = Path(os.environ.get("ARTE_SALIDA", RAIZ / "salida")).expanduser()

MODELOS = DATOS / "modelos"              # pesos del modelo de visión (se descargan una vez)
BD = DATOS / "fototeca.sqlite"           # metadatos + vectores de cada foto (unos pocos MB)
SELECCION = DATOS / "seleccion.json"     # lo que eliges en la galería
ORIGINALES = DATOS / "originales"        # solo las fotos elegidas, a resolución completa
MINIATURAS_ICLOUD = DATOS / "miniaturas_icloud"  # miniaturas pedidas a iCloud (opcional)
TEXTOS_CACHE = DATOS / "textos"          # vectores de las frases de cada categoría

WEB = Path(__file__).resolve().parent / "web"
CONFIG_CATEGORIAS = Path(__file__).resolve().parent / "categorias.json"


def preparar() -> None:
    for d in (DATOS, SALIDA, MODELOS, ORIGINALES, TEXTOS_CACHE):
        d.mkdir(parents=True, exist_ok=True)
    # Los modelos de Hugging Face se guardan dentro del proyecto, no en ~/.cache
    os.environ.setdefault("HF_HOME", str(MODELOS))
    os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
    os.environ.setdefault("HF_HUB_VERBOSITY", "error")
    os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")


def tam_carpeta(p: Path) -> int:
    total = 0
    if not p.exists():
        return 0
    for f in p.rglob("*"):
        try:
            if f.is_file() and not f.is_symlink():
                total += f.stat().st_size
        except OSError:
            pass
    return total


def legible(n: float) -> str:
    for u in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1024 or u == "TB":
            return f"{n:.0f} {u}" if u in ("B", "KB") else f"{n:.1f} {u}"
        n /= 1024
    return f"{n:.1f} TB"
