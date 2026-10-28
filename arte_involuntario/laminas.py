"""Maquetación de las 6 láminas A3 apaisadas (4 de arte involuntario + 2 del paseo).

La maqueta se describe una vez (posiciones en mm) y se dibuja con dos «motores»:
- PDF vectorial (reportlab) para la entrega,
- JPG con Pillow para las vistas previas y por si te piden imágenes.
"""
from __future__ import annotations

import io
import math
import os
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from . import imagenes

A3 = (420.0, 297.0)  # mm, apaisado
PT = 25.4 / 72       # 1 punto tipográfico en mm

ORDEN_CATEGORIAS = ["vuelos", "acumulaciones", "islas", "construcciones",
                    "erosiones", "instalaciones", "huellas", "apariciones"]

# ---------------------------------------------------------------------------
# Tipografías: Futura (la de Hamish Fulton) si estamos en un Mac; si no, lo que haya.
# ---------------------------------------------------------------------------

CANDIDATAS = [
    ("Futura", "/System/Library/Fonts/Supplemental/Futura.ttc",
     {"normal": ["Medium"], "negrita": ["Bold", "Condensed ExtraBold"], "cursiva": ["Medium Italic"]}),
    ("Avenir Next", "/System/Library/Fonts/Avenir Next.ttc",
     {"normal": ["Regular", "Medium"], "negrita": ["Bold", "Demi Bold"], "cursiva": ["Italic"]}),
    ("Helvetica Neue", "/System/Library/Fonts/HelveticaNeue.ttc",
     {"normal": ["Regular"], "negrita": ["Bold"], "cursiva": ["Italic"]}),
    ("Helvetica", "/System/Library/Fonts/Helvetica.ttc",
     {"normal": ["Regular"], "negrita": ["Bold"], "cursiva": ["Oblique"]}),
]
CANDIDATAS_SUELTAS = [
    ("Liberation Sans", {
        "normal": "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "negrita": "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "cursiva": "/usr/share/fonts/truetype/liberation/LiberationSans-Italic.ttf"}),
    ("DejaVu Sans", {
        "normal": "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "negrita": "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "cursiva": "/usr/share/fonts/truetype/dejavu/DejaVuSans-Oblique.ttf"}),
]


def _indice_ttc(ruta: str, estilos: list[str]) -> int | None:
    for objetivo in estilos:
        for i in range(24):
            try:
                f = ImageFont.truetype(ruta, 12, index=i)
            except Exception:
                break
            if f.getname()[1].lower() == objetivo.lower():
                return i
    return None


class Fuentes:
    """Resuelve la tipografía y la registra en reportlab y en Pillow."""

    def __init__(self, preferida: str | None = None):
        self.familia = "Helvetica"
        self.archivos: dict[str, tuple[str, int]] = {}
        orden = CANDIDATAS
        if preferida:
            orden = sorted(CANDIDATAS, key=lambda c: c[0].lower() != preferida.lower())
        for familia, ruta, estilos in orden:
            if not os.path.exists(ruta):
                continue
            idx = {k: _indice_ttc(ruta, v) for k, v in estilos.items()}
            if idx["normal"] is None:
                continue
            for k in ("negrita", "cursiva"):
                if idx[k] is None:
                    idx[k] = idx["normal"]
            self.familia = familia
            self.archivos = {k: (ruta, i) for k, i in idx.items()}
            break
        if not self.archivos:
            for familia, rutas_ in CANDIDATAS_SUELTAS:
                if all(os.path.exists(r) for r in rutas_.values()):
                    self.familia = familia
                    self.archivos = {k: (r, 0) for k, r in rutas_.items()}
                    break
        self._rl: dict[str, str] = {}
        self._registrar_reportlab()
        self._pil_cache: dict = {}

    def _registrar_reportlab(self):
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont

        base = {"normal": "Helvetica", "negrita": "Helvetica-Bold", "cursiva": "Helvetica-Oblique"}
        for estilo, (ruta, idx) in self.archivos.items():
            nombre = f"AI-{estilo}"
            try:
                if ruta.lower().endswith(".ttc"):
                    pdfmetrics.registerFont(TTFont(nombre, ruta, subfontIndex=idx))
                else:
                    pdfmetrics.registerFont(TTFont(nombre, ruta))
                self._rl[estilo] = nombre
            except Exception:
                self._rl[estilo] = base[estilo]
        for k, v in base.items():
            self._rl.setdefault(k, v)

    def rl(self, estilo: str) -> str:
        return self._rl.get(estilo, "Helvetica")

    def ancho(self, texto: str, estilo: str, pt: float, tracking: float = 0) -> float:
        """Ancho en mm."""
        from reportlab.pdfbase.pdfmetrics import stringWidth

        return (stringWidth(texto, self.rl(estilo), pt) + tracking * pt * max(0, len(texto) - 1)) * PT

    def pil(self, estilo: str, px: int):
        clave = (estilo, px)
        if clave not in self._pil_cache:
            ruta, idx = self.archivos.get(estilo, (None, 0))
            try:
                f = ImageFont.truetype(ruta, px, index=idx) if ruta else ImageFont.load_default(px)
            except Exception:
                f = ImageFont.load_default(px)
            self._pil_cache[clave] = f
        return self._pil_cache[clave]


# ---------------------------------------------------------------------------
# Elementos de la maqueta (coordenadas en mm desde la esquina superior izquierda)
# ---------------------------------------------------------------------------

@dataclass
class Foto:
    x: float
    y: float
    lado: float
    im: Image.Image


@dataclass
class Texto:
    x: float
    y: float            # línea base
    texto: str
    estilo: str = "normal"
    pt: float = 9
    alin: str = "izq"   # izq | centro | der
    tracking: float = 0  # espaciado extra entre letras, en fracción del cuerpo
    gris: float = 0.0    # 0 = negro, 1 = blanco


@dataclass
class Linea:
    puntos: list[tuple[float, float]]
    grosor: float = 0.3
    gris: float = 0.0


@dataclass
class Punto:
    x: float
    y: float
    r: float
    relleno: bool = True
    gris: float = 0.0


@dataclass
class Lamina:
    elementos: list = field(default_factory=list)
    ancho: float = A3[0]
    alto: float = A3[1]


# ---------------------------------------------------------------------------
# Utilidades de texto
# ---------------------------------------------------------------------------

def partir(texto: str, fu: Fuentes, estilo: str, pt: float, ancho: float, tracking: float = 0) -> list[str]:
    palabras = texto.split()
    lineas: list[str] = []
    actual = ""
    for p in palabras:
        prueba = f"{actual} {p}".strip()
        if fu.ancho(prueba, estilo, pt, tracking) <= ancho or not actual:
            actual = prueba
        else:
            lineas.append(actual)
            actual = p
    if actual:
        lineas.append(actual)
    return lineas


def texto_en_caja(texto, fu, estilo, pt, ancho, max_lineas, pt_min=6.0, tracking=0.0):
    """Reduce el cuerpo hasta que el texto quepa en `max_lineas` líneas."""
    while True:
        lineas = partir(texto, fu, estilo, pt, ancho, tracking)
        if len(lineas) <= max_lineas or pt <= pt_min:
            if len(lineas) > max_lineas:
                lineas = lineas[:max_lineas]
                lineas[-1] = lineas[-1].rstrip(".,;: ") + "…"
            return lineas, pt
        pt -= 0.5


def preparar_foto(im: Image.Image, recorte: dict | None, lado_mm: float, bn: bool, contraste: str, dpi: int = 300):
    r = recorte or {}
    cuadrada = imagenes.recorte_cuadrado(im, float(r.get("cx", 0.5)), float(r.get("cy", 0.5)), float(r.get("zoom", 1.0)))
    objetivo = round(lado_mm / 25.4 * dpi)
    baja = cuadrada.width < objetivo * 0.6
    if cuadrada.width > objetivo:
        cuadrada = cuadrada.resize((objetivo, objetivo), Image.LANCZOS)
    if bn:
        cuadrada = imagenes.a_blanco_y_negro(cuadrada, contraste)
    return cuadrada, baja


# ---------------------------------------------------------------------------
# Lámina tipo 1: arte involuntario (2 filas x 3 columnas, color)
# ---------------------------------------------------------------------------

def maquetar_arte(fotos: list[dict], fu: Fuentes, autor: str = "", nombres: dict | None = None,
                  cabecera: bool = True) -> list[Lamina]:
    """`fotos`: dicts con im (PIL), categoria, pie. Devuelve 4 láminas (o las que hagan falta)."""
    nombres = nombres or {}
    W, H = A3
    s, gap_x, gap_y, cap = 106.0, 15.0, 11.0, 15.0
    ancho_rejilla = 3 * s + 2 * gap_x
    x0 = (W - ancho_rejilla) / 2
    y0 = 30.0
    paginas = max(1, math.ceil(len(fotos) / 6))
    laminas = []
    for p in range(paginas):
        L = Lamina()
        if cabecera:
            L.elementos.append(Texto(x0, 17, "COLECCIÓN FOTOGRÁFICA DE ARTE INVOLUNTARIO", "negrita", 10, tracking=0.08))
            L.elementos.append(Texto(x0, 22.5, "a partir del Breve tratado del arte involuntario de Gilles Clément", "cursiva", 8))
            der = f"{autor.upper()}  ·  " if autor else ""
            L.elementos.append(Texto(x0 + ancho_rejilla, 17, f"{der}LÁMINA {p + 1}/{paginas}", "normal", 9, "der", tracking=0.06))
            L.elementos.append(Texto(x0 + ancho_rejilla, 22.5, "Ejercicio 2.3 · Fotografía · Bloque 2 Observar/Documentar", "normal", 7.5, "der", gris=0.35))
        for k, f in enumerate(fotos[p * 6:(p + 1) * 6]):
            fila, col = divmod(k, 3)
            x = x0 + col * (s + gap_x)
            y = y0 + fila * (s + cap + gap_y)
            L.elementos.append(Foto(x, y, s, f["im"]))
            cat = nombres.get(f["categoria"], f["categoria"]).upper()
            L.elementos.append(Texto(x, y + s + 6.2, cat, "negrita", 12, tracking=0.06))
            pie = (f.get("pie") or "").strip()
            if pie:
                lineas, pt = texto_en_caja(pie, fu, "cursiva", 8, s, 2, 6.5)
                for j, ln in enumerate(lineas):
                    L.elementos.append(Texto(x, y + s + 10.6 + j * pt * PT * 1.25, ln, "cursiva", pt, gris=0.2))
        laminas.append(L)
    return laminas


# ---------------------------------------------------------------------------
# Lámina tipo 2: paseo al estilo Hamish Fulton (B/N)
# ---------------------------------------------------------------------------

def _rejilla(n: int, ancho: float, alto: float, cap: float, gap: float) -> tuple[int, int, float]:
    mejor = (1, n, 0.0)
    for filas in (1, 2, 3):
        cols = math.ceil(n / filas)
        s = min((ancho - (cols - 1) * gap) / cols, (alto - filas * cap - (filas - 1) * gap) / filas)
        if s > mejor[2]:
            mejor = (filas, cols, s)
    return mejor


def _dibujo_recorrido(L: Lamina, puntos: list[dict], x: float, y: float, w: float, h: float, fu: Fuentes):
    """Pequeño croquis del recorrido (planta desde el GPS) o perfil de altitud, como los murales de Fulton."""
    con_alt = [p for p in puntos if p.get("alt") is not None and p.get("km") is not None]
    con_gps = [p for p in puntos if p.get("lat") is not None and p.get("lon") is not None]
    if len(con_alt) >= max(4, len(puntos) * 0.6):
        xs = [p["km"] for p in con_alt]
        ys = [p["alt"] for p in con_alt]
        etiqueta = f"PERFIL · {round(min(ys))}–{round(max(ys))} M"
    elif len(con_gps) >= 3:
        lat0 = sum(p["lat"] for p in con_gps) / len(con_gps)
        xs = [p["lon"] * math.cos(math.radians(lat0)) for p in con_gps]
        ys = [p["lat"] for p in con_gps]
        etiqueta = "RECORRIDO"
        con_alt = con_gps
        w = min(w, 70.0)
    else:
        return False
    minx, maxx, miny, maxy = min(xs), max(xs), min(ys), max(ys)
    dx, dy = (maxx - minx) or 1e-9, (maxy - miny) or 1e-9
    if etiqueta == "RECORRIDO":
        esc = min(w / dx, (h - 6) / dy)
        ox = x + (w - dx * esc) / 2
        oy = y + (h - 6 - dy * esc) / 2 + dy * esc
        pts = [(ox + (a - minx) * esc, oy - (b - miny) * esc) for a, b in zip(xs, ys)]
    else:
        pts = [(x + (a - minx) / dx * w, y + (h - 6) - (b - miny) / dy * (h - 6)) for a, b in zip(xs, ys)]
    L.elementos.append(Linea(pts, 0.45))
    for k, (px, py) in enumerate(pts):
        if k == 0:
            L.elementos.append(Punto(px, py, 1.3, True))
        elif k == len(pts) - 1:
            L.elementos.append(Punto(px, py, 1.3, False))
        else:
            L.elementos.append(Punto(px, py, 0.55, True))
    L.elementos.append(Texto(x, y + h + 1.5, etiqueta, "normal", 6.5, tracking=0.12, gris=0.3))
    return True


def maquetar_paseo(fotos: list[dict], fu: Fuentes, titulo: str, linea: str, autor: str = "",
                   mayusculas: bool = True, dibujo: bool = True, cabecera: bool = True,
                   diseno: str = "rejilla") -> list[Lamina]:
    """`fotos`: dicts con im (ya en B/N), frase, y opcionalmente km/alt/lat/lon. Siempre 2 láminas."""
    W, H = A3
    n = len(fotos)
    corte = math.ceil(n / 2)
    grupos = [fotos[:corte], fotos[corte:]]
    margen = 20.0
    laminas = []
    for p, grupo in enumerate(grupos):
        L = Lamina()
        top = 20.0
        if p == 0:
            tit = (titulo or "").strip().upper()
            pt_tit = 40
            while tit and fu.ancho(tit, "negrita", pt_tit, 0.04) > W - 2 * margen - 70 and pt_tit > 18:
                pt_tit -= 2
            if tit:
                L.elementos.append(Texto(margen, top + pt_tit * PT * 0.8, tit, "negrita", pt_tit, tracking=0.04))
            y_linea = top + (pt_tit * PT * 0.8 + 7 if tit else 4)
        else:
            y_linea = top + 4
        if linea:
            lns, ptl = texto_en_caja(linea.upper(), fu, "normal", 9, W - 2 * margen - 80, 2, 7, tracking=0.08)
            for j, ln in enumerate(lns):
                L.elementos.append(Texto(margen, y_linea + j * ptl * PT * 1.35, ln, "normal", ptl, tracking=0.08))
            y_fin_cab = y_linea + len(lns) * ptl * PT * 1.35
        else:
            y_fin_cab = y_linea
        if cabecera:
            der = f"{autor.upper()}  ·  " if autor else ""
            L.elementos.append(Texto(W - margen, top + 3, f"{der}PASEO FOTOGRÁFICO · {p + 1}/2", "normal", 8, "der", tracking=0.08))
            L.elementos.append(Texto(W - margen, top + 7.5, "según las pautas de Hamish Fulton", "cursiva", 7.5, "der", gris=0.35))
        zona_y = max(y_fin_cab + 8, 50.0)
        if p == 1 and dibujo:
            # franja propia bajo la cabecera, a lo ancho, como los murales de Fulton
            if _dibujo_recorrido(L, fotos, margen, y_fin_cab + 6, W - 2 * margen, 22, fu):
                zona_y = y_fin_cab + 6 + 22 + 10
        cap = 15.0
        gap = 7.0
        alto = H - zona_y - 14
        ancho = W - 2 * margen
        if not grupo:
            laminas.append(L)
            continue
        if diseno == "crece" and len(grupo) >= 3:
            _maquetar_crece(L, grupo, p, corte, fu, margen, zona_y, ancho, alto, cap, mayusculas)
        else:
            filas, cols, s = _rejilla(len(grupo), ancho, alto, cap, gap)
            usado_w = cols * s + (cols - 1) * gap
            usado_h = filas * (s + cap) + (filas - 1) * gap
            x0 = (W - usado_w) / 2
            y0 = zona_y + (alto - usado_h) / 2
            for k, f in enumerate(grupo):
                fila, col = divmod(k, cols)
                x = x0 + col * (s + gap)
                y = y0 + fila * (s + cap + gap)
                _foto_paseo(L, f, x, y, s, p * corte + k, n, fu, mayusculas)
        laminas.append(L)
    return laminas


def _foto_paseo(L, f, x, y, s, num, n, fu, mayusculas):
    L.elementos.append(Foto(x, y, s, f["im"]))
    marca = "ORIGEN" if num == 0 else ("FINAL" if num == n - 1 else f"{num + 1:02d}")
    L.elementos.append(Texto(x, y + s + 4.2, marca, "negrita", 7.5, tracking=0.12))
    frase = (f.get("frase") or "").strip()
    if mayusculas:
        frase = frase.upper()
    if frase:
        lineas, pt = texto_en_caja(frase, fu, "normal", 7.5, s, 3, 5.5, tracking=0.03 if mayusculas else 0)
        for j, ln in enumerate(lineas):
            L.elementos.append(Texto(x, y + s + 8.0 + j * pt * PT * 1.3, ln, "normal", pt, tracking=0.03 if mayusculas else 0))


def _maquetar_crece(L, grupo, p, corte, fu, margen, zona_y, ancho, alto, cap, mayusculas):
    """Variante «Within Sight» (Helen Sear): las fotos crecen a lo largo del recorrido, alineadas abajo."""
    m = len(grupo)
    n_total = corte * 2
    gap = 5.0
    pesos = [1 + 0.9 * ((p * corte + k) / max(1, n_total - 1)) for k in range(m)]
    # dos filas si son muchas
    filas = 2 if m > 5 else 1
    por_fila = math.ceil(m / filas)
    alto_fila = (alto - (filas - 1) * 8) / filas
    for fi in range(filas):
        trozo = list(range(fi * por_fila, min(m, (fi + 1) * por_fila)))
        if not trozo:
            continue
        suma = sum(pesos[k] for k in trozo)
        esc = min((ancho - gap * (len(trozo) - 1)) / suma, (alto_fila - cap) / max(pesos[k] for k in trozo))
        usado = sum(pesos[k] * esc for k in trozo) + gap * (len(trozo) - 1)
        x = margen + (ancho - usado) / 2
        base = zona_y + fi * (alto_fila + 8) + alto_fila - cap
        for k in trozo:
            s = pesos[k] * esc
            _foto_paseo(L, grupo[k], x, base - s, s, p * corte + k, n_total, fu, mayusculas)
            x += s + gap


# ---------------------------------------------------------------------------
# Motores de dibujo
# ---------------------------------------------------------------------------

def pdf(laminas: list[Lamina], ruta: Path, fu: Fuentes, titulo: str = "") -> Path:
    from reportlab.lib.units import mm
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas

    ruta = Path(ruta)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    c = canvas.Canvas(str(ruta), pagesize=(A3[0] * mm, A3[1] * mm))
    if titulo:
        c.setTitle(titulo)
    c.setCreator("arte-involuntario")
    for L in laminas:
        Hpt = L.alto * mm
        for e in L.elementos:
            if isinstance(e, Foto):
                buf = io.BytesIO()
                e.im.save(buf, "JPEG", quality=90, dpi=(300, 300))
                buf.seek(0)
                c.drawImage(ImageReader(buf), e.x * mm, Hpt - (e.y + e.lado) * mm, e.lado * mm, e.lado * mm)
            elif isinstance(e, Texto):
                c.setFillGray(e.gris)
                nombre = fu.rl(e.estilo)
                if e.tracking:
                    w = fu.ancho(e.texto, e.estilo, e.pt, e.tracking) * mm
                    x = e.x * mm - (w if e.alin == "der" else w / 2 if e.alin == "centro" else 0)
                    t = c.beginText(x, Hpt - e.y * mm)
                    t.setFont(nombre, e.pt)
                    t.setCharSpace(e.tracking * e.pt)
                    t.textOut(e.texto)
                    c.drawText(t)
                else:
                    c.setFont(nombre, e.pt)
                    f = {"izq": c.drawString, "centro": c.drawCentredString, "der": c.drawRightString}[e.alin]
                    f(e.x * mm, Hpt - e.y * mm, e.texto)
            elif isinstance(e, Linea):
                c.setStrokeGray(e.gris)
                c.setLineWidth(e.grosor * mm)
                c.setLineJoin(1)
                c.setLineCap(1)
                pth = c.beginPath()
                for k, (x, y) in enumerate(e.puntos):
                    (pth.moveTo if k == 0 else pth.lineTo)(x * mm, Hpt - y * mm)
                c.drawPath(pth, stroke=1, fill=0)
            elif isinstance(e, Punto):
                c.setFillGray(e.gris if e.relleno else 1)
                c.setStrokeGray(e.gris)
                c.setLineWidth(0.3 * mm)
                c.circle(e.x * mm, Hpt - e.y * mm, e.r * mm, stroke=1, fill=1)
        c.showPage()
    c.save()
    return ruta


def raster(L: Lamina, fu: Fuentes, dpi: int = 120) -> Image.Image:
    k = dpi / 25.4
    lienzo = Image.new("RGB", (round(L.ancho * k), round(L.alto * k)), "white")
    d = ImageDraw.Draw(lienzo)

    def gris(g):
        v = round(255 * g)
        return (v, v, v)

    for e in L.elementos:
        if isinstance(e, Foto):
            lado = round(e.lado * k)
            lienzo.paste(e.im.resize((lado, lado), Image.LANCZOS), (round(e.x * k), round(e.y * k)))
        elif isinstance(e, Texto):
            px = max(4, round(e.pt * PT * k))
            fnt = fu.pil(e.estilo, px)
            ancho_px = fu.ancho(e.texto, e.estilo, e.pt, e.tracking) * k
            x = e.x * k - (ancho_px if e.alin == "der" else ancho_px / 2 if e.alin == "centro" else 0)
            y = e.y * k
            if e.tracking:
                extra = e.tracking * e.pt * PT * k
                for ch in e.texto:
                    d.text((x, y), ch, font=fnt, fill=gris(e.gris), anchor="ls")
                    x += d.textlength(ch, font=fnt) + extra
            else:
                d.text((x, y), e.texto, font=fnt, fill=gris(e.gris), anchor="ls")
        elif isinstance(e, Linea):
            d.line([(x * k, y * k) for x, y in e.puntos], fill=gris(e.gris), width=max(1, round(e.grosor * k)), joint="curve")
        elif isinstance(e, Punto):
            r = e.r * k
            d.ellipse((e.x * k - r, e.y * k - r, e.x * k + r, e.y * k + r),
                      fill=gris(e.gris) if e.relleno else "white", outline=gris(e.gris), width=max(1, round(0.3 * k)))
    return lienzo
