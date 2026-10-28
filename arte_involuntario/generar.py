"""De la selección (datos/seleccion.json) a los PDF y JPG finales en salida/."""
from __future__ import annotations

import json
from pathlib import Path

from . import descargas, disco, imagenes, indice, laminas, rutas
from .textos import cargar_config


def leer_seleccion() -> dict:
    try:
        return json.loads(rutas.SELECCION.read_text(encoding="utf-8"))
    except Exception:
        return {"autor": "", "arte": [], "paseo": {"fotos": []}, "opciones": {}}


def guardar_seleccion(sel: dict) -> None:
    rutas.preparar()
    tmp = rutas.SELECCION.with_suffix(".tmp")
    tmp.write_text(json.dumps(sel, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(rutas.SELECCION)


def _orden_arte(items: list[dict], orden: str) -> list[dict]:
    if orden == "manual":
        return items
    pos = {c: i for i, c in enumerate(laminas.ORDEN_CATEGORIAS)}
    return sorted(items, key=lambda it: pos.get(it.get("categoria"), 99))  # sort estable: respeta el orden de elección


def generar(sel: dict | None = None, descargar: bool = True, aviso=print) -> dict:
    sel = sel or leer_seleccion()
    rutas.preparar()
    disco.comprobar(200 * 1024**2, "generar las láminas", rutas.SALIDA)
    cfg = cargar_config()
    nombres = {c["id"]: c["nombre"] for c in cfg["categorias"]}
    op = sel.get("opciones", {}) or {}
    autor = sel.get("autor", "") or ""
    fu = laminas.Fuentes(op.get("fuente"))
    avisos: list[str] = []

    arte = [a for a in sel.get("arte", []) if a.get("uuid")]
    arte = _orden_arte(arte, op.get("orden", "categoria"))
    paseo = sel.get("paseo", {}) or {}
    pfotos = [p for p in paseo.get("fotos", []) if p.get("uuid")]

    metas = {}
    for it in arte + pfotos:
        m = indice.foto_cualquiera(it["uuid"])
        if m:
            metas[it["uuid"]] = m
        else:
            avisos.append(f"La foto {it['uuid']} ya no está en el índice.")
    resueltas = descargas.resolver(list(metas.values()), descargar=descargar, aviso=aviso)

    def cargar(it, bn, lado_mm):
        r = resueltas.get(it["uuid"])
        if not r:
            return None
        im = imagenes.abrir(r["ruta"])
        cuadrada, baja = laminas.preparar_foto(im, it.get("recorte"), lado_mm, bn, op.get("contraste", "normal"))
        if r["origen"] == "previa" or baja:
            avisos.append(
                f"{metas[it['uuid']].get('nombre') or it['uuid']}: solo hay {r.get('lado', '?')} px "
                f"({'previsualización de iCloud' if r['origen'] == 'previa' else 'resolución baja'}); "
                "se verá algo blanda impresa."
            )
        return cuadrada

    salida = rutas.SALIDA
    for sub in ("fotos_arte", "fotos_paseo", "previas"):
        (salida / sub).mkdir(parents=True, exist_ok=True)
        for viejo in (salida / sub).glob("*.jpg"):
            viejo.unlink()
    for viejo in salida.glob("lamina_*.jpg"):
        viejo.unlink()

    lam_arte: list = []
    if arte:
        if len(arte) != 24:
            avisos.append(f"Arte involuntario: hay {len(arte)} fotos (el ejercicio pide 24 = 4 láminas × 6).")
        faltan = [nombres[c] for c in laminas.ORDEN_CATEGORIAS if c not in {a.get('categoria') for a in arte}]
        if faltan:
            avisos.append("Categorías sin representar: " + ", ".join(faltan))
        fotos = []
        for k, it in enumerate(arte, 1):
            im = cargar(it, False, 106)
            if im is None:
                avisos.append(f"No encuentro la imagen de {it['uuid']}")
                continue
            im.save(salida / "fotos_arte" / f"{k:02d}_{it.get('categoria', 'x')}.jpg", quality=92, dpi=(300, 300))
            fotos.append({"im": im, "categoria": it.get("categoria", ""), "pie": it.get("pie", "")})
        lam_arte = laminas.maquetar_arte(fotos, fu, autor, nombres, cabecera=op.get("cabecera", True))

    lam_paseo: list = []
    if pfotos:
        if len(pfotos) < 12:
            avisos.append(f"Paseo: hay {len(pfotos)} fotos (mínimo 12).")
        fotos = []
        for k, it in enumerate(pfotos, 1):
            im = cargar(it, True, 100)
            if im is None:
                avisos.append(f"No encuentro la imagen de {it['uuid']}")
                continue
            im.save(salida / "fotos_paseo" / f"{k:02d}.jpg", quality=92, dpi=(300, 300))
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

    ficheros = {}
    if lam_arte:
        ficheros["arte_pdf"] = laminas.pdf(lam_arte, salida / "01_arte_involuntario.pdf", fu, "Colección de arte involuntario")
    if lam_paseo:
        ficheros["paseo_pdf"] = laminas.pdf(lam_paseo, salida / "02_paseo_fotografico.pdf", fu, "Paseo fotográfico")
    todas = lam_arte + lam_paseo
    if todas:
        ficheros["completo_pdf"] = laminas.pdf(todas, salida / "entrega_completa.pdf", fu, "Ejercicio 2.3 Fotografía")
        previas = []
        for k, L in enumerate(todas, 1):
            nombre = f"lamina_{k}_{'arte' if k <= len(lam_arte) else 'paseo'}"
            laminas.raster(L, fu, 110).save(salida / "previas" / f"{nombre}.jpg", quality=85)
            laminas.raster(L, fu, 200).save(salida / f"{nombre}.jpg", quality=90, dpi=(200, 200))
            previas.append(f"previas/{nombre}.jpg")
        ficheros["previas"] = previas
    return {
        "ficheros": {k: (str(v) if isinstance(v, Path) else v) for k, v in ficheros.items()},
        "avisos": list(dict.fromkeys(avisos)),
        "laminas": len(todas),
        "fuente": fu.familia,
    }
