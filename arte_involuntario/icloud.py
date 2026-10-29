"""Miniaturas desde iCloud (solo macOS, opcional: `./arte analizar --traer-icloud`).

Para las fotos que no tienen NINGUNA imagen en el Mac, pide a Fotos (PhotoKit) una versión
reducida (~768 px, ~100 KB) en lugar del original. Se guarda en datos/miniaturas_icloud/.
Necesita que la Terminal tenga permiso en Ajustes → Privacidad y seguridad → Fotos («Acceso completo»).
"""
from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

from . import disco, rutas

KB_POR_MINIATURA = 150 * 1024
SEGUNDOS_POR_MINIATURA = 60      # si iCloud no la entrega en este tiempo, se salta
FALLOS_SEGUIDOS = 3              # cuelgues seguidos: iCloud no responde, dejar de pedir


def ruta_cache(uuid: str) -> Path:
    return rutas.MINIATURAS_ICLOUD / f"{uuid}.jpg"


def _autorizar(timeout: float = 120.0):
    import Photos

    nivel = Photos.PHAccessLevelReadWrite
    estado = Photos.PHPhotoLibrary.authorizationStatusForAccessLevel_(nivel)
    if estado == Photos.PHAuthorizationStatusNotDetermined:
        hecho = threading.Event()
        Photos.PHPhotoLibrary.requestAuthorizationForAccessLevel_handler_(nivel, lambda s: hecho.set())
        t0 = time.time()
        while not hecho.is_set() and time.time() - t0 < timeout:
            time.sleep(0.25)
        estado = Photos.PHPhotoLibrary.authorizationStatusForAccessLevel_(nivel)
    if estado != Photos.PHAuthorizationStatusAuthorized:
        raise RuntimeError(
            "Fotos no da acceso a la Terminal. Ajustes del Sistema → Privacidad y seguridad → Fotos → "
            "Terminal → «Acceso completo». (Usa la app Terminal de macOS.)"
        )


def traer(uuids: list[str], maximo: int | None = None) -> int:
    """Descarga miniaturas reducidas para `uuids`. Devuelve cuántas se han traído."""
    if sys.platform != "darwin":
        print("  (--traer-icloud solo funciona en macOS)")
        return 0
    pendientes = [u for u in uuids if not ruta_cache(u).exists()]
    if maximo:
        pendientes = pendientes[:maximo]
    if not pendientes:
        return 0
    rutas.MINIATURAS_ICLOUD.mkdir(parents=True, exist_ok=True)
    caben = max(0, (disco.libre(rutas.MINIATURAS_ICLOUD) - disco.MARGEN_MINIMO) // KB_POR_MINIATURA)
    if caben < len(pendientes):
        print(f"  ⚠ Solo hay espacio para {caben} de {len(pendientes)} miniaturas; traigo esas (las más recientes).")
        pendientes = pendientes[:caben]
        if not pendientes:
            return 0
    _autorizar()
    from .exportar_photokit import Caido, Colgado, Exportador

    print(f"· Pidiendo {len(pendientes)} miniaturas reducidas a iCloud (no se descargan originales)…")
    hechas = errores = seguidos = 0
    t0 = time.monotonic()
    try:
        # Cada petición va a un proceso aparte: si iCloud se cuelga con una foto, se mata ese
        # proceso y se sigue con la siguiente (y Ctrl+C siempre funciona).
        with Exportador() as ex:
            for k, u in enumerate(pendientes, 1):
                tmp = ruta_cache(u).with_suffix(".tmp.jpg")
                try:
                    ex.pedir("miniatura", u, tmp, SEGUNDOS_POR_MINIATURA, lado=768)
                    tmp.replace(ruta_cache(u))
                    hechas += 1
                    seguidos = 0
                except (Colgado, Caido) as e:
                    tmp.unlink(missing_ok=True)
                    seguidos += 1
                    print(f"\r  ! {u}: {e}" + " " * 20)
                    if seguidos >= FALLOS_SEGUIDOS:
                        print("  ⚠ iCloud no responde (¿sin internet?): dejo de pedir miniaturas.")
                        break
                except Exception as e:
                    tmp.unlink(missing_ok=True)
                    seguidos = 0  # Fotos contesta: es un problema de esta foto
                    errores += 1
                    if errores <= 3:
                        print(f"\r  ! {u}: {e}" + " " * 20)
                if k % 25 == 0:
                    print(f"\r  {k}/{len(pendientes)} · {k / (time.monotonic() - t0):.1f}/s   ", end="", flush=True)
    except KeyboardInterrupt:
        print("\n  Interrumpido: lo traído queda guardado.")
    if errores > 3:
        print(f"\n  ({errores} fotos no se pudieron traer)", end="")
    print(f"\n  {hechas} miniaturas traídas ({rutas.legible(rutas.tam_carpeta(rutas.MINIATURAS_ICLOUD))} en total).")
    return hechas
