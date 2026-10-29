"""Línea de órdenes:  ./arte analizar | galeria | laminas | estado | limpiar | todo"""
from __future__ import annotations

import argparse
import shutil
import sys
import time
from datetime import datetime, timedelta

from . import disco, rutas

AYUDA = """\
Cazador de arte involuntario (G. Clément) y paseos (H. Fulton) en tu fototeca.

Pasos:
  ./arte analizar        lee la fototeca de Fotos y analiza cada imagen (incremental)
  ./arte galeria         abre la galería en el navegador para elegir y montar las láminas
  ./arte laminas         vuelve a generar los PDF con la última selección
  ./arte estado          qué hay analizado y cuánto ocupa
  ./arte limpiar         borra cachés y descargas que ya no se usan (con --todo, también modelo e índice)
  ./arte todo            analizar (si hace falta) + galeria
"""

HORAS_RELECTURA = 12  # `todo` no vuelve a leer la fototeca si se leyó hace menos de esto


def _fecha(s: str | None, fin: bool = False):
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s.strip())
    except ValueError:
        raise RuntimeError(f"Fecha «{s}» no válida: usa AAAA-MM-DD, por ejemplo 2024-05-11") from None
    if fin and len(s.strip()) <= 10:
        dt += timedelta(days=1)  # --hasta 2024-05-11 incluye todo ese día
    return dt.astimezone()


def _modelo_recordado(avisar: bool = False) -> str:
    """El último modelo con el que se terminó de analizar. Si no tiene ninguna foto de la fuente
    actual (p. ej. se cortó el primer análisis, hecho con otro modelo), el que tenga más."""
    from . import indice
    from .modelo import PRESETS, clave_modelo

    m = indice.modelo_usado() or "rapido"
    if not rutas.BD.exists():
        return m
    analizadas = indice.estadisticas()["analizadas"]
    try:
        if analizadas.get(clave_modelo(m)):
            return m
    except ValueError:
        pass
    clave, n = max(analizadas.items(), key=lambda kv: kv[1], default=(None, 0))
    if not n:
        return m
    otro = next((p for p in PRESETS if clave_modelo(p) == clave), clave)
    if avisar:
        print(f"(No hay fotos analizadas con el modelo «{m}»: uso «{otro}», que tiene {n}.)")
    return otro


def _modelo_de(a, avisar: bool = False) -> str:
    """El modelo indicado, o el último con el que se analizó."""
    if getattr(a, "modelo", None):
        return a.modelo
    return _modelo_recordado(avisar)


def cmd_analizar(a) -> None:
    from . import fuentes, indice
    from .modelo import Modelo, clave_modelo

    rutas.preparar()
    a.modelo = _modelo_de(a)
    clave_modelo(a.modelo)  # un --modelo mal escrito se avisa antes de leer toda la fototeca
    print(f"Espacio libre: {rutas.legible(disco.libre())}")
    desde, hasta = _fecha(a.desde), _fecha(a.hasta, fin=True)
    if a.carpeta:
        print(f"· Leyendo la carpeta {a.carpeta}…")
        it = fuentes.desde_carpeta(a.carpeta, desde, hasta)
        fuente, origen = "carpeta", str(a.carpeta)
    else:
        print("· Leyendo la fototeca de Fotos (la primera vez puede tardar un minuto)…")
        it = fuentes.desde_fototeca(a.biblioteca, desde, hasta, a.album)
        fuente, origen = "fotos", str(a.biblioteca or "sistema")
    if a.limite:
        import itertools

        it = itertools.islice(it, a.limite)
    r = indice.registrar(it, fuente, borrar_ausentes=not (a.desde or a.hasta or a.album or a.limite), origen=origen)
    print(f"  {r['fotos']} fotos en la fuente")
    import gc

    gc.collect()  # suelta la base de datos de Fotos antes de cargar el modelo (RAM)
    if r["sin_imagen_local"]:
        if getattr(a, "traer_icloud", False):
            from . import icloud

            uuids = indice.sin_imagen()
            try:
                icloud.traer(uuids, a.max_icloud)
            except (disco.SinEspacio, RuntimeError) as e:
                print(f"  ⚠ {e}\n  (sigo sin esas miniaturas de iCloud)")
            for u in uuids:
                c = icloud.ruta_cache(u)
                if c.exists():
                    indice.actualizar_foto(u, ruta_analisis=str(c), ruta_grande=str(c), firma=f"icloud|{c.stat().st_size}")
        else:
            print(f"  {r['sin_imagen_local']} no tienen ninguna imagen en este Mac (solo en iCloud): se saltan.")
            print("  (Si quieres incluirlas: ./arte analizar --traer-icloud  · ~100 KB por foto)")
    if not indice.pendientes(clave_modelo(a.modelo)):
        print("  todas las fotos ya estaban analizadas")
        indice.guardar_modelo_usado(a.modelo)
        return
    disco.comprobar(r["fotos"] * 2048, "guardar el índice", margen=disco.MARGEN_PEQUENO)
    modelo = Modelo(a.modelo)
    res = indice.vectorizar(modelo, lote=a.lote)
    est = indice.estadisticas()
    print(f"✓ Analizadas {est['analizadas'].get(modelo.clave, 0)} fotos ({res['errores']} con error).")
    if not indice.pendientes(modelo.clave):
        indice.guardar_modelo_usado(a.modelo)
        print("  Siguiente paso:  ./arte galeria")
        return
    # cortado a medias (o solo una parte de la fototeca): la galería no cambia de modelo sola
    previo = _modelo_recordado()
    if previo != a.modelo:
        print(f"  (La galería sigue usando «{previo}» hasta que termines de analizar con «{a.modelo}»: "
              f"./arte analizar --modelo {a.modelo}\n"
              f"   Para ver ya lo analizado con «{a.modelo}»:  ./arte galeria --modelo {a.modelo})")
    else:
        print("  Para seguir analizando:  ./arte analizar  ·  la galería ya funciona con lo analizado:  ./arte galeria")


def cmd_galeria(a) -> None:
    from .servidor import servir

    servir(_modelo_de(a, avisar=True), a.puerto, abrir=not a.no_abrir)


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
    print(f"  modelo de la galería: {_modelo_recordado()}")
    print("Espacio:")
    for k, v in disco.resumen().items():
        print(f"  {k:18s} {rutas.legible(v)}")


def cmd_limpiar(a) -> None:
    from .generar import leer_seleccion

    liberado = 0

    def borrar(p):
        nonlocal liberado
        if p.is_dir():
            liberado += rutas.tam_carpeta(p)
            shutil.rmtree(p, ignore_errors=True)
        elif p.exists():
            liberado += p.stat().st_size
            p.unlink()

    borrar(rutas.TEXTOS_CACHE)
    # temporales de una generación cortada (Terminal cerrada a medias); solo los de más de 1 h,
    # para no tocar el de una galería que esté generando ahora mismo
    for p in rutas.SALIDA.glob(".generando-*"):
        if time.time() - p.stat().st_mtime > 3600:
            borrar(p)
    aviso = None
    if a.todo:
        for p in (rutas.ORIGINALES, rutas.MINIATURAS_ICLOUD, rutas.MODELOS, rutas.BD,
                  rutas.BD.with_suffix(".sqlite-wal"), rutas.BD.with_suffix(".sqlite-shm")):
            borrar(p)
    else:
        # conservar los originales de las fotos que tienes elegidas (y las miniaturas de iCloud,
        # que forman parte del índice)
        try:
            sel = leer_seleccion()
        except Exception as e:
            sel = {"_aviso": str(e)}
        aviso = sel.get("_aviso")
        usar = {x["uuid"] for x in sel.get("arte", [])} | {x["uuid"] for x in sel.get("paseo", {}).get("fotos", [])}
        if aviso:
            # sin saber qué fotos tenías elegidas no se borra ningún original (bajarlos otra vez de iCloud cuesta)
            print(f"⚠ {aviso}\n  Por si acaso, no borro ningún original descargado.")
        elif rutas.ORIGINALES.exists():
            for d in rutas.ORIGINALES.iterdir():
                if d.is_dir() and d.name not in usar:
                    borrar(d)
    print(f"Liberados {rutas.legible(liberado)}.")
    if not a.todo and not aviso:
        print("Se conservan el modelo, el índice, tu selección, sus originales y las láminas.\n"
              "Para borrarlo todo menos la selección y las láminas: ./arte limpiar --todo")


def cmd_todo(a) -> None:
    from . import indice
    from .modelo import clave_modelo

    a.modelo = _modelo_de(a, avisar=True)
    clave_modelo(a.modelo)  # un --modelo mal escrito se avisa antes de leer toda la fototeca
    ultima = indice.ultima_lectura()
    reciente = ultima and time.time() - ultima < HORAS_RELECTURA * 3600
    if reciente and indice.estadisticas()["analizadas"].get(clave_modelo(a.modelo)) and not a.releer:
        print(f"(La fototeca se leyó hace {int((time.time() - ultima) / 60)} min: abro la galería directamente.\n"
              " Para buscar fotos nuevas: ./arte analizar   o   ./arte todo --releer)")
    else:
        cmd_analizar(a)
        # análisis cortado a medias: la galería sigue con el modelo anterior, como acaba de avisar cmd_analizar
        if indice.pendientes(clave_modelo(a.modelo)) and _modelo_recordado() != a.modelo:
            a.modelo = None
    cmd_galeria(a)


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(prog="arte", description=AYUDA, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd")

    def comunes(p):
        p.add_argument("--modelo", default=None,
                       help="rapido (por defecto), preciso (más fino y lento, descarga 1,8 GB) o arquitectura:pesos "
                            "de open_clip. Si no lo indicas, se usa el último con el que analizaste.")

    p = sub.add_parser("analizar", help="analiza la fototeca")
    comunes(p)
    p.add_argument("--carpeta", help="analizar una carpeta en vez de la app Fotos")
    p.add_argument("--biblioteca", help="ruta a otra .photoslibrary")
    p.add_argument("--desde", help="solo fotos desde esta fecha (AAAA-MM-DD)")
    p.add_argument("--hasta", help="solo fotos hasta esta fecha, incluida (AAAA-MM-DD)")
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
    p.add_argument("--todo", action="store_true", help="borra también el modelo descargado, el índice y los originales")
    p.set_defaults(fn=cmd_limpiar)

    p = sub.add_parser("todo", help="analizar (si hace falta) y abrir la galería")
    comunes(p)
    for arg in ("--carpeta", "--biblioteca", "--desde", "--hasta", "--album"):
        p.add_argument(arg)
    p.add_argument("--limite", type=int)
    p.add_argument("--lote", type=int, default=32)
    p.add_argument("--traer-icloud", action="store_true")
    p.add_argument("--max-icloud", type=int, default=None)
    p.add_argument("--releer", action="store_true", help="volver a leer la fototeca aunque se haya leído hace poco")
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
    except (RuntimeError, ValueError) as e:
        print(f"\n✗ {e}")
        sys.exit(1)
    except Exception as e:  # cualquier otra cosa: mensaje corto + pista, sin traza de Python
        print(f"\n✗ Error inesperado ({type(e).__name__}): {e}")
        print("  Si se repite, vuelve a ejecutar ./instalar.sh; los detalles técnicos:  ARTE_DEPURAR=1 ./arte …")
        import os

        if os.environ.get("ARTE_DEPURAR"):
            raise
        sys.exit(1)
