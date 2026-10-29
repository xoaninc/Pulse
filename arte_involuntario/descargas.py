"""Imagen a resolución completa SOLO para las fotos elegidas.

Orden de preferencia:
 1. versión editada u original que ya esté en el disco (no copia nada);
 2. descarga desde iCloud de esa foto concreta con PhotoKit (versión actual, con tus
    ediciones; de una Live Photo, solo la foto fija), a datos/originales/, en un proceso
    aparte que se mata si iCloud se cuelga (ver exportar_photokit.py);
 3. si no se puede, la mayor previsualización local (avisando de la resolución).
Nunca deja sin láminas: cualquier fallo de iCloud se convierte en un aviso.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import time
from pathlib import Path

from . import disco, rutas

MAPA = rutas.ORIGINALES / "mapa.json"
MB_POR_FOTO = 12 * 1024**2      # estimación prudente (HEIC/JPEG de iPhone: 2-6 MB; ProRAW mucho más)
SEGUNDOS_POR_FOTO = 120          # si iCloud no la entrega en este tiempo, se usa la previsualización
SEGUNDOS_TOTALES = 15 * 60       # tope para todas las descargas de una generación
FALLOS_SEGUIDOS = 3              # si fallan varias seguidas, iCloud no está respondiendo: parar


def _mapa() -> dict:
    try:
        return json.loads(MAPA.read_text())
    except Exception:
        return {}


def _guardar_mapa(m: dict) -> None:
    rutas.ORIGINALES.mkdir(parents=True, exist_ok=True)
    MAPA.write_text(json.dumps(m, indent=1))


def _es_imagen_valida(ruta: str | None) -> bool:
    if not ruta or not os.path.exists(ruta):
        return False
    try:
        from PIL import Image

        from . import imagenes

        assert imagenes  # al importarlo se registra el lector de HEIC

        with Image.open(ruta) as im:
            im.size
        return True
    except Exception:
        return False


def resolver(fotos: list[dict], descargar: bool = True, aviso=print) -> dict[str, dict]:
    """Devuelve {uuid: {"ruta": ..., "origen": "local|icloud|previa", "lado": px}}."""
    out: dict[str, dict] = {}
    mapa = _mapa()
    faltan = []
    for f in fotos:
        u = f["uuid"]
        if _es_imagen_valida(f.get("ruta_original")):
            out[u] = {"ruta": f["ruta_original"], "origen": "local"}
        elif u in mapa and _es_imagen_valida(mapa[u]):
            out[u] = {"ruta": mapa[u], "origen": "icloud"}
        else:
            faltan.append(f)
    de_fotos = [f for f in faltan if f.get("fuente") == "fotos"]
    if de_fotos and descargar and sys.platform == "darwin":
        try:
            nuevos = _descargar_icloud(de_fotos, aviso)
        except Exception as e:
            aviso(f"⚠ No se descargan originales de iCloud ({e}); se usan las previsualizaciones.")
            nuevos = {}
        if nuevos:
            mapa.update(nuevos)
            _guardar_mapa(mapa)
        for u, r in nuevos.items():
            out[u] = {"ruta": r, "origen": "icloud"}
    for f in fotos:
        if f["uuid"] in out:
            continue
        for clave in ("ruta_grande", "ruta_analisis"):
            if _es_imagen_valida(f.get(clave)):
                out[f["uuid"]] = {"ruta": f[clave], "origen": "previa"}
                break
    from .imagenes import tam_imagen

    for u, d in out.items():
        w, h = tam_imagen(d["ruta"])
        d["lado"] = min(w, h)
    return out


def _descargar_icloud(fotos: list[dict], aviso) -> dict[str, str]:
    from .exportar_photokit import Colgado, Exportador
    from .icloud import _autorizar

    try:
        _autorizar()  # espera la respuesta del aviso de permisos (la primera vez)
    except Exception as e:
        aviso(f"⚠ {e}")
        return {}
    aviso(f"· Descargando de iCloud {len(fotos)} fotos elegidas (solo estas)…")
    resultado: dict[str, str] = {}
    t0 = time.monotonic()
    seguidos = 0
    # Cada exportación va a un proceso aparte (exportar_photokit): si iCloud se cuelga, se mata ese
    # proceso y la app sigue, termina y no pierde lo que imprime. Al salir del `with` (también con
    # Ctrl+C o un error) el proceso se cierra.
    with Exportador() as ex:
        for k, f in enumerate(fotos, 1):
            nombre = f.get("nombre") or f["uuid"]
            if not disco.cabe(2 * MB_POR_FOTO, rutas.ORIGINALES):
                aviso(f"⚠ Poco espacio libre: dejo de descargar; las {len(fotos) - k + 1} restantes usan la previsualización.")
                break
            if time.monotonic() - t0 > SEGUNDOS_TOTALES:
                aviso("⚠ iCloud va muy lento: dejo de descargar; el resto usa la previsualización.")
                break
            destino = rutas.ORIGINALES / f["uuid"]
            destino.mkdir(parents=True, exist_ok=True)
            try:
                ruta = ex.pedir("original", f["uuid"], destino, SEGUNDOS_POR_FOTO)
                if not _es_imagen_valida(ruta):
                    raise RuntimeError("iCloud no devolvió una imagen válida")
                resultado[f["uuid"]] = ruta
                seguidos = 0
                aviso(f"  {k}/{len(fotos)} ✓ {Path(ruta).name}")
            except Colgado:
                seguidos += 1
                shutil.rmtree(destino, ignore_errors=True)
                aviso(f"  {k}/{len(fotos)} ✗ {nombre}: iCloud no responde (se usará la previsualización)")
            except Exception as e:
                seguidos += 1
                shutil.rmtree(destino, ignore_errors=True)
                aviso(f"  {k}/{len(fotos)} ✗ {nombre}: {e} (se usará la previsualización)")
            if seguidos >= FALLOS_SEGUIDOS:
                aviso("⚠ iCloud no está entregando las fotos (¿sin internet?): el resto usa la previsualización.")
                break
    return resultado
