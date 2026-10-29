"""Descargas de iCloud con un PhotoKit falso (sin macOS, sin fototeca): el proceso hijo, los
cuelgues, las caídas, los cortes y que la app siempre termine y no pierda lo que imprime.

El falso se instala como paquetes `osxphotos`, `Photos`, `Quartz`, `Foundation` y `objc` en una
carpeta que solo ve el proceso hijo (PYTHONPATH). Lo que hace con cada foto depende del uuid:
  bien-*   exporta una imagen           live-*   Live Photo (su export propio no vuelve nunca)
  cuelga-* redirige stdout como wurlitzer y no vuelve nunca
  muere-*  el proceso termina de golpe  falla-*  error de PhotoKit   nohay-*  no está en Fotos
"""
from __future__ import annotations

import io
import json
import os
import queue
import signal
import subprocess
import sys
import textwrap
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from arte_involuntario import descargas, disco, exportar_photokit, icloud, rutas

RAIZ = Path(__file__).resolve().parent.parent

FALSOS = {
    "osxphotos/__init__.py": "",
    "osxphotos/photokit.py": '''
        import os, pathlib, time
        open(pathlib.Path(__file__).resolve().parent.parent / "pids.txt", "a").write(f"{os.getpid()}\\n")
        PHOTOS_VERSION_CURRENT, PHOTOS_VERSION_ORIGINAL = 0, 2

        class _PHAsset:
            def __init__(self, uuid):
                self.uuid = uuid

        class PhotoLibrary:
            def __init__(self):
                self._phimagemanager = "gestor"

            def fetch_uuid(self, uuid):
                u = uuid.split("/")[0]
                if u.startswith("nohay"):
                    raise RuntimeError("Fetch did not return result")
                cls = LivePhotoAsset if u.startswith("live") else PhotoAsset
                return cls(self._phimagemanager, _PHAsset(u))

        class PhotoAsset:
            def __init__(self, manager, phasset):
                assert manager == "gestor"
                self.phasset = phasset
                self.isphoto = True
                self.original_filename = f"IMG_{phasset.uuid}.HEIC"

            def export(self, dest, filename=None, version=PHOTOS_VERSION_CURRENT, overwrite=False, **kw):
                u = self.phasset.uuid
                assert version == PHOTOS_VERSION_CURRENT and overwrite and pathlib.Path(dest).is_dir()
                os.write(1, b"ruido de PhotoKit\\n@@{esto no es json\\n")
                if u.startswith("cuelga"):  # como osxphotos: wurlitzer se queda con stdout y stderr
                    r, w = os.pipe()
                    os.dup2(w, 1)
                    os.dup2(w, 2)
                    time.sleep(3600)
                if u.startswith("muere"):
                    os._exit(3)
                if u.startswith("falla"):
                    raise RuntimeError("Could not get image data")
                from PIL import Image
                ruta = pathlib.Path(dest) / (pathlib.Path(filename).stem + ".jpeg")
                Image.new("RGB", (60, 40), "green").save(ruta)
                return [str(ruta)]

        class LivePhotoAsset(PhotoAsset):
            def export(self, *a, **k):
                time.sleep(3600)  # fuera del hilo principal, el run loop no vuelve nunca
    ''',
    "Photos.py": '''
        import os, pathlib, time
        open(pathlib.Path(__file__).resolve().parent / "pids.txt", "a").write(f"{os.getpid()}\\n")
        PHImageRequestOptionsDeliveryModeHighQualityFormat = 1
        PHImageRequestOptionsResizeModeExact = 2
        PHImageRequestOptionsVersionCurrent = 0
        PHImageContentModeAspectFit = 0

        class _Resultado(list):
            def count(self):
                return len(self)

            def objectAtIndex_(self, i):
                return self[i]

        class PHAsset:
            @staticmethod
            def fetchAssetsWithLocalIdentifiers_options_(ids, op):
                return _Resultado(i.split("/")[0] for i in ids if not i.startswith("nohay"))

        class PHImageRequestOptions:
            @classmethod
            def alloc(cls):
                return cls()

            def init(self):
                return self

            def __getattr__(self, n):
                if n.startswith("set"):
                    return lambda v: self.__dict__.__setitem__(n[3:-1], v)
                raise AttributeError(n)

        class _Imagen:
            def __init__(self, lado):
                self.lado = lado

            def CGImageForProposedRect_context_hints_(self, *a):
                return (int(self.lado), int(self.lado * 3 / 4)), None

        class PHImageManager:
            @classmethod
            def defaultManager(cls):
                return cls()

            def requestImageForAsset_targetSize_contentMode_options_resultHandler_(self, u, tam, modo, op, fn):
                assert op.Synchronous is True and op.NetworkAccessAllowed is True
                if u.startswith("cuelga"):
                    time.sleep(3600)
                if u.startswith("muere"):
                    os._exit(3)
                if u.startswith("falla"):
                    return fn(None, {"PHImageErrorKey": "error de red"})
                fn(_Imagen(tam[0]), {})
    ''',
    "Quartz.py": '''
        kCGImageDestinationLossyCompressionQuality = "calidad"

        def CGImageDestinationCreateWithURL(url, uti, n, op):
            assert uti == "public.jpeg"
            return {"ruta": url.ruta}

        def CGImageDestinationAddImage(dst, cg, props):
            dst["tam"] = cg

        def CGImageDestinationFinalize(dst):
            from PIL import Image
            Image.new("RGB", dst["tam"], "blue").save(dst["ruta"], "JPEG")
            return True
    ''',
    "Foundation.py": '''
        class NSURL:
            @staticmethod
            def fileURLWithPath_(ruta):
                u = NSURL()
                u.ruta = ruta
                return u
    ''',
    "objc.py": '''
        import contextlib

        def autorelease_pool():
            return contextlib.nullcontext()
    ''',
}


def _vivo(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    try:  # un zombi ya no cuenta (en Linux)
        return Path(f"/proc/{pid}/stat").read_text().split(")")[-1].split()[0] != "Z"
    except OSError:
        return True


def _instalar_falsos(dir_: Path) -> Path:
    for nombre, codigo in FALSOS.items():
        f = dir_ / nombre
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(textwrap.dedent(codigo))
    return dir_


def _pids(falsos: Path) -> list[int]:
    f = falsos / "pids.txt"
    return [int(x) for x in f.read_text().split()] if f.exists() else []


@pytest.fixture
def entorno(tmp_path, monkeypatch):
    falsos = _instalar_falsos(tmp_path / "falsos")
    monkeypatch.setenv("PYTHONPATH", os.pathsep.join([str(falsos), os.environ.get("PYTHONPATH", "")]))
    monkeypatch.setattr(rutas, "ORIGINALES", tmp_path / "originales")
    monkeypatch.setattr(rutas, "MINIATURAS_ICLOUD", tmp_path / "miniaturas")
    monkeypatch.setattr(descargas, "MAPA", tmp_path / "originales" / "mapa.json")
    monkeypatch.setattr(descargas, "SEGUNDOS_POR_FOTO", 5)  # las pruebas con cuelgue lo bajan
    monkeypatch.setattr(icloud, "SEGUNDOS_POR_MINIATURA", 5)
    monkeypatch.setattr(icloud, "_autorizar", lambda: None)
    monkeypatch.setattr(disco, "cabe", lambda *a, **k: True)
    avisos: list[str] = []
    yield SimpleNamespace(falsos=falsos, tmp=tmp_path, avisos=avisos, aviso=avisos.append)
    # pase lo que pase: ningún proceso hijo sigue vivo ni queda como zombi
    assert not exportar_photokit._VIVOS
    assert not [p for p in _pids(falsos) if _vivo(p)]


def _fotos(*uuids):
    return [{"uuid": u, "fuente": "fotos", "nombre": f"{u}.heic"} for u in uuids]


# ---------------------------------------------------------------------- originales
def test_exporta_foto_y_live_photo_como_foto_fija(entorno):
    t0 = time.monotonic()
    r = descargas._descargar_icloud(_fotos("bien-1", "live-2"), entorno.aviso)
    assert time.monotonic() - t0 < 10
    assert sorted(r) == ["bien-1", "live-2"]
    for u, ruta in r.items():
        assert Path(ruta).parent == rutas.ORIGINALES / u and Image.open(ruta).size == (60, 40)
    assert entorno.avisos[1:] == ["  1/2 ✓ IMG_bien-1.jpeg", "  2/2 ✓ IMG_live-2.jpeg"]
    assert len(_pids(entorno.falsos)) == 1  # un solo proceso para toda la tanda


def test_cuelgue_mata_el_proceso_y_sigue(entorno, monkeypatch, capfd):
    monkeypatch.setattr(descargas, "SEGUNDOS_POR_FOTO", 1.5)
    t0 = time.monotonic()
    r = descargas._descargar_icloud(_fotos("cuelga-1", "bien-2"), print)
    dur = time.monotonic() - t0
    print("sigue saliendo")
    assert list(r) == ["bien-2"]
    assert dur < 1.5 + 5
    assert not (rutas.ORIGINALES / "cuelga-1").exists()
    assert len(_pids(entorno.falsos)) == 2  # el colgado se mató y se arrancó otro
    out = capfd.readouterr().out
    assert "1/2 ✗ cuelga-1.heic: iCloud no responde" in out
    assert "2/2 ✓ IMG_bien-2.jpeg" in out and out.rstrip().endswith("sigue saliendo")


def test_caida_y_error_cuentan_como_fallo(entorno):
    r = descargas._descargar_icloud(_fotos("muere-1", "bien-2", "falla-3", "bien-4"), entorno.aviso)
    assert sorted(r) == ["bien-2", "bien-4"]  # tras una caída se arranca otro proceso
    assert "  1/4 ✗ muere-1.heic: Fotos se cerró de golpe (se usará la previsualización)" in entorno.avisos
    assert "  3/4 ✗ falla-3.heic: Could not get image data (se usará la previsualización)" in entorno.avisos
    assert not (rutas.ORIGINALES / "muere-1").exists() and not (rutas.ORIGINALES / "falla-3").exists()


def test_tres_fallos_seguidos_paran(entorno):
    t0 = time.monotonic()
    r = descargas._descargar_icloud(_fotos("falla-1", "muere-2", "nohay-3", "bien-4"), entorno.aviso)
    assert r == {} and time.monotonic() - t0 < 10
    assert "  3/4 ✗ nohay-3.heic: Fotos no encuentra esta foto (¿se ha borrado?) (se usará la previsualización)" \
        in entorno.avisos
    assert not any("4/4" in a for a in entorno.avisos)
    assert entorno.avisos[-1].startswith("⚠ iCloud no está entregando las fotos")


def test_poco_disco_para_antes_de_pedir(entorno, monkeypatch):
    llamadas = []
    monkeypatch.setattr(disco, "cabe", lambda *a, **k: llamadas.append(1) or len(llamadas) == 1)
    r = descargas._descargar_icloud(_fotos("bien-1", "bien-2", "bien-3"), entorno.aviso)
    assert list(r) == ["bien-1"]
    assert entorno.avisos[-1].startswith("⚠ Poco espacio libre: dejo de descargar; las 2 restantes")
    monkeypatch.setattr(disco, "cabe", lambda *a, **k: False)
    pids = len(_pids(entorno.falsos))
    assert descargas._descargar_icloud(_fotos("bien-5"), entorno.aviso) == {}
    assert len(_pids(entorno.falsos)) == pids  # sin espacio no llega a arrancar ningún proceso


def test_resolver_usa_icloud_y_si_falla_la_previa(entorno, monkeypatch):
    monkeypatch.setattr(descargas, "sys", SimpleNamespace(platform="darwin"))
    previa = entorno.tmp / "previa.jpg"
    Image.new("RGB", (30, 20)).save(previa)
    fotos = _fotos("bien-1", "falla-2")
    fotos[1]["ruta_grande"] = str(previa)
    out = descargas.resolver(fotos, aviso=entorno.aviso)
    assert out["bien-1"]["origen"] == "icloud" and out["bien-1"]["lado"] == 40
    assert out["falla-2"] == {"ruta": str(previa), "origen": "previa", "lado": 20}
    assert "bien-1" in json.loads(descargas.MAPA.read_text())
    pids = len(_pids(entorno.falsos))
    out = descargas.resolver(fotos[:1], aviso=entorno.aviso)  # ya bajada: no se vuelve a pedir
    assert out["bien-1"]["origen"] == "icloud" and len(_pids(entorno.falsos)) == pids


def test_lector_ignora_el_ruido():
    cola: queue.Queue = queue.Queue()
    salida = io.StringIO('ruido\n@@{malo\n@@[1]\n@@{"uuid": "a", "ok": true, "ruta": "x"}\n')
    exportar_photokit._leer(salida, cola)
    assert cola.get_nowait() == {"uuid": "a", "ok": True, "ruta": "x"}
    assert cola.get_nowait() is None


# ---------------------------------------------------------------------- miniaturas (--traer-icloud)
def test_miniaturas_cuelgues_y_errores(entorno, monkeypatch, capsys):
    monkeypatch.setattr(icloud, "sys", SimpleNamespace(platform="darwin"))
    monkeypatch.setattr(disco, "libre", lambda *a: 10**12)
    monkeypatch.setattr(icloud, "SEGUNDOS_POR_MINIATURA", 1.5)
    t0 = time.monotonic()
    n = icloud.traer(["bien-1", "falla-2", "cuelga-3", "nohay-4", "bien-5"])
    assert n == 2 and time.monotonic() - t0 < 12
    for u in ("bien-1", "bien-5"):
        assert Image.open(icloud.ruta_cache(u)).size == (768, 576)
    assert not list(rutas.MINIATURAS_ICLOUD.glob("*.tmp.jpg"))
    out = capsys.readouterr().out
    assert "! falla-2: error de red" in out and "! cuelga-3: Fotos no contesta" in out
    assert "! nohay-4: Fotos no encuentra esta foto" in out and "2 miniaturas traídas" in out


def test_miniaturas_paran_si_icloud_no_responde(entorno, monkeypatch, capsys):
    monkeypatch.setattr(icloud, "sys", SimpleNamespace(platform="darwin"))
    monkeypatch.setattr(disco, "libre", lambda *a: 10**12)
    assert icloud.traer(["muere-1", "muere-2", "muere-3", "bien-4"]) == 0
    assert "dejo de pedir miniaturas" in capsys.readouterr().out
    assert not icloud.ruta_cache("bien-4").exists()


# ---------------------------------------------------------------------- la app termina siempre
_GUION = """
import sys, time
from pathlib import Path
from arte_involuntario import descargas, disco, icloud, rutas
icloud._autorizar = lambda: None
disco.cabe = lambda *a, **k: True
rutas.ORIGINALES = Path(sys.argv[1])
descargas.SEGUNDOS_POR_FOTO = float(sys.argv[2])
uuids = sys.argv[3:]
try:
    r = descargas._descargar_icloud([{"uuid": u} for u in uuids], print)
    print("FIN", sorted(r))
except KeyboardInterrupt:
    print("INTERRUMPIDO")
"""


def _lanzar(tmp_path, falsos, timeout, *uuids):
    env = dict(os.environ, PYTHONPATH=os.pathsep.join([str(falsos), str(RAIZ)]), PYTHONUNBUFFERED="1")
    return subprocess.Popen([sys.executable, "-c", _GUION, str(tmp_path / "orig"), str(timeout), *uuids],
                            env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                            start_new_session=True)


def test_tras_un_cuelgue_la_app_termina_y_no_pierde_la_salida(tmp_path):
    falsos = _instalar_falsos(tmp_path / "falsos")
    t0 = time.monotonic()
    p = _lanzar(tmp_path, falsos, 1.5, "cuelga-1", "bien-2")
    out, err = p.communicate(timeout=20)  # antes: no terminaba nunca y no se veía nada tras el cuelgue
    assert p.returncode == 0, err
    assert time.monotonic() - t0 < 10
    assert "1/2 ✗ cuelga-1: iCloud no responde" in out
    assert "2/2 ✓ IMG_bien-2.jpeg" in out and "FIN ['bien-2']" in out
    assert not [x for x in _pids(falsos) if _vivo(x)]


def test_ctrl_c_cierra_el_proceso_hijo(tmp_path):
    falsos = _instalar_falsos(tmp_path / "falsos")
    p = _lanzar(tmp_path, falsos, 60, "cuelga-1", "bien-2")
    limite = time.monotonic() + 10
    while not _pids(falsos) and time.monotonic() < limite:  # espera a que el hijo esté exportando
        time.sleep(0.05)
    time.sleep(0.3)
    t0 = time.monotonic()
    os.killpg(p.pid, signal.SIGINT)  # como Ctrl+C en la Terminal: a todo el grupo
    out, err = p.communicate(timeout=10)
    assert time.monotonic() - t0 < 3
    assert "INTERRUMPIDO" in out, err
    assert _pids(falsos) and not [x for x in _pids(falsos) if _vivo(x)]
