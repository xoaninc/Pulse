"""Paquete para pedir ayuda: hojas de contacto con lo que la app propone en cada categoría, tu
selección y los paseos detectados, más un resumen en texto. Se guarda en salida/informe/ y no se
envía a ningún sitio: tú decides qué imágenes compartir."""
from __future__ import annotations

import json
import platform
import shutil
import subprocess
import sys
from collections import Counter

from PIL import Image, ImageDraw, ImageFont, ImageOps

from . import generar, imagenes, indice, rutas

LADO = 180       # px de cada miniatura
COLS = 6
POR_CATEGORIA = 30
VERDE = (40, 160, 70)


def _fuente(pt: int):
    for nombre in ("Helvetica.ttc", "Arial.ttf", "DejaVuSans.ttf", "LiberationSans-Regular.ttf"):
        try:
            return ImageFont.truetype(nombre, pt)
        except Exception:
            continue
    try:
        return ImageFont.load_default(size=pt)
    except TypeError:
        return ImageFont.load_default()


def _mini(ix, uuid: str) -> Image.Image:
    f = ix.foto(uuid) or indice.foto_cualquiera(uuid)
    ruta = f and (f.get("ruta_analisis") or f.get("ruta_grande") or f.get("ruta_original"))
    try:
        im = imagenes.abrir(ruta, LADO * 2, color=True)
        return ImageOps.fit(im, (LADO, LADO))
    except Exception:
        im = Image.new("RGB", (LADO, LADO), (225, 225, 225))
        ImageDraw.Draw(im).text((8, LADO // 2 - 8), "sin imagen", fill=(120, 120, 120), font=_fuente(14))
        return im


def _hoja(titulo: str, celdas: list[tuple[str, str, bool]], ix, cols: int = COLS) -> Image.Image:
    """celdas = [(uuid, texto bajo la foto, marcada)]."""
    alto_txt = 34
    filas = max(1, -(-len(celdas) // cols))
    hoja = Image.new("RGB", (cols * (LADO + 10) + 10, 50 + filas * (LADO + alto_txt + 10)), "white")
    d = ImageDraw.Draw(hoja)
    d.text((10, 12), titulo, fill="black", font=_fuente(20))
    f_txt = _fuente(12)
    for k, (uuid, texto, marcada) in enumerate(celdas):
        x, y = 10 + (k % cols) * (LADO + 10), 50 + (k // cols) * (LADO + alto_txt + 10)
        hoja.paste(_mini(ix, uuid), (x, y))
        if marcada:
            d.rectangle((x - 3, y - 3, x + LADO + 2, y + LADO + 2), outline=VERDE, width=5)
        for n, linea in enumerate(texto.split("\n")[:2]):
            d.text((x, y + LADO + 3 + n * 15), linea[:30], fill="black", font=f_txt)
    return hoja


def crear(app) -> list:
    """`app` es la de servidor.App (índice, puntuación y paseos ya cargados)."""
    dest = rutas.SALIDA / "informe"
    shutil.rmtree(dest, ignore_errors=True)
    dest.mkdir(parents=True)
    ix, pt, pa = app.ix, app.pt, app.pa
    sel = generar.leer_seleccion()
    elegidas = {x["uuid"]: x.get("categoria") for x in sel.get("arte", [])}
    nombres = {c["id"]: c["nombre"] for c in app.tx.cfg["categorias"]}
    texto: list[str] = []
    fotos = ix.fotos
    est = indice.estadisticas()

    texto += ["INFORME · cazador de arte involuntario", "",
              f"macOS {platform.mac_ver()[0] or '-'} · {platform.machine()} · Python {sys.version.split()[0]}",
              f"modelo: {app.preset} ({app.clave})",
              f"fotos en la galería: {len(fotos)} · registradas: {est.get('fotos')} · analizadas: {est.get('analizadas')}",
              f"con GPS: {sum(1 for f in fotos if f.get('lat') is not None)} · con etiquetas de Fotos: "
              f"{sum(1 for f in fotos if f.get('etiquetas'))} · solo en iCloud: {sum(1 for f in fotos if f.get('en_icloud'))} · "
              f"con nota estética: {sum(1 for f in fotos if f.get('estetica') is not None)}",
              "", "Etiquetas de Fotos más frecuentes: " +
              ", ".join(f"{e} {n}" for e, n in Counter(e for f in fotos for e in (f.get("etiquetas") or [])).most_common(40)), ""]

    hechas = []
    for c in pt.cats:
        cands = app.cache_cand[c][:POR_CATEGORIA]
        celdas = []
        texto.append(f"== {nombres.get(c, c)}: {sum(1 for x in app.cache_cand[c] if x['puntos'] > 1.0)} candidatas con más de 1 punto")
        for r, d in enumerate(cands, 1):
            marcada = elegidas.get(d["uuid"]) == c
            celdas.append((d["uuid"], f"#{r}  {d['puntos']:.1f}{'  ✓' if marcada else ''}", marcada))
            texto.append(f"  #{r:<3} {d['puntos']:5.2f}  {d['uuid'][:8]}  sugerida={d.get('sugerida')}  "
                         f"etiquetas={','.join(d.get('etiquetas') or []) or '-'}")
        n = len(hechas) + 1
        _hoja(f"{n}. {nombres.get(c, c).upper()} · las {len(cands)} primeras (verde = elegida)", celdas, ix) \
            .save(dest / f"{n:02d}_{c}.jpg", quality=80)
        hechas.append(c)
        texto.append("")

    # tu selección
    celdas = [(x["uuid"], f"{k:02d} {nombres.get(x.get('categoria'), x.get('categoria') or '?')}", False)
              for k, x in enumerate(sel.get("arte", []), 1)]
    ps = sel.get("paseo", {})
    celdas += [(x["uuid"], f"P{k:02d} {x.get('frase') or ''}", False) for k, x in enumerate(ps.get("fotos", []), 1)]
    if celdas:
        _hoja(f"Tu selección: {len(sel.get('arte', []))} de arte + {len(ps.get('fotos', []))} del paseo «{ps.get('titulo') or ''}»",
              celdas, ix).save(dest / "09_seleccion.jpg", quality=80)
    texto += ["== Selección", f"  arte: {dict(Counter(nombres.get(x.get('categoria'), '?') for x in sel.get('arte', [])))}",
              f"  paseo: {len(ps.get('fotos', []))} fotos · título «{ps.get('titulo') or ''}» · línea «{ps.get('linea') or ''}»", ""]

    # paseos detectados
    paseos = pa.detectar()[:8]
    celdas = []
    texto.append(f"== Paseos detectados: {len(pa.detectar())}")
    for k, p in enumerate(paseos, 1):
        texto.append(f"  {k}. {p.get('dia')} · {p.get('fotos')} fotos ({p.get('naturales')} de naturaleza) · "
                     f"{p.get('km')} km · {p.get('horas')} h · {p.get('lugar') or ''}")
        for u in (p.get("portada") or [])[:COLS]:
            celdas.append((u, f"{k}. {p.get('dia')} · {p.get('km')} km", False))
    if celdas:
        _hoja("Paseos detectados (6 fotos de cada uno, en orden)", celdas, ix).save(dest / "10_paseos.jpg", quality=80)

    (dest / "resumen.txt").write_text("\n".join(texto) + "\n", encoding="utf-8")
    (dest / "seleccion.json").write_text(json.dumps({k: v for k, v in sel.items() if k != "autor"}, ensure_ascii=False, indent=1),
                                         encoding="utf-8")
    return sorted(dest.iterdir())


def abrir_carpeta() -> None:
    if sys.platform == "darwin":
        subprocess.run(["open", str(rutas.SALIDA / "informe")], check=False)
