"""Abrir imágenes (JPEG, PNG, HEIC...), leer EXIF y hacer miniaturas."""
from __future__ import annotations

import io
import math
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from PIL import Image, ImageOps

Image.MAX_IMAGE_PIXELS = 300_000_000

try:  # HEIC/HEIF, el formato por defecto del iPhone
    import pillow_heif

    pillow_heif.register_heif_opener()
    HEIF = True
except Exception:  # pragma: no cover - depende de la instalación
    HEIF = False

EXTENSIONES = {".jpg", ".jpeg", ".png", ".heic", ".heif", ".tif", ".tiff", ".webp"}

TAG_EXIF_IFD = 0x8769
TAG_GPS_IFD = 0x8825


def a_srgb(im: Image.Image) -> Image.Image:
    """Las fotos del iPhone vienen en Display P3: sin convertir, impresas salen apagadas."""
    icc = im.info.get("icc_profile")
    if not icc or im.mode not in ("RGB", "RGBA"):
        return im
    try:
        from PIL import ImageCms

        origen = ImageCms.ImageCmsProfile(io.BytesIO(icc))
        if "srgb" in (ImageCms.getProfileDescription(origen) or "").lower():
            return im
        destino = ImageCms.createProfile("sRGB")
        conv = ImageCms.profileToProfile(im, origen, destino, outputMode=im.mode,
                                         renderingIntent=ImageCms.Intent.PERCEPTUAL)
        conv.info.pop("icc_profile", None)
        return conv
    except Exception:
        return im


def abrir(ruta: str | Path, lado_max: int | None = None, color: bool = False) -> Image.Image:
    """Abre una imagen en RGB, girada según su EXIF. Si se da `lado_max`, la reduce
    (y en JPEG decodifica ya reducida, que es mucho más rápido). Con `color=True` además
    la convierte a sRGB (para las láminas)."""
    im = Image.open(ruta)
    if lado_max and im.format == "JPEG":
        im.draft("RGB", (lado_max, lado_max))
    icc = im.info.get("icc_profile")
    im = ImageOps.exif_transpose(im)
    if icc and "icc_profile" not in im.info:
        im.info["icc_profile"] = icc
    if color:
        im = a_srgb(im)
    if im.mode != "RGB":
        if im.mode in ("RGBA", "LA", "P"):
            im = im.convert("RGBA")
            fondo = Image.new("RGB", im.size, (255, 255, 255))
            fondo.paste(im, mask=im.split()[-1])
            im = fondo
        else:
            im = im.convert("RGB")
    if lado_max and max(im.size) > lado_max:
        im.thumbnail((lado_max, lado_max), Image.LANCZOS)
    return im


def miniatura_jpeg(ruta: str | Path, lado: int = 400, calidad: int = 82) -> bytes:
    im = abrir(ruta, lado)
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=calidad, optimize=True)
    return buf.getvalue()


def tam_imagen(ruta: str | Path) -> tuple[int, int]:
    """Tamaño en píxeles ya orientado, sin decodificar la imagen."""
    try:
        with Image.open(ruta) as im:
            w, h = im.size
            ori = im.getexif().get(0x0112, 1)
            return (h, w) if ori in (5, 6, 7, 8) else (w, h)
    except Exception:
        return (0, 0)


def _racional(v) -> float:
    try:
        x = float(v)
    except TypeError:
        n, d = v
        x = n / d if d else float("nan")
    if not math.isfinite(x):
        raise ValueError("racional EXIF no válido")
    return x


def _gms(v, ref) -> float | None:
    try:
        g, m, s = (_racional(x) for x in v)
        r = g + m / 60 + s / 3600
        return -r if ref in ("S", "W", b"S", b"W") else r
    except Exception:
        return None


def exif_basico(ruta: str | Path) -> dict:
    """Fecha de captura, GPS y altitud del EXIF (para la fuente «carpeta»)."""
    out: dict = {"fecha": None, "lat": None, "lon": None, "alt": None, "camara": None}
    try:
        with Image.open(ruta) as im:
            ex = im.getexif()
            sub = ex.get_ifd(TAG_EXIF_IFD)
            gps = ex.get_ifd(TAG_GPS_IFD)
            out["camara"] = " ".join(str(x) for x in (ex.get(0x010F), ex.get(0x0110)) if x) or None
    except Exception:
        return out
    txt = sub.get(0x9003) or sub.get(0x9004) or ex.get(0x0132)
    if txt:
        try:
            dt = datetime.strptime(str(txt).strip("\x00 ")[:19], "%Y:%m:%d %H:%M:%S")
            if dt.year > 1970:
                out["fecha"] = dt
        except Exception:
            pass
        if out["fecha"] is not None:
            off = str(sub.get(0x9011) or sub.get(0x9010) or "").strip("\x00 ")
            m = re.fullmatch(r"([+-])(\d\d):(\d\d)", off)
            if m:
                signo = -1 if m.group(1) == "-" else 1
                tz = timezone(signo * timedelta(hours=int(m.group(2)), minutes=int(m.group(3))))
                out["fecha"] = out["fecha"].replace(tzinfo=tz)
    if gps:
        lat = _gms(gps.get(2), gps.get(1)) if gps.get(2) else None
        lon = _gms(gps.get(4), gps.get(3)) if gps.get(4) else None
        if (lat is not None and lon is not None and math.isfinite(lat) and math.isfinite(lon)
                and abs(lat) <= 90 and abs(lon) <= 180 and not (lat == 0 and lon == 0)):
            out["lat"], out["lon"] = lat, lon
        if gps.get(6) is not None:
            try:
                alt = _racional(gps.get(6))
                if gps.get(5) in (1, b"\x01"):
                    alt = -alt
                if math.isfinite(alt) and abs(alt) < 9000:
                    out["alt"] = alt
            except Exception:
                pass
    return out


def recorte_cuadrado(im: Image.Image, cx: float = 0.5, cy: float = 0.5, zoom: float = 1.0) -> Image.Image:
    """Recorta un cuadrado centrado en (cx, cy) —fracciones 0..1 de la imagen—.
    zoom=1 usa el mayor cuadrado posible; zoom=2 un cuadrado de la mitad de lado."""
    w, h = im.size
    lado = min(w, h) / max(1.0, float(zoom))
    x = min(max(cx * w - lado / 2, 0), w - lado)
    y = min(max(cy * h - lado / 2, 0), h - lado)
    return im.crop((round(x), round(y), round(x + lado), round(y + lado)))


def a_blanco_y_negro(im: Image.Image, contraste: str = "normal") -> Image.Image:
    """Conversión a B/N pensada para impresión en reprografía: luminancia, estiramiento
    moderado sin mover el tono medio (la niebla sigue siendo niebla), sombras protegidas
    (negro ≈ 10/255) y medios algo abiertos contra la ganancia de punto. Devuelve modo «L»."""
    import numpy as np

    a = np.asarray(im.convert("RGB").convert("L", (0.30, 0.59, 0.11, 0)), np.float32) / 255
    lo, hi = np.percentile(a, (0.5, 99.5))
    ganancia = min(1 / max(hi - lo, 1e-3), {"suave": 1.0, "normal": 1.15, "alto": 1.4}.get(contraste, 1.15))
    medio = (lo + hi) / 2
    a = np.clip((a - medio) * ganancia + medio, 0, 1)
    if contraste == "alto":
        a = 0.7 * a + 0.3 * (0.5 - 0.5 * np.cos(np.pi * a))
    a = 0.04 + 0.94 * a ** 0.92
    return Image.fromarray((a * 255 + 0.5).astype(np.uint8), "L")
