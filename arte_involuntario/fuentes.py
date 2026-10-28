"""De dónde salen las fotos: la app Fotos de macOS (vía osxphotos) o una carpeta.

Con iCloud y «Optimizar almacenamiento del Mac», la mayoría de originales NO están en el
disco. No pasa nada: Fotos guarda siempre previsualizaciones locales (derivatives) y son
de sobra para analizar. Aquí nunca se descarga nada; eso solo ocurre en `descargas.py`
con las fotos que elijas para las láminas.
"""
from __future__ import annotations

import hashlib
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Iterator

from . import imagenes

EXT_IMAGEN = (".jpeg", ".jpg", ".heic", ".heif", ".png", ".tif", ".tiff", ".webp")


@dataclass
class Foto:
    uuid: str
    fuente: str                      # "fotos" | "carpeta"
    nombre: str = ""
    ruta_analisis: str | None = None  # imagen local que se analiza (previsualización u original)
    ruta_original: str | None = None  # original/editada si está en el disco
    fecha: str | None = None          # ISO 8601 con zona horaria si se conoce
    ts: float | None = None           # segundos desde 1970 (UTC)
    lat: float | None = None
    lon: float | None = None
    alt: float | None = None
    lugar: str = ""
    lugar_corto: str = ""
    etiquetas: list[str] = field(default_factory=list)
    captura: bool = False             # captura de pantalla / grabación
    selfie: bool = False
    favorita: bool = False
    estetica: float | None = None     # puntuación estética de Fotos (-1..1)
    ancho: int = 0
    alto: int = 0
    en_icloud: bool = False           # el original no está en este Mac
    caras: int = 0
    cara_max: float = 0.0             # tamaño relativo de la cara más grande (0..1)
    descripcion: str = ""             # pie de foto de Apple Intelligence, título o descripción
    firma: str = ""                   # cambia si la imagen cambia (para volver a analizarla)

    def a_dict(self) -> dict:
        return asdict(self)


def _fecha(dt: datetime | None) -> tuple[str | None, float | None]:
    if not dt:
        return None, None
    try:
        return dt.isoformat(), dt.timestamp()
    except Exception:
        return None, None


def _seguro(obj, attr, defecto=None):
    try:
        v = getattr(obj, attr)
        return defecto if v is None else v
    except Exception:
        return defecto


# ---------------------------------------------------------------------------
# Fotos de Apple
# ---------------------------------------------------------------------------

def _lugar(p) -> tuple[str, str]:
    place = _seguro(p, "place")
    if not place:
        return "", ""
    largo = ""
    corto = ""
    try:
        largo = place.address_str or place.name or ""
    except Exception:
        largo = _seguro(place, "name", "") or ""
    try:
        n = place.names
        ciudad = (n.city or n.sub_locality or n.area_of_interest or n.additional_city or [None])
        ciudad = ciudad[0] if isinstance(ciudad, (list, tuple)) and ciudad else ciudad
        interes = n.area_of_interest[0] if getattr(n, "area_of_interest", None) else None
        pais = n.country[0] if getattr(n, "country", None) else None
        partes = [x for x in (interes, ciudad if ciudad != interes else None, pais) if x]
        corto = ", ".join(dict.fromkeys(partes))
    except Exception:
        corto = (_seguro(place, "name", "") or "").split(",")[0]
    return largo, corto or largo.split(",")[0]


def _caras(p) -> tuple[int, float]:
    try:
        caras = p.face_info or []
    except Exception:
        return 0, 0.0
    tam = 0.0
    for f in caras:
        try:
            tam = max(tam, float(f.size or 0))
        except Exception:
            pass
    return len(caras), tam


def _previsualizacion(p) -> str | None:
    """La mayor previsualización local de imagen (Fotos las ordena de mayor a menor)."""
    try:
        derivadas = p.path_derivatives or []
    except Exception:
        derivadas = []
    for d in derivadas:
        if d.lower().endswith(EXT_IMAGEN) and os.path.exists(d):
            return d
    return None


def foto_de_photoinfo(p) -> Foto:
    orig = None
    try:
        if p.hasadjustments and p.path_edited and os.path.exists(p.path_edited):
            orig = p.path_edited
        elif p.path and os.path.exists(p.path) and not p.ismissing:
            orig = p.path
    except Exception:
        orig = None
    previa = _previsualizacion(p)
    # Para analizar, una previsualización (~1-2k px) es más rápida que un original de 12-48 MP.
    analisis = previa or orig
    fecha, ts = _fecha(_seguro(p, "date"))
    lat, lon = None, None
    loc = _seguro(p, "location", (None, None))
    if loc and loc[0] is not None and loc[1] is not None and not (loc[0] == 0 and loc[1] == 0):
        lat, lon = float(loc[0]), float(loc[1])
    largo, corto = _lugar(p)
    etiquetas = []
    try:
        etiquetas = list(dict.fromkeys(x for x in (p.labels or []) if x))
    except Exception:
        pass
    estetica = None
    try:
        sc = p.score
        estetica = float(sc.overall) if sc and sc.overall is not None else None
    except Exception:
        pass
    n_caras, cara_max = _caras(p)
    try:
        firma = f"{analisis}|{p.date_modified.isoformat() if p.date_modified else ''}"
    except Exception:
        firma = str(analisis)
    desc = ""
    for attr in ("ai_caption", "title", "description"):
        v = _seguro(p, attr, "")
        if isinstance(v, str) and v.strip():
            desc = v.strip()
            break
    return Foto(
        uuid=p.uuid,
        fuente="fotos",
        nombre=_seguro(p, "original_filename", "") or "",
        ruta_analisis=analisis,
        ruta_original=orig,
        fecha=fecha,
        ts=ts,
        lat=lat,
        lon=lon,
        lugar=largo,
        lugar_corto=corto,
        etiquetas=etiquetas,
        captura=bool(_seguro(p, "screenshot", False) or _seguro(p, "screen_recording", False)),
        selfie=bool(_seguro(p, "selfie", False)),
        favorita=bool(_seguro(p, "favorite", False)),
        estetica=estetica,
        ancho=int(_seguro(p, "width", 0) or 0),
        alto=int(_seguro(p, "height", 0) or 0),
        en_icloud=orig is None,
        caras=n_caras,
        cara_max=cara_max,
        descripcion=desc,
        firma=firma,
    )


def abrir_fototeca(biblioteca: str | None = None):
    try:
        import osxphotos
    except ImportError as e:  # pragma: no cover
        raise RuntimeError("Falta osxphotos. Ejecuta ./instalar.sh de nuevo.") from e
    try:
        return osxphotos.PhotosDB(dbfile=biblioteca) if biblioteca else osxphotos.PhotosDB()
    except Exception as e:
        msg = str(e)
        if "permission" in msg.lower() or "operation not permitted" in msg.lower() or "Errno 1" in msg:
            raise RuntimeError(
                "macOS no deja leer la fototeca. Ve a Ajustes del Sistema → Privacidad y seguridad → "
                "Acceso total al disco y activa «Terminal» (o la app de terminal que uses). "
                "Después cierra y vuelve a abrir la Terminal."
            ) from e
        raise


def desde_fototeca(
    biblioteca: str | None = None,
    desde: datetime | None = None,
    hasta: datetime | None = None,
    album: str | None = None,
) -> Iterator[Foto]:
    db = abrir_fototeca(biblioteca)
    kwargs: dict = {"images": True, "movies": False}
    if desde:
        kwargs["from_date"] = desde
    if hasta:
        kwargs["to_date"] = hasta
    if album:
        kwargs["albums"] = [album]
    for p in db.photos(**kwargs):
        try:
            if _seguro(p, "intrash", False) or _seguro(p, "hidden", False):
                continue
            if _seguro(p, "ismovie", False):
                continue
            # De las ráfagas, solo la elegida (o la primera)
            if _seguro(p, "burst", False) and not (_seguro(p, "burst_selected", False) or _seguro(p, "burst_key", False)):
                continue
            yield foto_de_photoinfo(p)
        except Exception as e:  # una foto rara no debe parar el análisis
            print(f"  ! Saltando {getattr(p, 'uuid', '?')}: {e}")


# ---------------------------------------------------------------------------
# Carpeta (cualquier ordenador, o fotos exportadas)
# ---------------------------------------------------------------------------

def desde_carpeta(carpeta: str | Path, desde: datetime | None = None, hasta: datetime | None = None) -> Iterator[Foto]:
    raiz = Path(carpeta).expanduser().resolve()
    if not raiz.exists():
        raise RuntimeError(f"No existe la carpeta {raiz}")
    for dirpath, dirnames, filenames in os.walk(raiz):
        dirnames[:] = sorted(d for d in dirnames if not d.startswith(".") and not d.endswith(".photoslibrary"))
        for fn in sorted(filenames):
            if fn.startswith(".") or Path(fn).suffix.lower() not in imagenes.EXTENSIONES:
                continue
            ruta = Path(dirpath) / fn
            ex = imagenes.exif_basico(ruta)
            dt = ex["fecha"]
            if dt is None:
                try:
                    dt = datetime.fromtimestamp(ruta.stat().st_mtime).astimezone()
                except Exception:
                    dt = None
            if dt is not None and dt.tzinfo is None:
                dt = dt.astimezone()
            if desde and dt and dt < (desde if desde.tzinfo else desde.astimezone()):
                continue
            if hasta and dt and dt > (hasta if hasta.tzinfo else hasta.astimezone()):
                continue
            fecha, ts = _fecha(dt)
            w, h = imagenes.tam_imagen(ruta)
            nombre = fn.lower()
            try:
                st = ruta.stat()
                firma = f"{st.st_mtime_ns}-{st.st_size}"
            except OSError:
                firma = ""
            yield Foto(
                uuid="c_" + hashlib.sha1(str(ruta).encode()).hexdigest()[:20],
                fuente="carpeta",
                nombre=fn,
                ruta_analisis=str(ruta),
                ruta_original=str(ruta),
                fecha=fecha,
                ts=ts,
                lat=ex["lat"],
                lon=ex["lon"],
                alt=ex["alt"],
                lugar_corto=Path(dirpath).name if Path(dirpath) != raiz else "",
                captura=nombre.startswith(("screenshot", "captura", "screen shot")),
                ancho=w,
                alto=h,
                firma=firma,
            )
