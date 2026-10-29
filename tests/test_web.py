"""Pruebas de la galería sin modelo ni fototeca: guardar la selección, «Generar» y el puerto al arrancar."""
from __future__ import annotations

import json
import socket
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace

import pytest

from arte_involuntario import generar, rutas, servidor
from arte_involuntario.modelo import clave_modelo

_sin_proxy = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _pedir(url: str, cuerpo: dict | None = None) -> tuple[int, dict]:
    datos = json.dumps(cuerpo).encode() if cuerpo is not None else None
    req = urllib.request.Request(url, datos, {"Content-Type": "application/json"})
    try:
        with _sin_proxy.open(req, timeout=5) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def _arrancar(handler) -> tuple[ThreadingHTTPServer, int]:
    srv = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, srv.server_address[1]


def _identidad(preset: str = "rapido", **cambios) -> dict:
    yo = SimpleNamespace(preset=preset, clave=clave_modelo(preset))
    return {**servidor.App.quien(yo), **cambios}


@pytest.fixture
def galeria(tmp_path, monkeypatch):
    """La galería con una App mínima, la selección en una carpeta temporal y un «generar» falso."""
    monkeypatch.setattr(rutas, "DATOS", tmp_path)
    monkeypatch.setattr(rutas, "SELECCION", tmp_path / "seleccion.json")
    monkeypatch.setattr(rutas, "preparar", lambda: None)
    generadas: list[dict] = []
    monkeypatch.setattr(generar, "generar", lambda sel, aviso=print: generadas.append(sel) or {"laminas": 0})
    app = SimpleNamespace(trabajo_generar=servidor.Trabajo(), quien=_identidad)
    srv, puerto = _arrancar(servidor.crear_handler(app))
    yield SimpleNamespace(url=f"http://127.0.0.1:{puerto}", generadas=generadas, app=app)
    srv.shutdown()
    srv.server_close()


def _esperar_generar(g):
    for _ in range(100):
        if g.app.trabajo_generar.estado != "trabajando":
            return
        time.sleep(0.02)
    raise AssertionError("la generación falsa no acaba")


# ---------------------------------------------------------------------- selección y «Generar»
def test_generar_devuelve_la_rev_y_no_hay_falso_conflicto(galeria):
    g = galeria
    cod, d = _pedir(g.url + "/api/seleccion", {"autor": "A", "arte": [], "_rev": 0})
    assert cod == 200 and d["_rev"] == 1
    cod, d = _pedir(g.url + "/api/generar", {"autor": "A", "arte": [], "_rev": 1})
    assert cod == 200 and d["ok"] is True and d["_rev"] == 2
    _esperar_generar(g)
    # el primer cambio después de generar, con la _rev que devolvió «Generar»: se guarda (antes, 409)
    cod, d = _pedir(g.url + "/api/seleccion", {"autor": "B", "arte": [], "_rev": 2})
    assert cod == 200 and d["_rev"] == 3
    # dos «Generar» seguidos
    for rev in (3, 4):
        cod, d = _pedir(g.url + "/api/generar", {"autor": "B", "arte": [], "_rev": rev})
        assert cod == 200 and d["_rev"] == rev + 1
        _esperar_generar(g)
    assert [s["autor"] for s in g.generadas] == ["A", "B", "B"]
    # un conflicto de verdad (otra pestaña con una versión vieja) se sigue detectando, también al generar
    for ruta in ("/api/seleccion", "/api/generar"):
        cod, d = _pedir(g.url + ruta, {"autor": "VIEJA", "arte": [], "_rev": 1})
        assert cod == 409 and d["error"] == "conflicto" and d["seleccion"]["_rev"] == 5
    assert json.loads(rutas.SELECCION.read_text(encoding="utf-8"))["autor"] == "B"
    assert len(g.generadas) == 3


def test_el_aviso_de_seleccion_danada_no_se_guarda(galeria):
    g = galeria
    cod, d = _pedir(g.url + "/api/seleccion", {"autor": "A", "_aviso": "La selección estaba dañada", "_rev": 0})
    assert cod == 200
    assert "_aviso" not in json.loads(rutas.SELECCION.read_text(encoding="utf-8"))
    cod, d = _pedir(g.url + "/api/generar", {"autor": "A", "arte": [], "_aviso": "otra vez", "_rev": d["_rev"]})
    assert cod == 200
    _esperar_generar(g)
    assert "_aviso" not in json.loads(rutas.SELECCION.read_text(encoding="utf-8"))
    assert "_aviso" not in g.generadas[-1]


# ---------------------------------------------------------------------- ¿galería ya abierta?
class _Vieja(BaseHTTPRequestHandler):
    """Una galería de una versión anterior (sin /api/quien) u otro programa."""

    def do_GET(self):
        self.send_error(404)

    def log_message(self, *a):
        pass


def _puerto_libre() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_solo_reutiliza_la_galeria_de_la_misma_carpeta_datos_y_modelo(tmp_path, monkeypatch):
    monkeypatch.setattr(rutas, "DATOS", tmp_path / "datos")
    misma = SimpleNamespace(trabajo_generar=None, quien=_identidad)
    otra = SimpleNamespace(trabajo_generar=None, quien=lambda: _identidad(datos=str(tmp_path / "otra" / "datos")))
    servidores = [_arrancar(servidor.crear_handler(misma)), _arrancar(servidor.crear_handler(otra)), _arrancar(_Vieja)]
    try:
        (_, p_misma), (_, p_otra), (_, p_vieja) = servidores
        libre = _puerto_libre()
        assert servidor._galeria_en(libre) is None
        assert servidor._galeria_en(p_vieja) == {}

        encontrada, otras = servidor._galerias_abiertas([libre, p_otra, p_vieja, p_misma], "rapido")
        assert encontrada == p_misma
        assert [p for p, _ in otras] == [p_otra, p_vieja]
        assert otras[0][1]["datos"] == str(tmp_path / "otra" / "datos") and otras[1][1] == {}
        # el mismo modelo escrito como arquitectura:pesos también es «la misma»
        assert servidor._galerias_abiertas([p_misma], clave_modelo("rapido"))[0] == p_misma
        # con otro modelo, ninguna sirve: se arranca otra en el siguiente puerto libre
        encontrada, otras = servidor._galerias_abiertas([p_otra, p_vieja, p_misma], "preciso")
        assert encontrada is None and [p for p, _ in otras] == [p_otra, p_vieja, p_misma]
        # otra carpeta del proyecto (otra versión descargada) con los mismos datos tampoco
        assert not servidor._es_esta(_identidad(raiz="/otra/carpeta"), "rapido")
        assert servidor._es_esta(_identidad(), "rapido")
    finally:
        for srv, _ in servidores:
            srv.shutdown()
            srv.server_close()
