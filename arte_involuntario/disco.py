"""Vigilancia del espacio libre: la app nunca debe llenar el disco del Mac."""
from __future__ import annotations

import shutil
from pathlib import Path

from . import rutas

# Margen que siempre dejamos libre (macOS se vuelve inestable por debajo de unos pocos GB).
MARGEN_MINIMO = 3 * 1024**3


class SinEspacio(RuntimeError):
    pass


def libre(ruta: Path | None = None) -> int:
    ruta = ruta or rutas.DATOS
    p = Path(ruta)
    while not p.exists() and p != p.parent:
        p = p.parent
    return shutil.disk_usage(p).free


def comprobar(necesario: int, que: str, ruta: Path | None = None) -> None:
    """Lanza SinEspacio si tras escribir `necesario` bytes quedaría menos del margen."""
    disponible = libre(ruta)
    if disponible - necesario < MARGEN_MINIMO:
        raise SinEspacio(
            f"No hay espacio suficiente para {que}: hacen falta ~{rutas.legible(necesario)} "
            f"y quedan {rutas.legible(disponible)} libres (dejamos siempre {rutas.legible(MARGEN_MINIMO)} de margen). "
            "Libera espacio o ejecuta `./arte limpiar`."
        )


def resumen() -> dict:
    return {
        "libre": libre(),
        "modelos": rutas.tam_carpeta(rutas.MODELOS),
        "base_datos": rutas.BD.stat().st_size if rutas.BD.exists() else 0,
        "originales": rutas.tam_carpeta(rutas.ORIGINALES),
        "miniaturas_icloud": rutas.tam_carpeta(rutas.MINIATURAS_ICLOUD),
        "salida": rutas.tam_carpeta(rutas.SALIDA),
    }
