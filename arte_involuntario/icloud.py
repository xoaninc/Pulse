"""Miniaturas desde iCloud (solo macOS, opcional: `./arte analizar --traer-icloud`).

Para las fotos que no tienen NINGUNA imagen en el Mac, pide a Fotos (PhotoKit) una versión
reducida (~768 px, ~100 KB) en lugar del original. Se guarda en datos/miniaturas_icloud/.
Necesita que la Terminal tenga permiso en Ajustes → Privacidad y seguridad → Fotos («Acceso completo»).
"""
from __future__ import annotations

import threading
import time
from pathlib import Path

from . import disco, rutas

KB_POR_MINIATURA = 150 * 1024


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


def _guardar_reducida(asset, destino: Path, lado: int = 768, calidad: float = 0.82) -> None:
    import objc
    import Photos
    import Quartz
    from Foundation import NSURL

    op = Photos.PHImageRequestOptions.alloc().init()
    op.setSynchronous_(True)
    op.setDeliveryMode_(Photos.PHImageRequestOptionsDeliveryModeHighQualityFormat)
    op.setResizeMode_(Photos.PHImageRequestOptionsResizeModeExact)
    op.setVersion_(Photos.PHImageRequestOptionsVersionCurrent)
    op.setNetworkAccessAllowed_(True)
    res: dict = {}

    def recibir(imagen, info):
        res["im"], res["info"] = imagen, dict(info or {})

    with objc.autorelease_pool():
        Photos.PHImageManager.defaultManager().requestImageForAsset_targetSize_contentMode_options_resultHandler_(
            asset, (float(lado), float(lado)), Photos.PHImageContentModeAspectFit, op, recibir)
        im = res.get("im")
        if im is None:
            raise RuntimeError(str(res.get("info", {}).get("PHImageErrorKey") or "sin imagen"))
        cg, _ = im.CGImageForProposedRect_context_hints_(None, None, None)
        url = NSURL.fileURLWithPath_(str(destino))
        dst = Quartz.CGImageDestinationCreateWithURL(url, "public.jpeg", 1, None)
        Quartz.CGImageDestinationAddImage(dst, cg, {Quartz.kCGImageDestinationLossyCompressionQuality: calidad})
        if not Quartz.CGImageDestinationFinalize(dst):
            raise RuntimeError("no se pudo escribir la miniatura")


def traer(uuids: list[str], maximo: int | None = None) -> int:
    """Descarga miniaturas reducidas para `uuids`. Devuelve cuántas se han traído."""
    import sys

    if sys.platform != "darwin":
        print("  (--traer-icloud solo funciona en macOS)")
        return 0
    pendientes = [u for u in uuids if not ruta_cache(u).exists()]
    if maximo:
        pendientes = pendientes[:maximo]
    if not pendientes:
        return 0
    rutas.MINIATURAS_ICLOUD.mkdir(parents=True, exist_ok=True)
    disco.comprobar(KB_POR_MINIATURA * len(pendientes), f"traer {len(pendientes)} miniaturas de iCloud", rutas.MINIATURAS_ICLOUD)
    _autorizar()
    import Photos

    print(f"· Pidiendo {len(pendientes)} miniaturas reducidas a iCloud (no se descargan originales)…")
    ids = [f"{u}/L0/001" for u in pendientes]
    activos = {}
    r = Photos.PHAsset.fetchAssetsWithLocalIdentifiers_options_(ids, None)
    for i in range(r.count()):
        a = r.objectAtIndex_(i)
        activos[str(a.localIdentifier()).split("/")[0]] = a
    hechas = 0
    t0 = time.time()
    try:
        for k, u in enumerate(pendientes, 1):
            a = activos.get(u)
            if a is None:
                continue
            tmp = ruta_cache(u).with_suffix(".tmp.jpg")
            try:
                _guardar_reducida(a, tmp)
                tmp.replace(ruta_cache(u))
                hechas += 1
            except Exception as e:
                tmp.unlink(missing_ok=True)
                if k <= 3:
                    print(f"  ! {u}: {e}")
            if k % 25 == 0:
                print(f"\r  {k}/{len(pendientes)} · {k / (time.time() - t0):.1f}/s   ", end="", flush=True)
    except KeyboardInterrupt:
        print("\n  Interrumpido: lo traído queda guardado.")
    print(f"\n  {hechas} miniaturas traídas ({rutas.legible(rutas.tam_carpeta(rutas.MINIATURAS_ICLOUD))} en total).")
    return hechas
