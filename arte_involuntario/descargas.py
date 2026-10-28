"""Imagen a resolución completa SOLO para las fotos elegidas.

Orden de preferencia:
 1. versión editada u original que ya esté en el disco (no copia nada);
 2. descarga desde iCloud de esa foto concreta (osxphotos + Fotos), a datos/originales/;
 3. si no se puede, la mayor previsualización local (avisando de la resolución).
"""
from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

from . import disco, rutas

MAPA = rutas.ORIGINALES / "mapa.json"
MB_POR_FOTO = 12 * 1024**2  # estimación prudente (HEIC/JPEG de iPhone: 2-6 MB; ProRAW mucho más)


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
    if faltan and descargar and any(f.get("fuente") == "fotos" for f in faltan) and sys.platform == "darwin":
        nuevos = _descargar_icloud([f for f in faltan if f.get("fuente") == "fotos"], aviso)
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
    disco.comprobar(MB_POR_FOTO * len(fotos), f"descargar {len(fotos)} fotos de iCloud", rutas.ORIGINALES)
    try:
        import osxphotos
        from osxphotos.photoexporter import ExportOptions, PhotoExporter
    except Exception as e:  # pragma: no cover
        aviso(f"  ! No puedo usar osxphotos para descargar: {e}")
        return {}
    aviso(f"· Descargando {len(fotos)} fotos de iCloud (solo las elegidas)… la app Fotos puede abrirse sola.")
    db = osxphotos.PhotosDB()
    resultado: dict[str, str] = {}
    por_uuid = {p.uuid: p for p in db.photos(uuid=[f["uuid"] for f in fotos])}
    for k, f in enumerate(fotos, 1):
        p = por_uuid.get(f["uuid"])
        if not p:
            continue
        destino = rutas.ORIGINALES / f["uuid"]
        destino.mkdir(parents=True, exist_ok=True)
        ruta = None
        ultimo_error = None
        for opciones in (
            dict(download_missing=True, use_photokit=True, edited=bool(p.hasadjustments)),
            dict(download_missing=True, use_photos_export=True, edited=bool(p.hasadjustments)),
        ):
            try:
                res = PhotoExporter(p).export(str(destino), options=ExportOptions(overwrite=True, **opciones))
                hechos = [x for x in (res.exported or []) if _es_imagen_valida(x)]
                if hechos:
                    ruta = hechos[0]
                    break
            except Exception as e:
                ultimo_error = e
                continue
        if ruta:
            resultado[f["uuid"]] = ruta
            aviso(f"  {k}/{len(fotos)} ✓ {Path(ruta).name}")
        else:
            shutil.rmtree(destino, ignore_errors=True)
            motivo = f": {ultimo_error}" if ultimo_error else ""
            aviso(f"  {k}/{len(fotos)} ✗ no se pudo descargar {f.get('nombre') or f['uuid']}{motivo}"
                  " (se usará la previsualización)")
    return resultado
