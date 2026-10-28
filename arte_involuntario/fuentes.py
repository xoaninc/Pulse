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
    ruta_grande: str | None = None    # la mayor previsualización local (editor de recorte)
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
    largo = _seguro(place, "name", "") or _seguro(place, "address_str", "") or ""
    corto = ""
    try:
        n = place.names
        primero = lambda campo: (getattr(n, campo, None) or [None])[0]  # noqa: E731 (listas de menor a mayor área)
        interes = primero("area_of_interest") or primero("inland_water") or primero("body_of_water")
        ciudad = primero("city") or primero("sub_administrative_area") or primero("region")
        pais = primero("country")
        partes = [x for x in (interes, ciudad, pais) if x]
        corto = ", ".join(dict.fromkeys(partes))
    except Exception:
        pass
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


# Tamaño aproximado (lado largo, px) de cada tipo de previsualización que guarda Fotos.
# _1_105_c ≈ 1024 px: siempre está en el Mac aunque el original esté en iCloud y conserva el GPS.
SUFIJOS_PX = {"_4_5005_c": 500, "_1_105_c": 1100, "_1_102_o": 2048, "_1_102_a": 2048, "_1_100_o": 4000}


def _px_por_nombre(ruta: str) -> int:
    nombre = os.path.basename(ruta)
    for suf, px in SUFIJOS_PX.items():
        if suf in nombre:
            return px
    return 0


def _previsualizaciones(p) -> tuple[str | None, str | None]:
    """(para_analizar, la_mayor): la más pequeña con ≥ 512 px (rápida de leer) y la más grande
    (para el editor de recorte y como último recurso en las láminas). Nunca descarga nada."""
    try:
        derivadas = [d for d in (p.path_derivatives or []) if d.lower().endswith(EXT_IMAGEN) and os.path.exists(d)]
    except Exception:
        derivadas = []
    if not derivadas:
        return None, None
    con_px = []
    for d in derivadas:
        px = _px_por_nombre(d) or max(imagenes.tam_imagen(d))
        con_px.append((px, d))
    buenas = sorted(c for c in con_px if c[0] >= 512)
    analizar = buenas[0][1] if buenas else max(con_px)[1]
    return analizar, max(con_px)[1]


def foto_de_photoinfo(p, extra: dict | None = None) -> Foto:
    extra = extra or {}
    orig = None
    try:
        if p.hasadjustments:
            # editada: solo vale la versión editada; si no está en disco se descargará la actual
            pe = p.path_edited
            orig = pe if pe and os.path.exists(pe) else None
        elif p.path and os.path.exists(p.path) and not p.ismissing:
            orig = p.path
    except Exception:
        orig = None
    previa, grande = _previsualizaciones(p)
    if not previa and not orig:
        # ¿la trajimos antes de iCloud con --traer-icloud?
        from .rutas import MINIATURAS_ICLOUD

        cache = MINIATURAS_ICLOUD / f"{p.uuid}.jpg"
        if cache.exists():
            previa = grande = str(cache)
    # Si la foto está editada, su previsualización ya refleja la edición; para analizar,
    # una previsualización (~1.000 px) es mucho más rápida que un original de 12-48 MP.
    analisis = previa or orig
    dt = _seguro(p, "date")
    if dt is not None and dt.year <= 1970:
        dt = None  # Fotos pone 1970 cuando no hay fecha
    fecha, ts = _fecha(dt)
    lat, lon = None, None
    loc = _seguro(p, "location", (None, None))
    if loc and loc[0] is not None and loc[1] is not None and not (loc[0] == 0 and loc[1] == 0):
        lat, lon = float(loc[0]), float(loc[1])
    alt = extra.get("alt")
    largo, corto = _lugar(p)
    etiquetas = []
    try:
        etiquetas = list(dict.fromkeys(x for x in (p.labels or []) if x))
    except Exception:
        pass
    estetica = None
    try:
        sc = p.score
        if sc and sc.overall:  # 0.0 = Fotos aún no la ha analizado
            estetica = float(sc.overall)
    except Exception:
        pass
    n_caras, cara_max = _caras(p)
    try:
        firma = f"{analisis}|{p.date_modified.isoformat() if p.date_modified else ''}"
    except Exception:
        firma = str(analisis)
    desc = ""
    for attr in ("title", "description"):
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
        ruta_grande=grande,
        fecha=fecha,
        ts=ts,
        lat=lat,
        lon=lon,
        alt=alt,
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


def rutas_legible(n: int) -> str:
    from .rutas import legible

    return legible(n)


def ruta_fototeca(biblioteca: str | None = None) -> Path | None:
    if biblioteca:
        return Path(biblioteca).expanduser()
    try:
        from osxphotos.utils import get_system_library_path

        r = get_system_library_path()
        if r:
            return Path(r)
    except Exception:
        pass
    defecto = Path.home() / "Pictures" / "Photos Library.photoslibrary"
    return defecto if defecto.exists() else None


def comprobar_espacio_fototeca(biblioteca: str | None = None) -> None:
    """Si la app Fotos está abierta, osxphotos copia la base de datos a una carpeta temporal
    (cientos de MB o más): comprobamos que cabe antes de empezar."""
    from . import disco

    lib = ruta_fototeca(biblioteca)
    if not lib:
        return
    try:
        from osxphotos.sqlite_utils import sqlite_db_is_locked

        if not sqlite_db_is_locked(str(lib / "database" / "Photos.sqlite")):
            return  # Fotos cerrada: osxphotos lee la base de datos sin copiarla
    except Exception:
        pass
    tam = 0
    for f in ("database/Photos.sqlite", "database/Photos.sqlite-wal", "database/search/psi.sqlite"):
        try:
            tam += (lib / f).stat().st_size
        except OSError:
            pass
    if tam:
        import tempfile

        if not disco.cabe(int(tam * 1.2), Path(tempfile.gettempdir()), margen=disco.MARGEN_PEQUENO):
            raise disco.SinEspacio(
                f"La app Fotos está abierta y habría que copiar su base de datos ({rutas_legible(tam)}) "
                "y no cabe. Cierra Fotos con ⌘Q y vuelve a lanzar ./arte analizar."
            )


def _altitudes(db) -> dict[str, dict]:
    """Altitud de cada foto: Fotos la guarda en ZASSET.ZLOCATIONDATA (8 doubles: lat, lon, alt…),
    pero osxphotos no la expone. Si algo falla, sin altitud (no es imprescindible)."""
    import struct

    tabla = "ZGENERICASSET" if getattr(db, "photos_version", 0) == 5 else "ZASSET"
    out: dict[str, dict] = {}
    try:
        filas = db.execute(f"SELECT ZUUID, ZLOCATIONDATA FROM {tabla} WHERE ZLOCATIONDATA IS NOT NULL").fetchall()
    except Exception:
        return out
    for uuid, blob in filas:
        try:
            if blob and len(blob) >= 24:
                lat, lon, alt = struct.unpack_from("<3d", blob)
                if alt and abs(alt) < 9000:
                    out[uuid] = {"alt": float(alt)}
        except Exception:
            continue
    return out


MENSAJE_PERMISO = (
    "macOS no deja leer la fototeca. Ve a Ajustes del Sistema → Privacidad y seguridad → "
    "Acceso total al disco y activa «Terminal». Después cierra la Terminal con ⌘Q, ábrela de nuevo "
    "y vuelve a ejecutar la orden."
)


def abrir_fototeca(biblioteca: str | None = None):
    import logging

    logging.getLogger("osxphotos").setLevel(logging.ERROR)  # sin avisos en inglés por cada foto
    try:
        import osxphotos
    except ImportError as e:  # pragma: no cover
        raise RuntimeError("Falta osxphotos. Ejecuta ./instalar.sh de nuevo.") from e
    lib = ruta_fototeca(biblioteca)
    if biblioteca and (not lib or not lib.exists()):
        raise RuntimeError(f"No encuentro la fototeca {biblioteca}")
    if lib:
        try:
            with open(lib / "database" / "Photos.sqlite", "rb") as f:
                f.read(16)
        except PermissionError as e:
            raise RuntimeError(MENSAJE_PERMISO) from e
        except FileNotFoundError:
            pass
    try:
        return osxphotos.PhotosDB(dbfile=str(lib)) if lib else osxphotos.PhotosDB()
    except Exception as e:
        cadena = " ".join(str(x) for x in (e, e.__cause__, e.__context__) if x).lower()
        if any(t in cadena for t in ("permission", "operation not permitted", "errno 1", "error copying")):
            raise RuntimeError(MENSAJE_PERMISO) from e
        if isinstance(e, FileNotFoundError) or "could not get path" in cadena:
            raise RuntimeError(
                "No encuentro tu fototeca de Fotos. Si nunca has abierto la app Fotos en este Mac, ábrela una vez. "
                "Si la fototeca no está en Imágenes: ./arte analizar --biblioteca \"/ruta/a/Fotos.photoslibrary\". "
                "Y comprueba el «Acceso total al disco» de la Terminal."
            ) from e
        raise


def desde_fototeca(
    biblioteca: str | None = None,
    desde: datetime | None = None,
    hasta: datetime | None = None,
    album: str | None = None,
) -> Iterator[Foto]:
    comprobar_espacio_fototeca(biblioteca)
    db = abrir_fototeca(biblioteca)
    extras = _altitudes(db)
    kwargs: dict = {"images": True, "movies": False}
    if desde:
        kwargs["from_date"] = desde
    if hasta:
        kwargs["to_date"] = hasta
    if album:
        kwargs["albums"] = [album]
    for p in db.photos(**kwargs):
        try:
            if _seguro(p, "intrash", False) or _seguro(p, "hidden", False) or _seguro(p, "ismovie", False):
                continue
            # álbumes compartidos y «Compartido contigo» no son fotos tuyas
            if _seguro(p, "shared", False):
                continue
            if _seguro(p, "syndicated", False) and not _seguro(p, "saved_to_library", False):
                continue
            # de las ráfagas, solo la elegida (o la que Fotos propone)
            if _seguro(p, "burst", False) and not (
                _seguro(p, "burst_selected", False) or _seguro(p, "burst_key", False) or _seguro(p, "burst_default_pick", False)
            ):
                continue
            yield foto_de_photoinfo(p, extras.get(p.uuid))
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
