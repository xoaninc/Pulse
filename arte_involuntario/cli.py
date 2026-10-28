"""Línea de órdenes:  ./arte analizar | galeria | laminas | estado | limpiar | todo"""
from __future__ import annotations

import argparse
import shutil
import sys
from datetime import datetime

from . import disco, rutas

AYUDA = """\
Cazador de arte involuntario (G. Clément) y paseos (H. Fulton) en tu fototeca.

Pasos:
  ./arte analizar        lee la fototeca de Fotos y analiza cada imagen (incremental)
  ./arte galeria         abre la galería en el navegador para elegir y montar las láminas
  ./arte laminas         vuelve a generar los PDF con la última selección
  ./arte estado          qué hay analizado y cuánto ocupa
  ./arte limpiar         borra descargas y cachés (con --todo, también modelo e índice)
  ./arte todo            analizar + galeria
"""


def _fecha(s: str | None):
    if not s:
        return None
    return datetime.fromisoformat(s).astimezone()


def cmd_analizar(a) -> None:
    from . import fuentes, indice
    from .modelo import PRESETS, Modelo

    rutas.preparar()
    preset = PRESETS[a.modelo]
    if not any(rutas.MODELOS.rglob("*.safetensors")) and not any(rutas.MODELOS.rglob("*.bin")):
        disco.comprobar(int(preset.descarga_mb * 1.3 * 1024**2), f"descargar el modelo ({preset.descarga_mb} MB)")
    print(f"Espacio libre: {rutas.legible(disco.libre())}")
    desde, hasta = _fecha(a.desde), _fecha(a.hasta)
    if a.carpeta:
        print(f"· Leyendo la carpeta {a.carpeta}…")
        it = fuentes.desde_carpeta(a.carpeta, desde, hasta)
        fuente = "carpeta"
    else:
        print("· Leyendo la fototeca de Fotos (la primera vez puede tardar un minuto)…")
        it = fuentes.desde_fototeca(a.biblioteca, desde, hasta, a.album)
        fuente = "fotos"
    if a.limite:
        import itertools

        it = itertools.islice(it, a.limite)
    r = indice.registrar(it, fuente, borrar_ausentes=not (a.desde or a.hasta or a.album or a.limite))
    print(f"  {r['fotos']} fotos en la fuente")
    import gc

    gc.collect()  # suelta la base de datos de Fotos antes de cargar el modelo (RAM)
    if r["sin_imagen_local"]:
        if getattr(a, "traer_icloud", False):
            from . import icloud

            uuids = indice.sin_imagen()
            icloud.traer(uuids, a.max_icloud)
            for u in uuids:
                c = icloud.ruta_cache(u)
                if c.exists():
                    indice.actualizar_foto(u, ruta_analisis=str(c), ruta_grande=str(c), firma=f"icloud|{c.stat().st_size}")
        else:
            print(f"  {r['sin_imagen_local']} no tienen ninguna imagen en este Mac (solo en iCloud): se saltan.")
            print("  (Si quieres incluirlas: ./arte analizar --traer-icloud  · ~100 KB por foto)")
    disco.comprobar(r["fotos"] * 4096, "guardar el índice")
    modelo = Modelo(a.modelo)
    res = indice.vectorizar(modelo, lote=a.lote)
    est = indice.estadisticas()
    print(f"✓ Analizadas {est['analizadas'].get(modelo.clave, 0)} fotos ({res['errores']} con error).")
    print("  Siguiente paso:  ./arte galeria")


def cmd_galeria(a) -> None:
    from .servidor import servir

    servir(a.modelo, a.puerto, abrir=not a.no_abrir)


def cmd_laminas(a) -> None:
    from .generar import generar

    r = generar(descargar=not a.sin_descargar)
    for k, v in r["ficheros"].items():
        if k != "previas":
            print(f"  {k}: {v}")
    for av in r["avisos"]:
        print(f"  ⚠ {av}")


def cmd_estado(a) -> None:
    from . import indice

    rutas.preparar()
    est = indice.estadisticas()
    print(f"Fuente: {est['fuente'] or '—'} · fotos registradas: {est['fotos']}")
    print(f"  sin imagen local (solo iCloud): {est['sin_imagen_local']}")
    for m, n in est["analizadas"].items():
        print(f"  analizadas con {m}: {n}")
    print(f"  con error al abrir: {est['errores']}")
    print("Espacio:")
    for k, v in disco.resumen().items():
        print(f"  {k:18s} {rutas.legible(v)}")


def cmd_limpiar(a) -> None:
    borrar = [rutas.ORIGINALES, rutas.MINIATURAS_ICLOUD, rutas.TEXTOS_CACHE]
    if a.todo:
        borrar += [rutas.MODELOS, rutas.BD, rutas.BD.with_suffix(".sqlite-wal"), rutas.BD.with_suffix(".sqlite-shm")]
    liberado = 0
    for p in borrar:
        if p.is_dir():
            liberado += rutas.tam_carpeta(p)
            shutil.rmtree(p, ignore_errors=True)
        elif p.exists():
            liberado += p.stat().st_size
            p.unlink()
    print(f"Liberados {rutas.legible(liberado)}." + ("" if a.todo else " (Usa --todo para borrar también el modelo y el índice.)"))
    print("Tu selección (datos/seleccion.json) y las láminas (salida/) se conservan.")


def cmd_todo(a) -> None:
    cmd_analizar(a)
    cmd_galeria(a)


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(prog="arte", description=AYUDA, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd")

    def comunes(p):
        p.add_argument("--modelo", choices=["rapido", "preciso"], default="rapido",
                       help="rapido (por defecto) o preciso (más lento, descarga 1,7 GB)")

    p = sub.add_parser("analizar", help="analiza la fototeca")
    comunes(p)
    p.add_argument("--carpeta", help="analizar una carpeta en vez de la app Fotos")
    p.add_argument("--biblioteca", help="ruta a otra .photoslibrary")
    p.add_argument("--desde", help="solo fotos desde esta fecha (AAAA-MM-DD)")
    p.add_argument("--hasta", help="solo fotos hasta esta fecha (AAAA-MM-DD)")
    p.add_argument("--album", help="solo este álbum de Fotos")
    p.add_argument("--limite", type=int, help="(pruebas) analizar solo N fotos")
    p.add_argument("--lote", type=int, default=32)
    p.add_argument("--traer-icloud", action="store_true",
                   help="pide a iCloud miniaturas reducidas (~100 KB) de las fotos sin ninguna imagen local")
    p.add_argument("--max-icloud", type=int, default=None, help="máximo de miniaturas a traer de iCloud")
    p.set_defaults(fn=cmd_analizar)

    p = sub.add_parser("galeria", help="abre la galería en el navegador")
    comunes(p)
    p.add_argument("--puerto", type=int, default=8765)
    p.add_argument("--no-abrir", action="store_true")
    p.set_defaults(fn=cmd_galeria)

    p = sub.add_parser("laminas", help="genera los PDF con la selección guardada")
    p.add_argument("--sin-descargar", action="store_true", help="no descargar originales de iCloud")
    p.set_defaults(fn=cmd_laminas)

    p = sub.add_parser("estado", help="resumen del índice y del espacio usado")
    p.set_defaults(fn=cmd_estado)

    p = sub.add_parser("limpiar", help="libera espacio")
    p.add_argument("--todo", action="store_true", help="borra también el modelo descargado y el índice")
    p.set_defaults(fn=cmd_limpiar)

    p = sub.add_parser("todo", help="analizar y abrir la galería")
    comunes(p)
    for arg in ("--carpeta", "--biblioteca", "--desde", "--hasta", "--album"):
        p.add_argument(arg)
    p.add_argument("--limite", type=int)
    p.add_argument("--lote", type=int, default=32)
    p.add_argument("--traer-icloud", action="store_true")
    p.add_argument("--max-icloud", type=int, default=None)
    p.add_argument("--puerto", type=int, default=8765)
    p.add_argument("--no-abrir", action="store_true")
    p.set_defaults(fn=cmd_todo)

    a = ap.parse_args(argv)
    if not getattr(a, "fn", None):
        ap.print_help()
        return
    try:
        a.fn(a)
    except disco.SinEspacio as e:
        print(f"\n✗ {e}")
        sys.exit(2)
    except KeyboardInterrupt:
        print("\nCancelado.")
        sys.exit(130)
    except RuntimeError as e:
        print(f"\n✗ {e}")
        sys.exit(1)
