"""PhotoKit en un proceso aparte (solo macOS): originales y miniaturas de iCloud.

Cada petición a Fotos se hace en un proceso hijo, no en un hilo, porque:
 - una descarga de iCloud puede quedarse colgada para siempre; un hilo no se puede matar
   (y uno normal impide que Python termine), un proceso sí;
 - osxphotos redirige los descriptores 1 y 2 de TODO el proceso mientras exporta (wurlitzer):
   si se cuelga dentro, se traga todo lo que la app imprima después;
 - el hijo trabaja en su hilo principal y pide siempre la foto fija, nunca la Live Photo
   (LivePhotoAsset necesita el run loop del hilo principal y además baja el vídeo .mov).

Un solo hijo sirve todas las fotos de una tanda; si se cuelga o se cae, se mata y se arranca
otro para las siguientes. Protocolo, una línea JSON por petición y otra por respuesta:
  padre → hijo   {"op": "original" | "miniatura", "uuid": …, "destino": …}
  hijo → padre   @@{"uuid": …, "ok": true, "ruta": …}   o   @@{"uuid": …, "ok": false, "error": …}
Las líneas sin la marca se ignoran (ruido de PhotoKit u osxphotos).
"""
from __future__ import annotations

import atexit
import json
import os
import queue
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

MARCA = "@@"
_RAIZ = Path(__file__).resolve().parent.parent
_VIVOS: set = set()   # hijos abiertos: se matan al salir de Python pase lo que pase
_saliendo = False


class Colgado(RuntimeError):
    """Fotos no contestó a tiempo (el proceso hijo ya se ha matado)."""


class Caido(RuntimeError):
    """El proceso hijo terminó de golpe (un fallo dentro de PhotoKit)."""


# ---------------------------------------------------------------------- lado de la app (padre)
class Exportador:
    """Habla con el proceso hijo. Úsalo con `with` para que el hijo se cierre siempre (también con Ctrl+C)."""

    def __init__(self):
        self._proc: subprocess.Popen | None = None
        self._cola: queue.Queue | None = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.cerrar()

    def _arrancar(self) -> None:
        if _saliendo:
            raise Caido("la app se está cerrando")
        codigo = (f"import sys; sys.path.insert(0, {str(_RAIZ)!r}); "
                  "from arte_involuntario.exportar_photokit import hijo; hijo()")
        try:
            p = subprocess.Popen(
                [sys.executable, "-c", codigo], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL, text=True, encoding="utf-8", errors="replace", bufsize=1)
        except OSError as e:
            raise Caido(f"no se pudo abrir el proceso que habla con Fotos ({e})")
        _VIVOS.add(p)
        self._proc, self._cola = p, queue.Queue()
        # el lector es «daemon»: nunca impide que Python termine
        threading.Thread(target=_leer, args=(p.stdout, self._cola), daemon=True).start()

    def pedir(self, op: str, uuid: str, destino, timeout: float, **extra) -> str:
        """Hace una petición y devuelve la ruta escrita. Lanza Colgado, Caido o RuntimeError (error de Fotos)."""
        if self._proc is None or self._proc.poll() is not None:
            self.cerrar()
            self._arrancar()
        peticion = json.dumps({"op": op, "uuid": uuid, "destino": os.path.abspath(destino), **extra})
        try:
            self._proc.stdin.write(peticion + "\n")
            self._proc.stdin.flush()
        except (OSError, ValueError):
            self.cerrar()
            raise Caido("Fotos se cerró de golpe")
        limite = time.monotonic() + timeout
        while True:
            resto = limite - time.monotonic()
            if resto <= 0:
                self.cerrar()  # lo atascado muere con el hijo; la siguiente foto arranca otro
                raise Colgado(f"Fotos no contesta en {timeout:.0f} s")
            try:
                # a trozos cortos: así Ctrl+C se atiende enseguida (en macOS una espera larga no se interrumpe)
                r = self._cola.get(timeout=min(resto, 0.5))
            except queue.Empty:
                continue
            if r is None:
                self.cerrar()
                raise Caido("Fotos se cerró de golpe")
            if r.get("uuid") != uuid:
                continue
            if r.get("ok"):
                return str(r["ruta"])
            raise RuntimeError(r.get("error") or "Fotos no devolvió la imagen")

    def cerrar(self) -> None:
        p, self._proc = self._proc, None
        if p is not None:
            _matar(p)


def _leer(salida, cola: queue.Queue) -> None:
    """Pasa a la cola solo las respuestas marcadas; None = el hijo ha terminado."""
    try:
        for linea in salida:
            if not linea.startswith(MARCA):
                continue
            try:
                r = json.loads(linea[len(MARCA):])
            except ValueError:
                continue
            if isinstance(r, dict):
                cola.put(r)
    except (OSError, ValueError):
        pass
    finally:
        cola.put(None)
        try:
            salida.close()
        except Exception:
            pass


def _matar(p: subprocess.Popen) -> None:
    _VIVOS.discard(p)
    try:
        if p.poll() is None:
            p.kill()
        p.wait(timeout=5)  # recoge al hijo: no quedan zombis
    except Exception:
        pass
    try:
        p.stdin.close()
    except Exception:
        pass


@atexit.register
def _matar_vivos() -> None:
    global _saliendo
    _saliendo = True
    for p in list(_VIVOS):
        _matar(p)


# ---------------------------------------------------------------------- lado de Fotos (hijo)
def hijo() -> None:
    # Las respuestas van por una copia privada de la salida; el descriptor 1 apunta a /dev/null,
    # así lo que impriman PhotoKit u osxphotos nunca se mezcla con ellas.
    canal = os.fdopen(os.dup(1), "w", encoding="utf-8", buffering=1)
    nulo = os.open(os.devnull, os.O_WRONLY)
    os.dup2(nulo, 1)
    signal.signal(signal.SIGINT, signal.SIG_IGN)  # Ctrl+C lo gestiona la app, que nos mata
    threading.Thread(target=_vigilar_padre, args=(os.getppid(),), daemon=True).start()
    operaciones = {"original": _original, "miniatura": _miniatura}
    for linea in sys.stdin:
        try:
            p = json.loads(linea)
        except ValueError:
            continue
        r = {"uuid": p.get("uuid")}
        try:
            r.update(ok=True, ruta=str(operaciones[p["op"]](p)))
        except Exception as e:
            r.update(ok=False, error=_texto_error(e))
        canal.write(MARCA + json.dumps(r) + "\n")
        canal.flush()


def _vigilar_padre(padre: int) -> None:
    """Si la app muere sin cerrarnos (p. ej. kill -9), no seguir vivos."""
    while True:
        time.sleep(2)
        if os.getppid() != padre:
            os._exit(0)


def _texto_error(e: Exception) -> str:
    t = " ".join(str(e).split()) or type(e).__name__
    return t if len(t) <= 200 else t[:197] + "…"


_biblioteca = None


def _original(p: dict) -> str:
    """Versión actual (con tus ediciones) como foto fija, en la carpeta p["destino"]."""
    global _biblioteca
    from osxphotos.photokit import PHOTOS_VERSION_CURRENT, PhotoAsset, PhotoLibrary

    if _biblioteca is None:
        _biblioteca = PhotoLibrary()
    uuid = p["uuid"]
    for ident in (uuid, f"{uuid}/L0/001"):
        try:
            phasset = _biblioteca.fetch_uuid(ident).phasset
            break
        except Exception:
            continue
    else:
        raise RuntimeError("Fotos no encuentra esta foto (¿se ha borrado?)")
    # PhotoAsset aunque sea una Live Photo (fetch_uuid daría LivePhotoAsset): pide la imagen con
    # setSynchronous_(True), sin run loop, y no baja el vídeo
    activo = PhotoAsset(_biblioteca._phimagemanager, phasset)
    if not activo.isphoto:
        raise RuntimeError("no es una foto")
    nombre = activo.original_filename or f"{uuid}.jpg"
    rutas_ = activo.export(p["destino"], filename=str(nombre), version=PHOTOS_VERSION_CURRENT, overwrite=True)
    if not rutas_:
        raise RuntimeError("Fotos no devolvió la imagen")
    return rutas_[0]


def _miniatura(p: dict) -> str:
    """Versión reducida (~768 px, JPEG) en el fichero p["destino"], sin bajar el original."""
    import objc
    import Photos
    import Quartz
    from Foundation import NSURL

    lado = float(p.get("lado") or 768)
    calidad = float(p.get("calidad") or 0.82)
    with objc.autorelease_pool():
        encontrados = Photos.PHAsset.fetchAssetsWithLocalIdentifiers_options_([f"{p['uuid']}/L0/001"], None)
        if encontrados is None or encontrados.count() == 0:
            raise RuntimeError("Fotos no encuentra esta foto")
        asset = encontrados.objectAtIndex_(0)
        op = Photos.PHImageRequestOptions.alloc().init()
        op.setSynchronous_(True)  # el manejador se llama en este mismo hilo: no hace falta run loop
        op.setDeliveryMode_(Photos.PHImageRequestOptionsDeliveryModeHighQualityFormat)
        op.setResizeMode_(Photos.PHImageRequestOptionsResizeModeExact)
        op.setVersion_(Photos.PHImageRequestOptionsVersionCurrent)
        op.setNetworkAccessAllowed_(True)
        res: dict = {}

        def recibir(imagen, info):
            res["im"], res["info"] = imagen, dict(info or {})

        Photos.PHImageManager.defaultManager().requestImageForAsset_targetSize_contentMode_options_resultHandler_(
            asset, (lado, lado), Photos.PHImageContentModeAspectFit, op, recibir)
        im = res.get("im")
        if im is None:
            raise RuntimeError(str(res.get("info", {}).get("PHImageErrorKey") or "sin imagen"))
        cg, _ = im.CGImageForProposedRect_context_hints_(None, None, None)
        url = NSURL.fileURLWithPath_(p["destino"])
        dst = Quartz.CGImageDestinationCreateWithURL(url, "public.jpeg", 1, None)
        Quartz.CGImageDestinationAddImage(dst, cg, {Quartz.kCGImageDestinationLossyCompressionQuality: calidad})
        if not Quartz.CGImageDestinationFinalize(dst):
            raise RuntimeError("no se pudo escribir la miniatura")
    return p["destino"]
