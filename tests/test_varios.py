"""Pruebas sin modelo ni fototeca: limpieza del GPS de los paseos, modelo recordado por la
galería, recuentos del índice, validación de --modelo y clave de ia.env guardada con TextEdit."""
from __future__ import annotations

import math
import random
from types import SimpleNamespace

import numpy as np
import pytest

from arte_involuntario import cli, fuentes, ia, indice, modelo, rutas
from arte_involuntario.fuentes import Foto
from arte_involuntario.paseos import Paseos

# ---------------------------------------------------------------------- GPS de los paseos
LAT0, LON0 = 40.78, -4.00
KM_LAT = 111.2
KM_LON = 111.2 * math.cos(math.radians(LAT0))


def _km(pts, dt=360):
    """Km que mide Paseos._traza para posiciones tomadas cada `dt` segundos."""
    fotos = [{"ts": 1.7e9 + k * dt, "lat": la, "lon": lo} for k, (la, lo) in enumerate(pts)]
    pa = Paseos.__new__(Paseos)
    pa.ix = SimpleNamespace(fotos=fotos)
    traza = pa._traza(list(range(len(fotos))))
    return traza[-1][1]


def _p(este_km, norte_km):
    return (LAT0 + norte_km / KM_LAT, LON0 + este_km / KM_LON)


def _recta(n=30):  # 6 km hacia el norte
    return [_p(0, 6 * k / (n - 1)) for k in range(n)]


def _desviar(pts, k, km_este):
    pts = list(pts)
    pts[k] = (pts[k][0], pts[k][1] + km_este / KM_LON)
    return pts


@pytest.mark.parametrize("nombre,pts", [
    ("limpia", _recta()),
    ("primera a 2 km", _desviar(_recta(), 0, 2)),
    ("primera a 4 km", _desviar(_recta(), 0, 4)),
    ("última a 2 km", _desviar(_recta(), -1, 2)),
    ("última a 4 km", _desviar(_recta(), -1, 4)),
    ("central a 4 km", _desviar(_recta(), 15, 4)),
    ("dos seguidas a 2 km", _desviar(_desviar(_recta(), 15, 2), 16, 2)),
    ("segunda y tercera a 2 km", _desviar(_desviar(_recta(), 1, 2), 2, 2)),
])
def test_gps_recta_6_km_con_posiciones_erroneas(nombre, pts):
    assert _km(pts) == pytest.approx(6.0, rel=0.05), nombre


@pytest.mark.parametrize("semilla", range(8))
def test_gps_temblor_25_m_en_120_fotos(semilla):
    r = random.Random(semilla)
    pts = [(la + r.gauss(0, .025) / KM_LAT, lo + r.gauss(0, .025) / KM_LON) for la, lo in _recta(120)]
    assert _km(pts, dt=90) == pytest.approx(6.0, rel=0.05)


def test_gps_respeta_cumbres_y_curvas():
    # ida y vuelta a una cumbre con una o dos fotos arriba y fotos cada 10 min: no es un pico del GPS
    ida = [_p(0, 0.6 * k) for k in range(6)]
    vuelta = [_p(0.02, 3 - 0.6 * k) for k in range(1, 6)]
    assert _km(ida + vuelta, dt=600) == pytest.approx(6.0, rel=0.03)
    assert _km(ida[:-1] + [_p(0, 3), _p(0.01, 3)] + vuelta, dt=600) == pytest.approx(6.0, rel=0.03)
    # zigzag de tramos de 500 m con una foto cada 100 m: las esquinas no se recortan
    z, x, y = [_p(0, 0)], 0.0, 0.0
    for t in range(60):
        ang = math.radians(45 if (t // 5) % 2 == 0 else 135)
        x, y = x + 0.1 * math.cos(ang), y + 0.1 * math.sin(ang)
        z.append(_p(x, y))
    assert _km(z, dt=120) == pytest.approx(6.0, rel=0.03)


# ---------------------------------------------------------------------- índice y línea de órdenes
@pytest.fixture
def datos(tmp_path, monkeypatch):
    """Índice vacío en una carpeta temporal y una «carpeta de fotos» simulada."""
    d = tmp_path / "datos"
    for k, v in {"DATOS": d, "SALIDA": tmp_path / "salida", "MODELOS": d / "modelos", "BD": d / "fototeca.sqlite",
                 "ORIGINALES": d / "originales", "MINIATURAS_ICLOUD": d / "miniaturas_icloud",
                 "TEXTOS_CACHE": d / "textos"}.items():
        monkeypatch.setattr(rutas, k, v)
    carpetas = {"A": ["a1", "a2", "a3"], "B": ["b1"]}
    leidas = []

    def desde_carpeta(carpeta, desde=None, hasta=None):
        leidas.append(carpeta)
        for k, u in enumerate(carpetas[str(carpeta)]):
            yield Foto(uuid=u, fuente="carpeta", ruta_analisis=f"/x/{u}.jpg", ts=1.7e9 + k, firma=f"f{u}")

    class ModeloFalso:
        def __init__(self, preset):
            self.clave = modelo.clave_modelo(preset)

    corte = {"n": None}  # None: analiza todo; n: «Ctrl+C» tras n fotos

    def vectorizar(m, lote=32, hilos=4):
        trabajo = indice.pendientes(m.clave)[:corte["n"]]
        con = indice.conectar()
        con.executemany("INSERT OR REPLACE INTO vectores (uuid, modelo, v, error, firma) VALUES (?,?,?,?,?)",
                        [(u, m.clave, np.ones(4, np.float16).tobytes(), None, fi) for u, _, fi in trabajo])
        con.commit()
        con.close()
        return {"nuevas": len(trabajo), "errores": 0}

    monkeypatch.setattr(fuentes, "desde_carpeta", desde_carpeta)
    monkeypatch.setattr(modelo, "Modelo", ModeloFalso)
    monkeypatch.setattr(indice, "vectorizar", vectorizar)
    return SimpleNamespace(leidas=leidas, corte=corte)


def _recordado():
    return cli._modelo_de(SimpleNamespace(modelo=None))


def test_analisis_cortado_no_cambia_el_modelo_de_la_galeria(datos, capsys):
    cli.main(["analizar", "--carpeta", "A"])
    assert indice.modelo_usado() == "rapido"
    datos.corte["n"] = 1
    cli.main(["analizar", "--carpeta", "A", "--modelo", "preciso"])
    out = capsys.readouterr().out
    assert indice.modelo_usado() == "rapido" and _recordado() == "rapido"
    assert "La galería sigue usando «rapido» hasta que termines de analizar con «preciso»" in out
    assert "./arte galeria --modelo preciso" in out
    datos.corte["n"] = None
    cli.main(["analizar", "--carpeta", "A", "--modelo", "preciso"])
    assert indice.modelo_usado() == "preciso"


def test_primer_analisis_cortado_con_otro_modelo(datos, capsys):
    # nunca se analizó con «rapido» y el análisis con «preciso» se cortó: la galería usa «preciso»
    datos.corte["n"] = 2
    cli.main(["analizar", "--carpeta", "A", "--modelo", "preciso"])
    assert indice.modelo_usado() is None
    assert _recordado() == "preciso"
    cli.main(["estado"])
    assert "modelo de la galería: preciso" in capsys.readouterr().out


def test_estadisticas_solo_cuentan_la_fuente_actual(datos, capsys):
    cli.main(["analizar", "--carpeta", "A"])
    datos.corte["n"] = 0
    cli.main(["analizar", "--carpeta", "B", "--modelo", "preciso"])  # otra carpeta, sin analizar
    est = indice.estadisticas()
    assert est["fotos"] == 1
    assert est["analizadas"].get(modelo.clave_modelo("rapido"), 0) == 0  # los vectores de A siguen, pero no cuentan
    con = indice.conectar()
    con.execute("INSERT INTO vectores (uuid, modelo, v, error, firma) VALUES ('a1', 'x:y', NULL, 'rota', 'f')")
    con.commit()
    con.close()
    assert indice.estadisticas()["errores"] == 0
    datos.corte["n"] = None
    cli.main(["analizar", "--carpeta", "B"])
    assert "✓ Analizadas 1 fotos" in capsys.readouterr().out


@pytest.mark.parametrize("orden", [["analizar", "--carpeta", "A"], ["todo", "--carpeta", "A", "--no-abrir"]])
def test_modelo_desconocido_se_avisa_antes_de_leer(datos, capsys, orden):
    with pytest.raises(SystemExit) as e:
        cli.main(orden + ["--modelo", "grande"])
    assert e.value.code == 1
    assert "Modelo desconocido «grande»" in capsys.readouterr().out
    assert datos.leidas == []
    assert indice.ultima_lectura() is None


# ---------------------------------------------------------------------- ia.env
CLAVE = "gsk_A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8S9t0U1v2W3x4Y5z6A1b2"


@pytest.mark.parametrize("nombre,texto", [
    ("ia.env.rtf", r"""{\rtf1\ansi\ansicpg1252\cocoartf2822
\cocoatextscaling0\cocoaplatform0{\fonttbl\f0\fswiss\fcharset0 Helvetica;}
{\colortbl;\red255\green255\blue255;}
\pard\tx566\tx1133\pardirnatural\partightenfactor0

\f0\fs24 \cf0 \
GROQ_API_KEY=""" + CLAVE + "}"),
    ("ia.env.rtf", r"""{\rtf1\ansi
\f0\fs24 \cf0 ARTE_IA_CLAVE=""" + CLAVE + "\\\n}"),
    ("ia.env.rtf", r"""{\rtf1\ansi
\f0\fs24 \cf0 GROQ_API_KEY=""" + CLAVE + "}"),
    ("ia.env", f'export GROQ_API_KEY="{CLAVE}"\n'),
])
def test_clave_de_ia_env(tmp_path, monkeypatch, nombre, texto):
    for k in ("ARTE_IA_CLAVE", "GROQ_API_KEY", "ARTE_IA_URL", "ARTE_IA_MODELO"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(rutas, "RAIZ", tmp_path)
    (tmp_path / nombre).write_text(texto, encoding="utf-8")
    assert ia._config()["clave"] == CLAVE


def test_clave_rtf_de_otro_proveedor(tmp_path, monkeypatch):
    for k in ("ARTE_IA_CLAVE", "GROQ_API_KEY", "ARTE_IA_URL", "ARTE_IA_MODELO"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(rutas, "RAIZ", tmp_path)
    (tmp_path / "ia.env.rtf").write_text("{\\rtf1\\ansi\\\nARTE_IA_CLAVE=sk-or-v1-abc123}\n"
                                         "ARTE_IA_URL=https://openrouter.ai/api/v1}", encoding="utf-8")
    c = ia._config()
    assert c["clave"] == "sk-or-v1-abc123"
    assert c["url"] == "https://openrouter.ai/api/v1"
