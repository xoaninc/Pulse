"""De la selección (datos/seleccion.json) a los PDF y JPG finales en salida/."""
from __future__ import annotations

import json
import os
import shutil
import tempfile
import threading
import time
from pathlib import Path

from . import descargas, disco, imagenes, indice, laminas, rutas
from .textos import cargar_config

_LOCK = threading.Lock()
VACIA = {"autor": "", "arte": [], "paseo": {"fotos": []}, "opciones": {}, "_rev": 0}


class Conflicto(Exception):
    def __init__(self, rev: int):
        super().__init__(f"La selección cambió en otra pestaña (rev {rev})")
        self.rev = rev


def _apartar_corrupta() -> Path:
    """Mueve seleccion.json a seleccion.corrupta-<epoch>.json sin pisar una copia anterior."""
    base = int(time.time())
    for i in range(1000):
        copia = rutas.SELECCION.with_name(f"seleccion.corrupta-{base}{f'-{i}' if i else ''}.json")
        if not copia.exists():
            os.replace(rutas.SELECCION, copia)
            return copia
    raise RuntimeError("demasiadas copias de seleccion.corrupta-*.json en datos/")


def leer_seleccion() -> dict:
    """La selección guardada. Si el fichero está dañado, se aparta (nunca se borra ni se guarda
    encima) y se devuelve una selección vacía con `_aviso`, que la galería enseña y nunca se guarda."""
    with _LOCK:
        if not rutas.SELECCION.exists():
            return json.loads(json.dumps(VACIA))
        try:
            sel = json.loads(rutas.SELECCION.read_text(encoding="utf-8"))
            if not isinstance(sel, dict):
                raise ValueError("no es un objeto JSON")
            return sel
        except Exception as e:
            try:
                copia = _apartar_corrupta()
            except Exception as e2:
                # sin poder apartarla no se devuelve una vacía: se guardaría encima de la dañada
                raise RuntimeError(f"datos/seleccion.json no se puede leer ({e}) ni apartar ({e2})") from e
            vacia = json.loads(json.dumps(VACIA))
            vacia["_aviso"] = (f"La selección guardada estaba dañada y no se podía leer. Se ha apartado "
                               f"como datos/{copia.name} y empiezas con una selección vacía.")
            return vacia


def guardar_seleccion(sel: dict, rev_cliente: int | None = None) -> int:
    """Guarda de forma atómica. Si `rev_cliente` es más antigua que la guardada (otra pestaña
    ha cambiado la selección después), no guarda y lanza Conflicto."""
    rutas.preparar()
    with _LOCK:
        actual = 0
        if rutas.SELECCION.exists():
            try:
                actual = int(json.loads(rutas.SELECCION.read_text(encoding="utf-8")).get("_rev", 0))
            except Exception:
                actual = 0
        if rev_cliente is not None and rev_cliente < actual:
            raise Conflicto(actual)
        sel = dict(sel)
        sel.pop("_aviso", None)  # solo viaja al navegador: nunca se guarda
        sel["_rev"] = actual + 1
        fd, tmp = tempfile.mkstemp(dir=rutas.DATOS, suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(sel, f, ensure_ascii=False, indent=1)
        os.replace(tmp, rutas.SELECCION)
        return sel["_rev"]


def _orden_arte(items: list[dict], orden: str) -> list[dict]:
    if orden == "manual":
        return items
    pos = {c: i for i, c in enumerate(laminas.ORDEN_CATEGORIAS)}
    return sorted(items, key=lambda it: pos.get(it.get("categoria"), 99))  # sort estable: respeta el orden de elección


def _icc_srgb() -> bytes | None:
    try:
        from PIL import ImageCms

        return ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()
    except Exception:
        return None


def _guardar_jpg(im, ruta: Path, dpi: int, icc: bytes | None, calidad: int = 92) -> None:
    extra = {"icc_profile": icc} if (icc and im.mode == "RGB") else {}
    im.save(ruta, "JPEG", quality=calidad, dpi=(dpi, dpi), **extra)


def _limpiar_temporales_viejos() -> None:
    """Borra las salida/.generando-* de generaciones que murieron a medias (Terminal cerrada,
    salida forzada): su `finally` no llegó a ejecutarse. Solo las de más de 1 h, para no tocar
    la de otra generación que esté en curso."""
    try:
        for d in rutas.SALIDA.glob(".generando-*"):
            try:
                if d.is_dir() and time.time() - d.stat().st_mtime > 3600:
                    shutil.rmtree(d, ignore_errors=True)
            except OSError:
                pass
    except OSError:
        pass


def generar(sel: dict | None = None, descargar: bool | None = None, aviso=print) -> dict:
    sel = sel or leer_seleccion()
    rutas.preparar()
    _limpiar_temporales_viejos()
    op = sel.get("opciones", {}) or {}
    if descargar is None:
        descargar = not op.get("sin_descargar", False)
    arte = [a for a in sel.get("arte", []) if a.get("uuid")]
    paseo = sel.get("paseo", {}) or {}
    pfotos = [p for p in paseo.get("fotos", []) if p.get("uuid")]
    if not arte and not pfotos:
        msg = "Todavía no hay fotos elegidas: abre la galería (./arte galeria), elige y pulsa «Generar»."
        raise RuntimeError(f"{sel['_aviso']} {msg}" if sel.get("_aviso") else msg)
    disco.comprobar(80 * 1024**2, "generar las láminas", rutas.SALIDA, margen=disco.MARGEN_PEQUENO)
    cfg = cargar_config()
    nombres = {c["id"]: c["nombre"] for c in cfg["categorias"]}
    autor = (sel.get("autor", "") or "").strip()
    fu = laminas.Fuentes(op.get("fuente"))
    avisos: list[str] = []
    icc = _icc_srgb()

    arte = _orden_arte(arte, op.get("orden", "categoria"))
    metas = {}
    for it in arte + pfotos:
        m = indice.foto_cualquiera(it["uuid"])
        if m:
            metas[it["uuid"]] = m  # las que faltan las avisa cargar(), que sabe qué foto elegida son
    try:
        resueltas = descargas.resolver(list(metas.values()), descargar=descargar, aviso=aviso)
    except Exception as e:  # nunca dejar sin láminas por un problema de iCloud
        aviso(f"⚠ No se han podido descargar originales ({e}); se usan las previsualizaciones.")
        resueltas = descargas.resolver(list(metas.values()), descargar=False, aviso=aviso)

    # Antes de maquetar, una foto que falla se nombra por su orden en la selección; los avisos
    # de resolución se escriben después, con la lámina y la posición donde ha quedado de verdad.
    px_por_imagen: dict[int, tuple[int, str]] = {}
    fallos: list[str] = []

    def fallo(txt):
        fallos.append(txt)
        avisos.append(txt)

    def cargar(it, bn, lado_mm, etiqueta, detalle=""):
        m = metas.get(it["uuid"])
        if not m:
            etq = f"{etiqueta} ({detalle})" if detalle else etiqueta
            fallo(f"{etq}: ya no está en el índice (¿se borró de Fotos?); quítala o elige otra en la galería.")
            return None
        nombre = m.get("nombre") or it["uuid"]
        etq = f"{etiqueta} ({', '.join(x for x in (detalle, nombre) if x)})"
        r = resueltas.get(it["uuid"])
        if not r:
            fallo(f"{etq}: no encuentro ninguna imagen de esta foto.")
            return None
        # el original puede estar truncado (descarga cortada) o no decodificarse (HEIC raro):
        # antes de dar la foto por perdida se prueba con sus previsualizaciones
        candidatas = [(r["ruta"], r["origen"])]
        for clave in ("ruta_grande", "ruta_analisis"):
            if m.get(clave) and all(m[clave] != c[0] for c in candidatas):
                candidatas.append((m[clave], "previa"))
        error = None
        for ruta, origen in candidatas:
            try:
                im = imagenes.abrir(ruta, color=True)
                cuadrada, px = laminas.preparar_foto(im, it.get("recorte"), lado_mm, bn, op.get("contraste", "normal"))
            except Exception as e:
                error = error or e
                continue
            if error:
                avisos.append(f"{etq}: no se puede abrir el original ({error}); se usa la previsualización. "
                              "Vuelve a descargarla si la quieres nítida.")
            px_por_imagen[id(cuadrada)] = (px, origen)
            return cuadrada
        archivo = Path(r["ruta"]).name
        fallo(f"{etq}: no se puede abrir {'el archivo' if archivo == nombre else archivo} ({error}); "
              "elige otra foto o vuelve a descargarla.")
        return None

    tmp = Path(tempfile.mkdtemp(prefix=".generando-", dir=rutas.SALIDA))
    try:
        for sub in ("fotos_arte", "fotos_paseo", "previas"):
            (tmp / sub).mkdir()

        lam_arte: list = []
        cat_por_imagen: dict[int, str] = {}
        if arte:
            fotos_arte = []
            for k, it in enumerate(arte, 1):
                cat = nombres.get(it.get("categoria"), "?")
                im = cargar(it, False, laminas.LADO_ARTE, f"Arte, foto elegida nº {k}", cat)
                if im is None:
                    continue
                # numerada como en la lámina (las que no se han podido cargar no ocupan hueco)
                _guardar_jpg(im, tmp / "fotos_arte" / f"{len(fotos_arte) + 1:02d}_{it.get('categoria', 'x')}.jpg", 300, icc)
                fotos_arte.append({"im": im, "categoria": it.get("categoria", ""), "pie": it.get("pie", "")})
                cat_por_imagen[id(im)] = cat
            if fotos_arte:
                if len(fotos_arte) != 24:
                    avisos.append(f"Arte involuntario: hay {len(fotos_arte)} fotos en las láminas "
                                  "(el ejercicio pide 24 = 4 láminas × 6).")
                presentes = {f["categoria"] for f in fotos_arte}
                faltan = [nombres[c] for c in laminas.ORDEN_CATEGORIAS if c not in presentes and c in nombres]
                if faltan:
                    avisos.append("Categorías sin representar: " + ", ".join(faltan) + " (el ejercicio pide intentar que estén todas).")
                lam_arte = laminas.maquetar_arte(fotos_arte, fu, autor, nombres, cabecera=op.get("cabecera", True))
            else:
                avisos.append("Arte involuntario: no se ha podido cargar ninguna foto; vuelve a elegirlas en la galería.")

        lam_paseo: list = []
        marca_por_imagen: dict[int, str] = {}
        if pfotos:
            if not (paseo.get("titulo") or "").strip():
                avisos.append("Paseo: falta la palabra-título (como LIZARDS o CLOUDS en las obras de Fulton).")
            if not (paseo.get("linea") or "").strip():
                avisos.append("Paseo: falta la línea que describe la caminata.")
            fotos_paseo = []
            for k, it in enumerate(pfotos, 1):
                im = cargar(it, True, 110, f"Paseo, foto elegida nº {k}")
                if im is None:
                    continue
                _guardar_jpg(im, tmp / "fotos_paseo" / f"{len(fotos_paseo) + 1:02d}.jpg", 300, icc)
                m = metas.get(it["uuid"], {})
                alt = it.get("alt") if it.get("alt") is not None else m.get("alt")
                fotos_paseo.append({"im": im, "frase": it.get("frase", ""), "km": it.get("km"), "alt": alt,
                                    "fecha": m.get("fecha"), "lat": m.get("lat"), "lon": m.get("lon")})
            n = len(fotos_paseo)
            for j, f in enumerate(fotos_paseo):  # la misma numeración que lleva cada foto en la lámina
                marca_por_imagen[id(f["im"])] = "ORIGEN" if j == 0 else ("FINAL" if j == n - 1 else f"{j + 1:02d}")
            if fotos_paseo:
                if n < 12:
                    avisos.append(f"Paseo: hay {n} fotos en las láminas (mínimo 12).")
                lam_paseo = laminas.maquetar_paseo(
                    fotos_paseo, fu, paseo.get("titulo", ""), paseo.get("linea", ""), autor,
                    mayusculas=paseo.get("mayusculas", True), dibujo=paseo.get("dibujo", True),
                    cabecera=op.get("cabecera", True), diseno=paseo.get("diseno", "rejilla"),
                    datos=paseo.get("datos", True),
                )
            else:
                avisos.append("Paseo: no se ha podido cargar ninguna foto; vuelve a elegirlas en la galería.")

        todas = lam_arte + lam_paseo
        if not todas:  # la salida anterior se queda como estaba
            raise RuntimeError("No se ha podido cargar ninguna de las fotos elegidas; vuelve a elegirlas en la galería. "
                               + " ".join(fallos[:3]) + (" …" if len(fallos) > 3 else ""))
        if not autor:
            avisos.append("Falta tu nombre para la cabecera (pestaña Láminas).")
        # resolución efectiva de cada foto tal como ha quedado en la lámina
        etiquetas = {id(e.im): f"Paseo, foto {marca_por_imagen.get(id(e.im), '?')}"
                     for L in lam_paseo for e in L.elementos if isinstance(e, laminas.Foto)}
        for li, L in enumerate(lam_arte, 1):
            for j, e in enumerate((e for e in L.elementos if isinstance(e, laminas.Foto)), 1):
                etiquetas[id(e.im)] = f"Lámina {li}, foto {j} ({cat_por_imagen.get(id(e.im), '?')})"
        for L in todas:
            avisos.extend(L.avisos)
            for e in L.elementos:
                if isinstance(e, laminas.Foto) and id(e.im) in px_por_imagen:
                    px, origen = px_por_imagen[id(e.im)]
                    ppi = px / (e.lado / 25.4)
                    if ppi < laminas.PPI_MINIMO:
                        motivo = ("previsualización de iCloud (no se pudo bajar el original)" if origen == "previa"
                                  else "recorte con mucho zoom o foto pequeña")
                        avisos.append(f"{etiquetas.get(id(e.im), 'Foto')}: {px} px tras el recorte → {ppi:.0f} ppp impresa "
                                      f"({motivo}); se verá algo blanda. Baja el zoom o elige otra.")

        if lam_arte:
            laminas.pdf(lam_arte, tmp / "01_arte_involuntario.pdf", fu, "Colección de arte involuntario", autor)
        if lam_paseo:
            laminas.pdf(lam_paseo, tmp / "02_paseo_fotografico.pdf", fu, "Paseo fotográfico", autor)
        laminas.pdf(todas, tmp / "entrega_completa.pdf", fu, "Ejercicio 2.3 Fotografía", autor)
        previas = []
        for k, L in enumerate(todas, 1):
            nombre = f"lamina_{k}_{'arte' if k <= len(lam_arte) else 'paseo'}"
            _guardar_jpg(laminas.raster(L, fu, 110), tmp / "previas" / f"{nombre}.jpg", 110, icc, 85)
            _guardar_jpg(laminas.raster(L, fu, 200), tmp / f"{nombre}.jpg", 200, icc, 90)
            previas.append(f"previas/{nombre}.jpg")

        # sustituir la salida anterior de golpe (nada de mezclar versiones)
        salida = rutas.SALIDA
        for viejo in ("01_arte_involuntario.pdf", "02_paseo_fotografico.pdf", "entrega_completa.pdf"):
            (salida / viejo).unlink(missing_ok=True)
        for viejo in salida.glob("lamina_*.jpg"):
            viejo.unlink()
        for sub in ("fotos_arte", "fotos_paseo", "previas"):
            shutil.rmtree(salida / sub, ignore_errors=True)
        for f in tmp.iterdir():
            os.replace(f, salida / f.name)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    ficheros = {"completo_pdf": str(rutas.SALIDA / "entrega_completa.pdf"), "previas": previas}
    if lam_arte:
        ficheros["arte_pdf"] = str(rutas.SALIDA / "01_arte_involuntario.pdf")
    if lam_paseo:
        ficheros["paseo_pdf"] = str(rutas.SALIDA / "02_paseo_fotografico.pdf")
    if fu.familia != "Futura":
        avisos.append(f"Tipografía: se ha usado {fu.familia} (Futura no está disponible en este ordenador).")
    aviso(f"✓ {len(todas)} láminas generadas en {rutas.SALIDA}")
    return {"ficheros": ficheros, "avisos": list(dict.fromkeys(avisos)), "laminas": len(todas), "fuente": fu.familia}
