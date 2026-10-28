"""De la selección (datos/seleccion.json) a los PDF y JPG finales en salida/."""
from __future__ import annotations

import json
import os
import shutil
import tempfile
import threading
from pathlib import Path

from . import descargas, disco, imagenes, indice, laminas, rutas
from .textos import cargar_config

_LOCK = threading.Lock()
VACIA = {"autor": "", "arte": [], "paseo": {"fotos": []}, "opciones": {}, "_rev": 0}


class Conflicto(Exception):
    def __init__(self, rev: int):
        super().__init__(f"La selección cambió en otra pestaña (rev {rev})")
        self.rev = rev


def leer_seleccion() -> dict:
    with _LOCK:
        if not rutas.SELECCION.exists():
            return json.loads(json.dumps(VACIA))
        try:
            return json.loads(rutas.SELECCION.read_text(encoding="utf-8"))
        except Exception as e:
            # nunca devolver una selección vacía que luego se guardaría encima de la buena
            copia = rutas.SELECCION.with_name("seleccion.corrupta.json")
            shutil.copyfile(rutas.SELECCION, copia)
            raise RuntimeError(f"datos/seleccion.json no se puede leer ({e}); copia en {copia.name}") from e


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


def generar(sel: dict | None = None, descargar: bool | None = None, aviso=print) -> dict:
    sel = sel or leer_seleccion()
    rutas.preparar()
    op = sel.get("opciones", {}) or {}
    if descargar is None:
        descargar = not op.get("sin_descargar", False)
    arte = [a for a in sel.get("arte", []) if a.get("uuid")]
    paseo = sel.get("paseo", {}) or {}
    pfotos = [p for p in paseo.get("fotos", []) if p.get("uuid")]
    if not arte and not pfotos:
        raise RuntimeError("Todavía no hay fotos elegidas: abre la galería (./arte galeria), elige y pulsa «Generar».")
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
            metas[it["uuid"]] = m
        else:
            avisos.append(f"La foto {it['uuid']} ya no está en el índice (¿se borró de Fotos?).")
    try:
        resueltas = descargas.resolver(list(metas.values()), descargar=descargar, aviso=aviso)
    except Exception as e:  # nunca dejar sin láminas por un problema de iCloud
        aviso(f"⚠ No se han podido descargar originales ({e}); se usan las previsualizaciones.")
        resueltas = descargas.resolver(list(metas.values()), descargar=False, aviso=aviso)

    px_por_imagen: dict[int, tuple[str, int, str]] = {}

    def cargar(it, bn, lado_mm, etiqueta):
        r = resueltas.get(it["uuid"])
        if not r:
            avisos.append(f"{etiqueta}: no encuentro ninguna imagen de esta foto.")
            return None
        im = imagenes.abrir(r["ruta"], color=True)
        cuadrada, px = laminas.preparar_foto(im, it.get("recorte"), lado_mm, bn, op.get("contraste", "normal"))
        px_por_imagen[id(cuadrada)] = (etiqueta, px, r["origen"])
        return cuadrada

    tmp = Path(tempfile.mkdtemp(prefix=".generando-", dir=rutas.SALIDA))
    try:
        for sub in ("fotos_arte", "fotos_paseo", "previas"):
            (tmp / sub).mkdir()

        lam_arte: list = []
        if arte:
            if len(arte) != 24:
                avisos.append(f"Arte involuntario: hay {len(arte)} fotos (el ejercicio pide 24 = 4 láminas × 6).")
            presentes = {a.get("categoria") for a in arte}
            faltan = [nombres[c] for c in laminas.ORDEN_CATEGORIAS if c not in presentes and c in nombres]
            if faltan:
                avisos.append("Categorías sin representar: " + ", ".join(faltan) + " (el ejercicio pide intentar que estén todas).")
            fotos = []
            for k, it in enumerate(arte, 1):
                etiqueta = f"Lámina {(k - 1) // 6 + 1}, foto {(k - 1) % 6 + 1} ({nombres.get(it.get('categoria'), '?')})"
                im = cargar(it, False, laminas.LADO_ARTE, etiqueta)
                if im is None:
                    continue
                _guardar_jpg(im, tmp / "fotos_arte" / f"{k:02d}_{it.get('categoria', 'x')}.jpg", 300, icc)
                fotos.append({"im": im, "categoria": it.get("categoria", ""), "pie": it.get("pie", "")})
            lam_arte = laminas.maquetar_arte(fotos, fu, autor, nombres, cabecera=op.get("cabecera", True))

        lam_paseo: list = []
        if pfotos:
            if len(pfotos) < 12:
                avisos.append(f"Paseo: hay {len(pfotos)} fotos (mínimo 12).")
            if not (paseo.get("titulo") or "").strip():
                avisos.append("Paseo: falta la palabra-título (como LIZARDS o CLOUDS en las obras de Fulton).")
            if not (paseo.get("linea") or "").strip():
                avisos.append("Paseo: falta la línea que describe la caminata.")
            n = len(pfotos)
            fotos = []
            for k, it in enumerate(pfotos, 1):
                marca = "ORIGEN" if k == 1 else ("FINAL" if k == n else f"{k:02d}")
                im = cargar(it, True, 110, f"Paseo, foto {marca}")
                if im is None:
                    continue
                _guardar_jpg(im, tmp / "fotos_paseo" / f"{k:02d}.jpg", 300, icc)
                m = metas.get(it["uuid"], {})
                alt = it.get("alt") if it.get("alt") is not None else m.get("alt")
                fotos.append({"im": im, "frase": it.get("frase", ""), "km": it.get("km"), "alt": alt,
                              "fecha": m.get("fecha"), "lat": m.get("lat"), "lon": m.get("lon")})
            lam_paseo = laminas.maquetar_paseo(
                fotos, fu, paseo.get("titulo", ""), paseo.get("linea", ""), autor,
                mayusculas=paseo.get("mayusculas", True), dibujo=paseo.get("dibujo", True),
                cabecera=op.get("cabecera", True), diseno=paseo.get("diseno", "rejilla"),
                datos=paseo.get("datos", True),
            )

        todas = lam_arte + lam_paseo
        if not autor:
            avisos.append("Falta tu nombre para la cabecera (pestaña Láminas).")
        # resolución efectiva de cada foto tal como ha quedado en la lámina
        for L in todas:
            avisos.extend(L.avisos)
            for e in L.elementos:
                if isinstance(e, laminas.Foto) and id(e.im) in px_por_imagen:
                    etiqueta, px, origen = px_por_imagen[id(e.im)]
                    ppi = px / (e.lado / 25.4)
                    if ppi < laminas.PPI_MINIMO:
                        motivo = ("previsualización de iCloud (no se pudo bajar el original)" if origen == "previa"
                                  else "recorte con mucho zoom o foto pequeña")
                        avisos.append(f"{etiqueta}: {px} px tras el recorte → {ppi:.0f} ppp impresa ({motivo}); "
                                      "se verá algo blanda. Baja el zoom o elige otra.")

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
