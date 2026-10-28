"""Vigilancia del espacio libre: la app nunca debe llenar el disco del Mac."""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

from . import rutas

# Margen que dejamos libre en operaciones grandes (descargas): macOS se vuelve inestable
# por debajo de unos pocos GB. Se puede cambiar con ARTE_MARGEN_GB.
MARGEN_MINIMO = int(float(os.environ.get("ARTE_MARGEN_GB", "2")) * 1024**3)
# Para escrituras pequeñas (el índice, los PDF) basta con algo menos.
MARGEN_PEQUENO = int(min(1.0, float(os.environ.get("ARTE_MARGEN_GB", "2"))) * 1024**3)


class SinEspacio(RuntimeError):
    pass


def _existente(ruta: Path | None) -> Path:
    p = Path(ruta or rutas.DATOS)
    while not p.exists() and p != p.parent:
        p = p.parent
    return p


def _libre_macos(p: Path) -> int | None:
    """Espacio «para uso importante», el que muestra Ajustes: incluye lo purgable (cachés de
    iCloud, instantáneas de Time Machine) que macOS libera solo cuando hace falta."""
    try:
        from Foundation import NSURL, NSURLVolumeAvailableCapacityForImportantUsageKey as clave

        res = NSURL.fileURLWithPath_(str(p)).resourceValuesForKeys_error_([clave], None)
        valores = res[0] if isinstance(res, tuple) else res
        v = valores.get(clave) if valores else None
        return int(v) if v else None
    except Exception:
        return None


def libre(ruta: Path | None = None) -> int:
    p = _existente(ruta)
    real = shutil.disk_usage(p).free
    if sys.platform == "darwin":
        importante = _libre_macos(p)
        if importante:
            return max(real, importante)
    return real


def comprobar(necesario: int, que: str, ruta: Path | None = None, margen: int | None = None) -> None:
    """Lanza SinEspacio si tras escribir `necesario` bytes quedaría menos del margen."""
    margen = MARGEN_MINIMO if margen is None else margen
    disponible = libre(ruta)
    if disponible - necesario < margen:
        falta = necesario + margen - disponible
        raise SinEspacio(
            f"No hay espacio suficiente para {que}: hacen falta ~{rutas.legible(necesario)} y quedan "
            f"{rutas.legible(disponible)} libres (además dejo siempre {rutas.legible(margen)} de margen para macOS). "
            f"Libera unos {rutas.legible(falta)}: vacía la Papelera, borra descargas o vídeos grandes, "
            "o mira Ajustes del Sistema → General → Almacenamiento."
        )


def cabe(necesario: int, ruta: Path | None = None, margen: int | None = None) -> bool:
    margen = MARGEN_MINIMO if margen is None else margen
    return libre(ruta) - necesario >= margen


def resumen() -> dict:
    return {
        "libre": libre(),
        "modelos": rutas.tam_carpeta(rutas.MODELOS),
        "base_datos": rutas.BD.stat().st_size if rutas.BD.exists() else 0,
        "originales": rutas.tam_carpeta(rutas.ORIGINALES),
        "miniaturas_icloud": rutas.tam_carpeta(rutas.MINIATURAS_ICLOUD),
        "salida": rutas.tam_carpeta(rutas.SALIDA),
    }
