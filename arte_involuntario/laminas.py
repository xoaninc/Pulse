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
PPI_MINIMO = 200     # por debajo, la foto se verá blanda impresa

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
    """Resuelve la tipografía y la registra en reportlab y en Pillow. Solo se acepta una familia
    si reportlab puede incrustarla (así el PDF y las vistas previas usan la misma letra)."""

    def __init__(self, preferida: str | None = None):
        self.familia = "Helvetica"
        self.archivos: dict[str, tuple[str, int]] = {}
        self._rl: dict[str, str] = {}
        self._pil_cache: dict = {}
        opciones: list[tuple[str, dict[str, tuple[str, int]]]] = []
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
            opciones.append((familia, {k: (ruta, i) for k, i in idx.items()}))
        for familia, rutas_ in CANDIDATAS_SUELTAS:
            if all(os.path.exists(r) for r in rutas_.values()):
                opciones.append((familia, {k: (r, 0) for k, r in rutas_.items()}))
        for familia, archivos in opciones:
            rl = self._registrar_reportlab(familia, archivos)
            if rl:
                self.familia, self.archivos, self._rl = familia, archivos, rl
                break
        if not self._rl:  # sin ninguna TTF utilizable: las base-14 de PDF
            self._rl = {"normal": "Helvetica", "negrita": "Helvetica-Bold", "cursiva": "Helvetica-Oblique"}

    @staticmethod
    def _registrar_reportlab(familia: str, archivos: dict[str, tuple[str, int]]) -> dict[str, str] | None:
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont

        out = {}
        for estilo, (ruta, idx) in archivos.items():
            nombre = f"AI-{familia.replace(' ', '')}-{estilo}"
            try:
                if nombre not in pdfmetrics.getRegisteredFontNames():
                    if ruta.lower().endswith(".ttc"):
                        pdfmetrics.registerFont(TTFont(nombre, ruta, subfontIndex=idx))
                    else:
                        pdfmetrics.registerFont(TTFont(nombre, ruta))
                out[estilo] = nombre
            except Exception:
                if estilo == "normal":
                    return None  # esta familia no se puede incrustar: probar la siguiente
                out[estilo] = None
        for k in ("negrita", "cursiva"):
            out[k] = out.get(k) or out["normal"]
        return out

    def rl(self, estilo: str) -> str:
        return self._rl.get(estilo) or self._rl["normal"]

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
    avisos: list = field(default_factory=list)
    ancho: float = A3[0]
    alto: float = A3[1]


# ---------------------------------------------------------------------------
# Utilidades de texto
# ---------------------------------------------------------------------------

def _trocear(palabra: str, fu: Fuentes, estilo: str, pt: float, ancho: float, tracking: float) -> list[str]:
    """Parte una palabra que no cabe en la columna (URL, compuesto con guiones…)."""
    trozos, actual = [], ""
    for ch in palabra:
        if actual and fu.ancho(actual + ch + "-", estilo, pt, tracking) > ancho:
            trozos.append(actual + "-")
            actual = ch
        else:
            actual += ch
    return trozos + ([actual] if actual else [])


def partir(texto: str, fu: Fuentes, estilo: str, pt: float, ancho: float, tracking: float = 0) -> list[str]:
    palabras: list[str] = []
    for p in texto.split():
        palabras += _trocear(p, fu, estilo, pt, ancho, tracking) if fu.ancho(p, estilo, pt, tracking) > ancho else [p]
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
    """Reduce un poco el cuerpo si hace falta; si aun así no cabe, corta con «…».
    Devuelve (líneas, cuerpo, recortado)."""
    while True:
        lineas = partir(texto, fu, estilo, pt, ancho, tracking)
        if len(lineas) <= max_lineas or pt <= pt_min:
            recortado = len(lineas) > max_lineas
            if recortado:
                lineas = lineas[:max_lineas]
                lineas[-1] = lineas[-1].rstrip(".,;: ") + "…"
            return lineas, pt, recortado
        pt -= 0.5


def preparar_foto(im: Image.Image, recorte: dict | None, lado_mm: float, bn: bool, contraste: str, dpi: int = 300):
    """Recorta en cuadrado, reduce a la resolución de impresión y (si toca) pasa a B/N.
    Devuelve (imagen, píxeles reales del recorte, para calcular la resolución efectiva)."""
    r = recorte or {}
    cuadrada = imagenes.recorte_cuadrado(im, float(r.get("cx", 0.5)), float(r.get("cy", 0.5)), float(r.get("zoom", 1.0)))
    px = cuadrada.width
    objetivo = round(lado_mm / 25.4 * dpi)
    if cuadrada.width > objetivo:
        cuadrada = cuadrada.resize((objetivo, objetivo), Image.LANCZOS)
    if bn:
        cuadrada = imagenes.a_blanco_y_negro(cuadrada, contraste)
    return cuadrada, px


def _textos_mixtos(L: Lamina, fu: Fuentes, x: float, y: float, partes: list[tuple[str, str]], pt: float, gris: float):
    """Una línea con tramos en distintos estilos (p. ej. título del libro en cursiva)."""
    for texto, estilo in partes:
        L.elementos.append(Texto(x, y, texto, estilo, pt, gris=gris))
        x += fu.ancho(texto, estilo, pt)


# ---------------------------------------------------------------------------
# Lámina tipo 1: arte involuntario (2 filas x 3 columnas, color)
# ---------------------------------------------------------------------------

LADO_ARTE = 106.0


def maquetar_arte(fotos: list[dict], fu: Fuentes, autor: str = "", nombres: dict | None = None,
                  cabecera: bool = True) -> list[Lamina]:
    """`fotos`: dicts con im (PIL), categoria, pie. Devuelve 4 láminas (o las que hagan falta)."""
    nombres = nombres or {}
    W, H = A3
    s, gap_x, gap_y, cap = LADO_ARTE, 15.0, 12.0, 15.0
    ancho_rejilla = 3 * s + 2 * gap_x
    x0 = (W - ancho_rejilla) / 2
    y0 = 31.0
    paginas = max(1, math.ceil(len(fotos) / 6))
    laminas = []
    for p in range(paginas):
        L = Lamina()
        if cabecera:
            L.elementos.append(Texto(x0, 16.5, "COLECCIÓN FOTOGRÁFICA DE ARTE INVOLUNTARIO", "negrita", 9.5, tracking=0.12))
            _textos_mixtos(L, fu, x0, 21.8, [("a partir del ", "normal"), ("Breve tratado del arte involuntario", "cursiva"),
                                             (" de Gilles Clément", "normal")], 7.5, 0.3)
            der = f"{autor.upper()}  ·  " if autor else ""
            L.elementos.append(Texto(x0 + ancho_rejilla, 16.5, f"{der}LÁMINA {p + 1}/{paginas}", "normal", 8.5, "der", tracking=0.1))
            L.elementos.append(Texto(x0 + ancho_rejilla, 21.8, "Ejercicio 2.3 · Fotografía · Observar/Documentar", "normal", 7, "der", gris=0.4))
            L.elementos.append(Linea([(x0, 25.0), (x0 + ancho_rejilla, 25.0)], 0.15, 0.55))
        for k, f in enumerate(fotos[p * 6:(p + 1) * 6]):
            fila, col = divmod(k, 3)
            x = x0 + col * (s + gap_x)
            y = y0 + fila * (s + cap + gap_y)
            L.elementos.append(Foto(x, y, s, f["im"]))
            cat = nombres.get(f["categoria"], f["categoria"]).upper()
            L.elementos.append(Texto(x, y + s + 5.6, cat, "negrita", 9.5, tracking=0.15))
            L.elementos.append(Texto(x + s, y + s + 5.6, f"{p * 6 + k + 1:02d}", "normal", 7, "der", gris=0.45, tracking=0.1))
            pie = (f.get("pie") or "").strip()
            if pie:
                lineas, pt, cortado = texto_en_caja(pie, fu, "normal", 7.5, s, 2, 7.0)
                for j, ln in enumerate(lineas):
                    L.elementos.append(Texto(x, y + s + 10.0 + j * pt * PT * 1.3, ln, "normal", pt, gris=0.3))
                if cortado:
                    L.avisos.append(f"Lámina {p + 1}, foto {k + 1} ({cat.capitalize()}): el pie no cabe en dos líneas "
                                    "y se ha cortado; acórtalo.")
        laminas.append(L)
    return laminas


# ---------------------------------------------------------------------------
# Lámina tipo 2: paseo al estilo Hamish Fulton (B/N)
# ---------------------------------------------------------------------------

CAP_PASEO = 18.0     # alto reservado bajo cada foto: datos + hasta 3 líneas de frase
GAP_PASEO = 7.0
PT_FRASE = 7.0


def _rejilla(n: int, ancho: float, alto: float, cap: float, gap: float) -> tuple[int, int, float]:
    mejor = (1, n, 0.0)
    for filas in (1, 2, 3):
        cols = math.ceil(n / filas)
        s = min((ancho - (cols - 1) * gap) / cols, (alto - filas * cap - (filas - 1) * gap) / filas)
        if s > mejor[2]:
            mejor = (filas, cols, s)
    return mejor


def _km_redondo(km: float) -> float:
    for v in (0.1, 0.2, 0.5, 1, 2, 5, 10, 20, 50):
        if v >= km:
            return v
    return 100.0


def _dibujo_recorrido(L: Lamina, fotos: list[dict], x: float, y: float, w: float, h: float, fu: Fuentes) -> bool:
    """Perfil de altitud (si hay altitudes) o planta del recorrido desde el GPS, como los murales
    de Fulton, con el número de cada foto. Ocupa la caja (x, y, w, h)."""
    from .paseos import km_entre, num_es

    n = len(fotos)
    marcas = ["O" if k == 0 else ("F" if k == n - 1 else f"{k + 1:02d}") for k in range(n)]
    con_alt = [(k, f) for k, f in enumerate(fotos) if f.get("alt") is not None and f.get("km") is not None]
    con_gps = [(k, f) for k, f in enumerate(fotos) if f.get("lat") is not None and f.get("lon") is not None]
    alto_util = h - 7
    if len(con_alt) >= max(4, n * 0.6):
        xs = [f["km"] for _, f in con_alt]
        ys = [f["alt"] for _, f in con_alt]
        dx, dy = (max(xs) - min(xs)) or 1e-9, (max(ys) - min(ys)) or 1.0
        pts = [(x + (a - min(xs)) / dx * w, y + 3 + alto_util - (b - min(ys)) / dy * alto_util) for a, b in zip(xs, ys)]
        idx = [k for k, _ in con_alt]
        etiqueta = (f"PERFIL DE LA CAMINATA · {num_es(min(ys), 0)}–{num_es(max(ys), 0)} M · "
                    f"{num_es(max(xs) - min(xs))} KM")
    elif len(con_gps) >= 3:
        lat0 = sum(f["lat"] for _, f in con_gps) / len(con_gps)
        kx = 111.32 * math.cos(math.radians(lat0))  # km por grado de longitud
        xs = [f["lon"] * kx for _, f in con_gps]
        ys = [f["lat"] * 110.57 for _, f in con_gps]
        dx, dy = (max(xs) - min(xs)) or 1e-6, (max(ys) - min(ys)) or 1e-6
        caja = min(w, 120.0)
        esc = min(caja / dx, alto_util / dy)  # mm por km, misma escala en x e y
        ox = x + (w - dx * esc) / 2
        oy = y + 3 + (alto_util + dy * esc) / 2
        pts = [(ox + (a - min(xs)) * esc, oy - (b - min(ys)) * esc) for a, b in zip(xs, ys)]
        idx = [k for k, _ in con_gps]
        # barra de escala y norte
        km_barra = _km_redondo(max(0.05, dx / 4))
        bx = x + w - km_barra * esc
        L.elementos.append(Linea([(bx, y + h + 1.2), (x + w, y + h + 1.2)], 0.35))
        L.elementos.append(Texto(x + w, y + h + 3.6, f"{num_es(km_barra, 1 if km_barra < 1 else 0)} KM", "normal", 5.5, "der", gris=0.35))
        L.elementos.append(Linea([(x + w - 1.2, y + 4.5), (x + w - 1.2, y + 0.8)], 0.3))
        L.elementos.append(Texto(x + w - 1.2, y + 7.6, "N", "normal", 5.5, "centro", gris=0.35))
        etiqueta = f"RECORRIDO · {num_es(sum(km_entre((con_gps[i][1]['lat'], con_gps[i][1]['lon']), (con_gps[i + 1][1]['lat'], con_gps[i + 1][1]['lon'])) for i in range(len(con_gps) - 1)))} KM"
    else:
        return False
    L.elementos.append(Linea(pts, 0.4))
    for k, (px, py) in zip(idx, pts):
        if k == 0:
            L.elementos.append(Punto(px, py, 1.2, True))
        elif k == n - 1:
            L.elementos.append(Punto(px, py, 1.2, False))
        else:
            L.elementos.append(Punto(px, py, 0.5, True))
        if k not in (0, n - 1):
            L.elementos.append(Texto(px, py - 2.0, marcas[k], "normal", 5, "centro", gris=0.4))
    L.elementos.append(Texto(x, y + h + 2.6, etiqueta, "normal", 6, tracking=0.12, gris=0.35))
    return True


def datos_foto(f: dict) -> str:
    from datetime import datetime

    from .paseos import num_es

    partes = []
    try:
        partes.append(datetime.fromisoformat(f["fecha"]).strftime("%H:%M"))
    except Exception:
        pass
    if f.get("km") is not None:
        partes.append(f"KM {num_es(float(f['km']))}")
    if f.get("alt") is not None:
        partes.append(f"{num_es(float(f['alt']), 0)} M")
    return " · ".join(partes)


def maquetar_paseo(fotos: list[dict], fu: Fuentes, titulo: str, linea: str, autor: str = "",
                   mayusculas: bool = True, dibujo: bool = True, cabecera: bool = True,
                   diseno: str = "rejilla", datos: bool = True) -> list[Lamina]:
    """`fotos`: dicts con im (ya en B/N), frase y opcionalmente fecha/km/alt/lat/lon. Siempre 2 láminas
    que se leen como un díptico: misma franja superior y misma rejilla en las dos.
    Como en las obras de Fulton: PALABRA-TÍTULO y línea de la caminata centradas arriba; bajo cada
    foto, una línea de datos (ORIGEN/nº · hora · km · altitud) y la frase del suceso."""
    W, H = A3
    n = len(fotos)
    corte = math.ceil(n / 2)
    grupos = [fotos[:corte], fotos[corte:]]
    margen = 20.0
    top = 16.0
    tit = (titulo or "").strip().upper()
    pt_tit = 40
    while tit and fu.ancho(tit, "negrita", pt_tit, 0.1) > W - 2 * margen and pt_tit > 18:
        pt_tit -= 2
    alto_tit = pt_tit * PT * 0.78 + 7.5 if tit else 4
    lns, ptl, _ = texto_en_caja(linea.upper(), fu, "normal", 9, W - 2 * margen - 40, 2, 7, tracking=0.08) if linea else ([], 9, False)
    alto_linea = (len(lns) - 1) * ptl * PT * 1.4 + 2 if lns else 0
    alto_dibujo = 24.0 if dibujo else 0.0
    # franja superior común: lámina 1 = título + línea; lámina 2 = línea + dibujo del recorrido
    franja = max(alto_tit + alto_linea, 4 + alto_linea + (alto_dibujo + 9 if dibujo else 0))
    zona_y = top + franja + 8
    alto = H - zona_y - 15
    ancho = W - 2 * margen
    opciones = dict(mayusculas=mayusculas, datos=datos)
    laminas = []

    if diseno == "crece":
        escala = _escala_crece(grupos, corte, n, ancho, alto)
    else:
        filas, cols, s = _rejilla(max(len(g) for g in grupos), ancho, alto, CAP_PASEO, GAP_PASEO)

    for p, grupo in enumerate(grupos):
        L = Lamina()
        y_linea = top + (alto_tit if p == 0 else 4)
        if p == 0 and tit:
            L.elementos.append(Texto(W / 2, top + pt_tit * PT * 0.78, tit, "negrita", pt_tit, "centro", tracking=0.1))
        for j, ln in enumerate(lns):
            L.elementos.append(Texto(W / 2, y_linea + j * ptl * PT * 1.4, ln, "normal", ptl, "centro", tracking=0.08))
        if p == 1 and dibujo:
            y_d = y_linea + alto_linea + 5
            if not _dibujo_recorrido(L, fotos, margen + 20, y_d, W - 2 * margen - 40, alto_dibujo, fu):
                L.avisos.append("Paseo: las fotos no tienen GPS, así que no se dibuja el recorrido.")
        if cabecera:
            L.elementos.append(Texto(margen, H - 9, "PASEO FOTOGRÁFICO SEGÚN LAS PAUTAS DE HAMISH FULTON", "normal", 6.5, gris=0.45, tracking=0.12))
            der = f"{autor.upper()}  ·  " if autor else ""
            L.elementos.append(Texto(W - margen, H - 9, f"{der}{p + 1}/2", "normal", 6.5, "der", gris=0.45, tracking=0.12))
        if grupo:
            if diseno == "crece":
                _maquetar_crece(L, grupo, p, corte, n, fu, margen, zona_y, ancho, alto, escala, opciones)
            else:
                usado_h = filas * (s + CAP_PASEO) + (filas - 1) * GAP_PASEO
                y0 = zona_y + (alto - usado_h) / 2
                for k, f in enumerate(grupo):
                    fila, col = divmod(k, cols)
                    en_fila = min(cols, len(grupo) - fila * cols)       # última fila incompleta: centrada
                    usado_w = en_fila * s + (en_fila - 1) * GAP_PASEO
                    x = (W - usado_w) / 2 + col * (s + GAP_PASEO)
                    y = y0 + fila * (s + CAP_PASEO + GAP_PASEO)
                    _foto_paseo(L, f, x, y, s, p * corte + k, n, fu, **opciones)
        laminas.append(L)
    return laminas


def _foto_paseo(L, f, x, y, s, num, n, fu, mayusculas=True, datos=True):
    L.elementos.append(Foto(x, y, s, f["im"]))
    y1 = y + s + 4.4
    pt_m = 7.0
    if num == 0 or num == n - 1:
        L.elementos.append(Punto(x + 1.0, y1 - 0.95, 0.95, relleno=(num == 0)))
        marca, xm = ("ORIGEN" if num == 0 else "FINAL"), x + 2.9
    else:
        marca, xm = f"{num + 1:02d}", x
    L.elementos.append(Texto(xm, y1, marca, "negrita", pt_m, tracking=0.12))
    if datos:
        d = datos_foto(f)
        if d:
            xd = xm + fu.ancho(marca, "negrita", pt_m, 0.12) + 2.2
            L.elementos.append(Texto(xd, y1, "·  " + d, "normal", 6.5, gris=0.45, tracking=0.06))
    frase = (f.get("frase") or "").strip()
    if mayusculas:
        frase = frase.upper()
    if not frase:
        L.avisos.append(f"Paseo, foto {marca}: no tiene frase (el ejercicio pide una bajo cada foto).")
        return
    tr = 0.04 if mayusculas else 0
    lineas, pt, cortado = texto_en_caja(frase, fu, "normal", PT_FRASE, s, 3, 6.5, tracking=tr)
    for j, ln in enumerate(lineas):
        L.elementos.append(Texto(x, y + s + 8.6 + j * pt * PT * 1.32, ln, "normal", pt, tracking=tr))
    if cortado:
        L.avisos.append(f"Paseo, foto {marca}: la frase no cabe en tres líneas y se ha cortado; acórtala.")


def _pesos_crece(corte: int, n_total: int, p: int, m: int) -> list[float]:
    return [1 + 0.6 * ((p * corte + k) / max(1, n_total - 1)) for k in range(m)]


def _filas_crece(m: int) -> list[list[int]]:
    filas = 2 if m > 5 else 1
    por_fila = math.ceil(m / filas)
    return [list(range(fi * por_fila, min(m, (fi + 1) * por_fila))) for fi in range(filas)]


def _escala_crece(grupos, corte, n_total, ancho, alto) -> float:
    """Una única escala para las dos láminas: el lado de cada foto depende solo de su posición
    en la caminata, así el crecimiento es continuo de ORIGEN a FINAL."""
    gap, sep = 5.0, 8.0
    esc = float("inf")
    for p, grupo in enumerate(grupos):
        m = len(grupo)
        if not m:
            continue
        pesos = _pesos_crece(corte, n_total, p, m)
        filas = _filas_crece(m)
        alto_fila = (alto - (len(filas) - 1) * sep) / len(filas)
        for fila in filas:
            suma = sum(pesos[k] for k in fila)
            esc = min(esc, (ancho - gap * (len(fila) - 1)) / suma, (alto_fila - CAP_PASEO) / max(pesos[k] for k in fila))
    return esc


def _maquetar_crece(L, grupo, p, corte, n_total, fu, margen, zona_y, ancho, alto, esc, opciones):
    """Variante «Within Sight» (Helen Sear): las fotos crecen a lo largo del recorrido, alineadas abajo."""
    m = len(grupo)
    gap, sep = 5.0, 8.0
    pesos = _pesos_crece(corte, n_total, p, m)
    filas = _filas_crece(m)
    alto_fila = (alto - (len(filas) - 1) * sep) / len(filas)
    for fi, fila in enumerate(filas):
        usado = sum(pesos[k] * esc for k in fila) + gap * (len(fila) - 1)
        x = margen + (ancho - usado) / 2
        base = zona_y + fi * (alto_fila + sep) + alto_fila - CAP_PASEO
        for k in fila:
            s = pesos[k] * esc
            _foto_paseo(L, grupo[k], x, base - s, s, p * corte + k, n_total, fu, **opciones)
            x += s + gap


# ---------------------------------------------------------------------------
# Motores de dibujo
# ---------------------------------------------------------------------------

def pdf(laminas: list[Lamina], ruta: Path, fu: Fuentes, titulo: str = "", autor: str = "") -> Path:
    from reportlab.lib.units import mm
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas

    ruta = Path(ruta)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    c = canvas.Canvas(str(ruta), pagesize=(A3[0] * mm, A3[1] * mm), initialFontName=fu.rl("normal"), initialFontSize=9)
    if titulo:
        c.setTitle(titulo)
    if autor:
        c.setAuthor(autor)
    c.setCreator("arte-involuntario")
    for L in laminas:
        Hpt = L.alto * mm
        for e in L.elementos:
            if isinstance(e, Foto):
                buf = io.BytesIO()
                im = e.im if e.im.mode in ("L", "RGB") else e.im.convert("RGB")
                im.save(buf, "JPEG", quality=90, dpi=(300, 300))  # modo L → DeviceGray en el PDF
                buf.seek(0)
                c.drawImage(ImageReader(buf), e.x * mm, Hpt - (e.y + e.lado) * mm, e.lado * mm, e.lado * mm)
            elif isinstance(e, Texto):
                # Siempre con objeto de texto y espaciado explícito: en PDF el espaciado entre
                # letras (Tc) es estado gráfico y se arrastraría al texto siguiente.
                c.setFillGray(e.gris)
                w = fu.ancho(e.texto, e.estilo, e.pt, e.tracking) * mm
                x = e.x * mm - (w if e.alin == "der" else w / 2 if e.alin == "centro" else 0)
                t = c.beginText(x, Hpt - e.y * mm)
                t.setFont(fu.rl(e.estilo), e.pt)
                t.setCharSpace(e.tracking * e.pt)
                t.textOut(e.texto)
                c.drawText(t)
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
            lienzo.paste(e.im.convert("RGB").resize((lado, lado), Image.LANCZOS), (round(e.x * k), round(e.y * k)))
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
