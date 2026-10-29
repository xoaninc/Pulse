"""Pruebas de láminas y generación sin modelo ni fototeca: dibujo del recorrido, textos que no
caben, fotos que fallan, selección dañada y miniaturas con perfil de color."""
from __future__ import annotations

import io
import itertools
import json
import os
import time

import pytest
from PIL import Image, ImageCms

from arte_involuntario import descargas, generar, imagenes, indice, laminas, rutas


@pytest.fixture(scope="module")
def fu():
    return laminas.Fuentes()


def _paseo(n, alt=True, gps=True, lat=None, lon=None):
    im = Image.new("L", (10, 10), 128)
    out = []
    for k in range(n):
        out.append({"im": im, "frase": "Dos corzos cruzan la pista y se quedan quietos mirándonos",
                    "km": 0.2 * k, "alt": (1150 + 25 * k) if alt else None,
                    "fecha": f"2025-05-11T{10 + k // 6:02d}:{(k * 10) % 60:02d}:00+02:00",
                    "lat": (lat if lat is not None else 40.7933 + 0.0016 * k) if gps else None,
                    "lon": (lon if lon is not None else -3.9525 + 0.0007 * k) if gps else None})
    return out


def _caja(e, fu):
    if isinstance(e, laminas.Foto):
        return (e.x, e.y, e.x + e.lado, e.y + e.lado)
    w = fu.ancho(e.texto, e.estilo, e.pt, e.tracking)
    x = e.x - (w if e.alin == "der" else w / 2 if e.alin == "centro" else 0)
    return (x, e.y - e.pt * laminas.PT * 0.72, x + w, e.y)


def _se_solapan(a, b):
    return min(a[2], b[2]) - max(a[0], b[0]) > 0.05 and min(a[3], b[3]) - max(a[1], b[1]) > 0.05


def _fotos(L):
    return [e for e in L.elementos if isinstance(e, laminas.Foto)]


def _ruta(L):
    return [e for e in L.elementos if isinstance(e, laminas.Linea) and e.grosor == 0.4]


# ---------------------------------------------------------------------- dibujo del recorrido
def test_planta_legible_con_norte_y_escala_junto_al_dibujo(fu):
    for n in (12, 16, 30):
        lp = laminas.maquetar_paseo(_paseo(n, alt=False), fu, "NIEBLA", "UNA CAMINATA", "A")
        L = lp[1]
        (ruta,) = _ruta(L)
        xs, ys = [p[0] for p in ruta.puntos], [p[1] for p in ruta.puntos]
        assert max(ys) - min(ys) > 30  # antes, 17 mm: una mancha
        barra = [e for e in L.elementos if isinstance(e, laminas.Linea) and len(e.puntos) == 4]
        assert len(barra) == 1
        largo = barra[0].puntos[2][0] - barra[0].puntos[1][0]
        assert 3 < largo <= 25 and 0 < barra[0].puntos[0][0] - max(xs) < 8
        assert any(e.texto in ("1 KM", "2 KM", "500 M") for e in L.elementos if isinstance(e, laminas.Texto))
        textos = [e for e in L.elementos if isinstance(e, laminas.Texto)]
        for a, b in itertools.combinations(textos, 2):
            assert not _se_solapan(_caja(a, fu), _caja(b, fu)), (a.texto, b.texto)
        assert sum(e.pt == 5 for e in textos) >= (n - 2) * 0.8  # casi todos los puntos numerados
        # las dos láminas siguen con la misma rejilla
        assert {f.lado for f in _fotos(lp[0])} == {f.lado for f in _fotos(lp[1])}


@pytest.mark.parametrize("lat_lon", [(40.79, -3.95), None])
def test_sin_recorrido_no_se_dibuja_ni_reserva_franja(fu, lat_lon):
    sin_dibujo = laminas.maquetar_paseo(_paseo(12, alt=False), fu, "NIEBLA", "UNA CAMINATA", "A", dibujo=False)
    if lat_lon:  # todas en el mismo punto (ubicación puesta a mano en Fotos)
        fotos = _paseo(12, alt=False, lat=lat_lon[0], lon=lat_lon[1])
    else:
        fotos = _paseo(12, alt=False, gps=False)
    lp = laminas.maquetar_paseo(fotos, fu, "NIEBLA", "UNA CAMINATA", "A")
    assert not _ruta(lp[1])
    assert not [e for e in lp[1].elementos if isinstance(e, laminas.Linea) and len(e.puntos) == 4]
    assert any("no se dibuja el recorrido" in a for a in lp[1].avisos)
    assert _fotos(lp[0])[0].lado == _fotos(sin_dibujo[0])[0].lado  # sin banda vacía arriba


def test_perfil_con_km_iguales_pasa_a_planta(fu):
    fotos = _paseo(12)
    for f in fotos:
        f["km"] = 1.0
    L = laminas.maquetar_paseo(fotos, fu, "NIEBLA", "UNA CAMINATA", "A")[1]
    assert any(e.texto.startswith("RECORRIDO") for e in L.elementos if isinstance(e, laminas.Texto))


def test_crece_recorta_la_linea_de_datos_y_sigue_creciendo(fu):
    for n in (20, 24, 30):
        lp = laminas.maquetar_paseo(_paseo(n), fu, "NIEBLA", "UNA CAMINATA", "A", diseno="crece")
        lados = [f.lado for L in lp for f in _fotos(L)]
        assert all(b >= a - 1e-9 for a, b in zip(lados, lados[1:]))
        for L in lp:
            fotos = _fotos(L)
            for e in L.elementos:
                if isinstance(e, laminas.Texto) and e.texto.startswith("·  "):
                    f = max((f for f in fotos if f.x <= e.x and e.y - 8 < f.y + f.lado < e.y), key=lambda f: f.x)
                    assert _caja(e, fu)[2] <= f.x + f.lado + 0.01, e.texto
        assert any(e.texto.endswith(" M") for L in lp for e in L.elementos if isinstance(e, laminas.Texto)
                   and e.texto.startswith("·  "))  # en las fotos grandes la altitud sigue


def test_puntos_suspensivos_dentro_de_la_caja(fu):
    lineas, pt, cortado = laminas.texto_en_caja("A" * 300, fu, "normal", 7, 31, 3, 6.5, tracking=0.04)
    assert cortado and lineas[-1].endswith("…") and not lineas[-1].endswith("-…")
    assert fu.ancho(lineas[-1], "normal", pt, 0.04) <= 31


def test_maquetar_sin_fotos(fu):
    assert laminas.maquetar_paseo([], fu, "NIEBLA", "", "A") == []
    assert laminas.maquetar_arte([], fu, "A") == []


# ---------------------------------------------------------------------- generar
def _jpeg(ruta, lado, ruido=False):
    im = Image.effect_noise((lado, lado), 60).convert("RGB") if ruido else Image.new("RGB", (lado, lado), (90, 140, 60))
    im.save(ruta, "JPEG", quality=95)
    return str(ruta)


@pytest.fixture
def entorno(tmp_path, monkeypatch):
    for nombre in ("DATOS", "SALIDA", "MODELOS", "ORIGINALES", "TEXTOS_CACHE"):
        monkeypatch.setattr(rutas, nombre, tmp_path / nombre.lower())
    monkeypatch.setattr(rutas, "SELECCION", tmp_path / "datos" / "seleccion.json")
    fotos = {}
    monkeypatch.setattr(indice, "foto_cualquiera", lambda u: fotos.get(u))
    monkeypatch.setattr(descargas, "resolver", lambda ms, descargar=True, aviso=print: {
        m["uuid"]: {"ruta": m["ruta_original"], "origen": "local"} for m in ms})
    return tmp_path, fotos


def test_generar_con_fotos_rotas_borradas_y_temporales_viejos(entorno):
    tmp, fotos = entorno
    (tmp / "img").mkdir()
    arte = []
    for k in range(9):
        u = f"a{k}"
        arte.append({"uuid": u, "categoria": "vuelos", "pie": ""})
        if k == 4:
            continue  # borrada de Fotos: ya no está en el índice
        ruta = _jpeg(tmp / "img" / f"{u}.jpg", 100 if k == 7 else 1300, ruido=(k == 2))
        if k == 2:  # descarga cortada: se abre, pero no se decodifica
            datos = open(ruta, "rb").read()
            open(ruta, "wb").write(datos[: len(datos) // 3])
        fotos[u] = {"uuid": u, "nombre": f"{u}.jpg", "ruta_original": ruta}
    paseo = {"titulo": "NIEBLA", "linea": "X", "fotos": [{"uuid": f"borrada{k}", "frase": "x"} for k in range(12)]}
    rutas.SALIDA.mkdir(parents=True)
    viejo, nuevo = rutas.SALIDA / ".generando-viejo", rutas.SALIDA / ".generando-nuevo"
    viejo.mkdir(), nuevo.mkdir()
    os.utime(viejo, (time.time() - 7200, time.time() - 7200))

    r = generar.generar({"autor": "A", "arte": arte, "paseo": paseo}, descargar=False, aviso=lambda m: None)
    av = r["avisos"]
    assert r["laminas"] == 2 and "arte_pdf" in r["ficheros"] and "paseo_pdf" not in r["ficheros"]
    assert any(a.startswith("Arte, foto elegida nº 3 (Vuelos, a2.jpg): no se puede abrir el archivo (") for a in av)
    assert any(a.startswith("Arte, foto elegida nº 5 (Vuelos): ya no está en el índice") for a in av)
    assert any("Paseo: no se ha podido cargar ninguna foto" in a for a in av)
    # la foto pequeña es la 6.ª que se ha podido cargar: lámina 1, foto 6 (no la 8.ª elegida)
    assert any(a.startswith("Lámina 1, foto 6 (Vuelos): 100 px") for a in av), av
    assert not any(a.startswith("Lámina 2, foto 2") for a in av)
    assert sorted(p.name for p in (rutas.SALIDA / "fotos_arte").iterdir())[-1] == "07_vuelos.jpg"
    assert not viejo.exists() and nuevo.exists()

    # si no se puede cargar ninguna, error claro y la entrega anterior se queda como estaba
    antes = (rutas.SALIDA / "entrega_completa.pdf").read_bytes()
    with pytest.raises(RuntimeError, match="No se ha podido cargar ninguna"):
        generar.generar({"autor": "A", "arte": arte[4:5], "paseo": paseo}, descargar=False, aviso=lambda m: None)
    assert (rutas.SALIDA / "entrega_completa.pdf").read_bytes() == antes
    assert list(rutas.SALIDA.glob(".generando-*")) == [nuevo]  # la fallida no deja su temporal


def test_original_roto_usa_la_previsualizacion(entorno):
    tmp, fotos = entorno
    (tmp / "img").mkdir()
    roto = _jpeg(tmp / "img" / "roto.jpg", 1300, ruido=True)
    datos = open(roto, "rb").read()
    open(roto, "wb").write(datos[: len(datos) // 3])
    fotos["u"] = {"uuid": "u", "nombre": "IMG_1.jpg", "ruta_original": roto,
                  "ruta_analisis": _jpeg(tmp / "img" / "previa.jpg", 400)}
    r = generar.generar({"autor": "A", "arte": [{"uuid": "u", "categoria": "islas"}]}, descargar=False, aviso=lambda m: None)
    assert r["laminas"] == 1
    assert any(a.startswith("Arte, foto elegida nº 1 (Islas, IMG_1.jpg): no se puede abrir el original (")
               and "se usa la previsualización" in a for a in r["avisos"])


# ---------------------------------------------------------------------- selección dañada
def test_seleccion_danada_se_aparta_sin_pisar_copias(entorno):
    rutas.DATOS.mkdir(parents=True)
    rutas.SELECCION.write_text('{"autor": "A", "arte": [', encoding="utf-8")
    s1 = generar.leer_seleccion()
    copias = sorted(rutas.DATOS.glob("seleccion.corrupta-*.json"))
    assert len(copias) == 1 and copias[0].read_text(encoding="utf-8") == '{"autor": "A", "arte": ['
    assert not rutas.SELECCION.exists()
    assert {k: v for k, v in s1.items() if k != "_aviso"} == generar.VACIA and copias[0].name in s1["_aviso"]
    rutas.SELECCION.write_text("[1, 2]", encoding="utf-8")  # JSON válido pero no es una selección
    s2 = generar.leer_seleccion()
    copias = sorted(rutas.DATOS.glob("seleccion.corrupta-*.json"))
    assert len(copias) == 2 and "_aviso" in s2
    assert {c.read_text(encoding="utf-8") for c in copias} == {'{"autor": "A", "arte": [', "[1, 2]"}
    generar.guardar_seleccion(s2, s2["_rev"])
    guardada = json.loads(rutas.SELECCION.read_text(encoding="utf-8"))
    assert "_aviso" not in guardada and generar.leer_seleccion() == guardada
    with pytest.raises(RuntimeError, match="dañada"):
        rutas.SELECCION.write_text("{", encoding="utf-8")
        generar.generar(descargar=False, aviso=lambda m: None)


# ---------------------------------------------------------------------- miniaturas
def test_miniatura_conserva_perfil_rgb_y_descarta_el_cmyk(tmp_path):
    icc = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()
    Image.new("RGB", (900, 600), (32, 170, 51)).save(tmp_path / "p3.jpg", icc_profile=icc)
    mini = Image.open(io.BytesIO(imagenes.miniatura_jpeg(tmp_path / "p3.jpg", 300)))
    assert mini.info.get("icc_profile") == icc and max(mini.size) == 300
    falso = bytearray(icc)
    falso[16:20] = b"CMYK"
    Image.new("CMYK", (300, 200)).save(tmp_path / "cmyk.jpg", icc_profile=bytes(falso))
    mini = Image.open(io.BytesIO(imagenes.miniatura_jpeg(tmp_path / "cmyk.jpg", 100)))
    assert mini.mode == "RGB" and not mini.info.get("icc_profile")
