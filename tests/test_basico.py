"""Pruebas sin modelo ni fototeca: recortes, EXIF, puntuación, paseos y maquetación."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from fractions import Fraction
from types import SimpleNamespace

import numpy as np
import pytest
from PIL import Image
from PIL.TiffImagePlugin import IFDRational

from arte_involuntario import imagenes, laminas
from arte_involuntario.fuentes import foto_de_photoinfo
from arte_involuntario.paseos import Paseos, frase_borrador, km_entre, linea_paseo
from arte_involuntario.puntuar import Puntuador, coincide, normalizar


# ---------------------------------------------------------------------- imágenes
def test_recorte_cuadrado_y_bn():
    im = Image.new("RGB", (400, 200), "red")
    c = imagenes.recorte_cuadrado(im, 0.9, 0.5, 1)
    assert c.size == (200, 200)
    c2 = imagenes.recorte_cuadrado(im, 0.5, 0.5, 2)
    assert c2.size == (100, 100)
    bn = imagenes.a_blanco_y_negro(c, "alto")
    assert bn.mode == "L"  # gris de verdad: el PDF la incrusta como DeviceGray
    # la niebla (tonos claros y poco contraste) no se estira hasta el blanco y negro puros
    niebla = Image.linear_gradient("L").resize((200, 200)).point(lambda v: 150 + v * 70 // 255).convert("RGB")
    lo, hi = imagenes.a_blanco_y_negro(niebla, "normal").getextrema()
    assert lo > 60 and hi < 250


def _rat(x):
    f = Fraction(x).limit_denominator(10000)
    return IFDRational(f.numerator, f.denominator)


def test_exif_gps_altitud(tmp_path):
    ex = Image.Exif()
    ex[0x8769] = {0x9003: "2025:05:11 10:05:00", 0x9011: "+02:00"}
    ex[0x8825] = {1: "N", 2: (_rat(40), _rat(47), _rat(31.2)), 3: "W", 4: (_rat(3), _rat(57), _rat(14.4)),
                  5: b"\x00", 6: _rat(1150.5)}
    ruta = tmp_path / "a.jpg"
    Image.new("RGB", (64, 48), "white").save(ruta, exif=ex.tobytes())
    d = imagenes.exif_basico(ruta)
    assert d["fecha"] == datetime(2025, 5, 11, 10, 5, tzinfo=timezone(timedelta(hours=2)))
    assert d["lat"] == pytest.approx(40.792, abs=1e-3)
    assert d["lon"] == pytest.approx(-3.954, abs=1e-3)
    assert d["alt"] == pytest.approx(1150.5, abs=0.1)


# ---------------------------------------------------------------------- Fotos (osxphotos simulado)
def test_photoinfo_icloud_sin_original(tmp_path):
    previa = tmp_path / "UUID_1_105_c.jpeg"
    Image.new("RGB", (32, 32)).save(previa)
    p = SimpleNamespace(
        uuid="UUID", hasadjustments=False, path_edited=None, path=None, ismissing=True,
        path_derivatives=[str(tmp_path / "x.mov"), str(previa)], date=datetime(2024, 3, 1, 12, tzinfo=timezone.utc),
        location=(40.4, -3.7), place=None, labels=["Plastic Bag", "Tree"], score=SimpleNamespace(overall=0.4),
        face_info=[], original_filename="IMG_1.HEIC", screenshot=False, selfie=False, favorite=True,
        width=4032, height=3024, date_modified=None,
    )
    f = foto_de_photoinfo(p)
    assert f.en_icloud is True
    assert f.ruta_analisis == str(previa)
    assert f.ruta_original is None
    assert f.etiquetas == ["Plastic Bag", "Tree"]
    assert f.estetica == pytest.approx(0.4)


# ---------------------------------------------------------------------- puntuación
class _Ix:
    def __init__(self, E, fotos):
        self.E = E / np.linalg.norm(E, axis=1, keepdims=True)
        self.fotos = fotos
        self.uuids = [f["uuid"] for f in fotos]
        self.pos = {u: i for i, u in enumerate(self.uuids)}

    def __len__(self):
        return len(self.fotos)

    def foto(self, u):
        return self.fotos[self.pos[u]] if u in self.pos else None


CATS = ["vuelos", "acumulaciones", "islas", "construcciones", "erosiones", "instalaciones", "huellas", "apariciones"]


def _textos(dim):
    eye = np.eye(dim, dtype=np.float32)
    g = {f"cat:{c}": eye[[k]] for k, c in enumerate(CATS)}
    g.update({f"conf:{c}": eye[[9]] for c in CATS})
    g["arte"] = eye[[10]]
    g["excluir"] = eye[[11]]
    g["naturaleza"] = eye[[12]]
    g["urbano"] = eye[[13]]
    g["camino"] = eye[[14]]
    g["sucesos"] = eye[[15, 16]]
    cfg = {"categorias": [{"id": c, "nombre": c.capitalize(), "prompts": ["x"], "etiquetas_apple": ["plastic bag"] if c == "vuelos" else []} for c in CATS],
           "global": {"etiquetas_excluir": ["screenshot"]},
           "paseo": {"sucesos": [{"frase": "Pasan nubes", "palabra": "NUBES", "prompt": "a"}, {"frase": "Un perro", "palabra": "PERRO", "prompt": "b"}]}}
    return cfg, g


class _Tx:
    def __init__(self, cfg, g):
        self.cfg, self.g = cfg, g

    def __getitem__(self, k):
        return self.g[k]

    def get(self, k):
        return self.g.get(k)


def test_puntuacion_ordena_y_penaliza():
    rng = np.random.default_rng(0)
    dim = 20
    E = rng.normal(0, 0.05, (30, dim)).astype(np.float32)
    E[0, 0] += 1.0          # foto 0 = vuelos clarísimo
    E[1, 0] += 1.0          # foto 1 = igual, pero es captura de pantalla
    E[2, 3] += 1.0          # foto 2 = construcciones
    fotos = [{"uuid": f"u{i}", "etiquetas": [], "captura": i == 1} for i in range(30)]
    fotos[5]["etiquetas"] = ["Plastic Bag"]
    E[5, 0] += 0.3
    cfg, g = _textos(dim)
    pt = Puntuador(_Ix(E, fotos), _Tx(cfg, g))
    vuelos = [d["uuid"] for d in pt.candidatas("vuelos", 5)]
    assert vuelos[0] == "u0"
    assert "u1" not in vuelos[:3]           # la captura queda abajo
    assert vuelos.index("u5") < 4            # la etiqueta de Fotos ayuda
    assert pt.candidatas("construcciones", 1)[0]["uuid"] == "u2"
    assert pt.ficha(0)["sugerida"] == "vuelos"


def test_etiquetas_normalizadas():
    assert normalizar("Óxido") == "oxido"
    assert coincide({"plastic bag", "tree"}, {"plastic bag"}) == ["plastic bag"]
    assert coincide({"heno"}, {"heno", "paja"}) == ["heno"]


# ---------------------------------------------------------------------- paseos
def _paseo_sintetico():
    dim = 20
    rng = np.random.default_rng(1)
    E = rng.normal(0, 0.05, (60, dim)).astype(np.float32)
    fotos = []
    t0 = datetime(2025, 5, 11, 10, 0, tzinfo=timezone.utc).timestamp()
    for i in range(60):
        if i < 40:   # caminata: 40 fotos cada 6 min, avanzando por el monte
            E[i, 12] += 1.0
            ts = t0 + i * 360
            lat, lon = 40.79 + i * 0.001, -3.95 + i * 0.0007
        else:        # fotos sueltas de ciudad, otros días
            E[i, 13] += 1.0
            ts = t0 + 86400 * (i - 38)
            lat, lon = 40.41, -3.70
        fotos.append({"uuid": f"u{i}", "ts": ts, "fecha": datetime.fromtimestamp(ts, timezone.utc).isoformat(),
                      "lat": lat, "lon": lon, "alt": 1000 + i * 10 if i < 40 else None, "lugar_corto": "Sierra" if i < 40 else "Madrid"})
    # una foto «intrusa» (recibida por WhatsApp) en mitad de la caminata con GPS de otra ciudad
    fotos[20]["lat"], fotos[20]["lon"] = 41.38, 2.17
    cfg, g = _textos(dim)
    ix = _Ix(E, fotos)
    return Paseos(ix, _Tx(cfg, g))


def test_detecta_caminata_y_tolera_intrusa():
    pa = _paseo_sintetico()
    ps = pa.detectar(min_fotos=8)
    assert len(ps) == 1
    p = ps[0]
    assert p["fotos"] == 39          # 40 menos la intrusa
    assert 3 < p["km"] < 6
    assert p["id"] == f"p{int(pa.ix.fotos[0]['ts'])}"  # id estable: instante de la primera foto


def test_pico_gps_no_infla_km_y_rango_reabrible():
    pa = _paseo_sintetico()
    base = pa.detectar(min_fotos=8)[0]["km"]
    pa2 = _paseo_sintetico()
    pa2.ix.fotos[15]["lat"] += 0.03   # una posición desviada ~3 km que va y vuelve
    pa2._paseos = None
    assert abs(pa2.detectar(min_fotos=8)[0]["km"] - base) < 0.2
    t0 = pa2.ix.fotos[0]["ts"]
    r = pa2.por_rango(t0, t0 + 3600)
    pa3 = _paseo_sintetico()       # «reinicio del servidor»: el rango se reconstruye por su id
    assert pa3.por_id(r["id"])["fotos"] == r["fotos"]


def test_sugerencia_12_con_origen_y_final():
    pa = _paseo_sintetico()
    p = pa.detectar(min_fotos=8)[0]
    r = pa.sugerir(p["id"], 12)
    assert len(r["sugeridas"]) == 12
    ts = [pa.ix.foto(u)["ts"] for u in r["sugeridas"]]
    assert ts == sorted(ts)
    assert r["sugeridas"][0] == "u0" and r["sugeridas"][-1] == "u39"
    fichas = {f["uuid"]: f for f in r["todas"]}
    assert fichas["u0"]["km"] == 0
    assert fichas["u10"]["frase"] in ("Pasan nubes", "Un perro")


def test_suceso_singular_frente_al_comun():
    pa = _paseo_sintetico()
    E = pa.ix.E.copy()
    E[:40, 15] += 0.3          # «nubes»: sale en todas las fotos del paseo
    E[5, 16] += 0.32           # el perro solo aparece en la foto 5 (algo menos parecido en absoluto)
    pa.ix.E = E / np.linalg.norm(E, axis=1, keepdims=True)
    pa.suc_sim = pa.ix.E @ pa.tx.get("sucesos").T
    r = pa.sugerir(pa.detectar(min_fotos=8)[0]["id"], 12)
    fichas = {f["uuid"]: f for f in r["todas"]}
    assert fichas["u5"]["frase"] == "Un perro"
    assert fichas["u6"]["frase"] == "Pasan nubes"


def test_textos_fulton():
    assert frase_borrador("10:05", 3.25, 1150, "Pasan nubes") == "10:05 · km 3,2 · 1.150 m — Pasan nubes"
    f = [{"lugar": "Cercedilla", "fecha": "2025-05-11T10:00:00+02:00", "km": 0},
         {"lugar": "Siete Picos", "fecha": "2025-05-11T14:10:00+02:00", "km": 9.4}]
    assert linea_paseo(f, f[0]["fecha"]) == "UNA CAMINATA DE 4 HORAS DESDE CERCEDILLA HASTA SIETE PICOS · 9,4 KM · 11 MAYO 2025"
    lineal = [dict(f[0], lugar="Sierra", lat=40.0, lon=-3.0), dict(f[1], lugar="Sierra", lat=40.06, lon=-3.0)]
    assert "CIRCULAR" not in linea_paseo(lineal, f[0]["fecha"])
    vuelta = [dict(lineal[0]), dict(lineal[1], lat=40.0005)]
    assert linea_paseo(vuelta, f[0]["fecha"]).startswith("UNA CAMINATA CIRCULAR DE 4 HORAS DESDE Y HASTA SIERRA")
    assert km_entre((40.0, -3.0), (40.0, -3.0)) == 0


# ---------------------------------------------------------------------- láminas
def _dentro(L):
    for e in L.elementos:
        if isinstance(e, laminas.Foto):
            assert 0 <= e.x and e.x + e.lado <= L.ancho and 0 <= e.y and e.y + e.lado <= L.alto
        if isinstance(e, laminas.Texto):
            assert 0 <= e.y <= L.alto


def test_maquetas_y_pdf(tmp_path):
    fu = laminas.Fuentes()
    im = Image.new("RGB", (300, 300), "gray")
    arte = [{"im": im, "categoria": CATS[k % 8], "pie": "Calle de Toledo, Madrid · marzo 2025"} for k in range(24)]
    la = laminas.maquetar_arte(arte, fu, "Nombre Apellido", {c: c.capitalize() for c in CATS})
    assert len(la) == 4
    assert sum(isinstance(e, laminas.Foto) for e in la[0].elementos) == 6
    paseo = [{"im": im, "frase": f"10:{k:02d} · km {k} — Pasan nubes muy despacio sobre el collado", "km": k, "alt": 1000 + 30 * k,
              "lat": 40 + k / 1000, "lon": -3 - k / 1000} for k in range(13)]
    for diseno in ("rejilla", "crece"):
        lp = laminas.maquetar_paseo(paseo, fu, "NUBES", "CAMINATA DE 4 HORAS DESDE A HASTA B", "N A", diseno=diseno)
        assert len(lp) == 2
        assert sum(isinstance(e, laminas.Foto) for L in lp for e in L.elementos) == 13
        for L in lp:
            _dentro(L)
    for L in la:
        _dentro(L)
    ruta = laminas.pdf(la + lp, tmp_path / "x.pdf", fu)
    assert ruta.stat().st_size > 1000
    r = laminas.raster(lp[1], fu, 40)
    assert r.size == (round(420 * 40 / 25.4), round(297 * 40 / 25.4))


def test_config_categorias_valida():
    from arte_involuntario import rutas

    cfg = json.loads(rutas.CONFIG_CATEGORIAS.read_text(encoding="utf-8"))
    assert [c["id"] for c in cfg["categorias"]] == CATS
    for c in cfg["categorias"]:
        assert len(c["prompts"]) >= 15, c["id"]
        assert c["nombre"] and c["definicion"]
    assert len(cfg["paseo"]["sucesos"]) >= 40
    assert cfg["global"]["prompts_excluir"]


def test_traduccion_busquedas():
    from arte_involuntario.traduccion import a_ingles

    assert a_ingles("bolsa de plástico enganchada en un árbol") == "a photo of plastic bag caught in a tree"
    assert a_ingles("zapatillas colgadas de cables eléctricos") == "a photo of sneakers hanging from power lines"
    assert a_ingles("rusty gate in a field") == "rusty gate in a field"  # el inglés no se toca
