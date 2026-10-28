"""Galería local en el navegador (http://127.0.0.1:8765). Solo escucha en tu Mac."""
from __future__ import annotations

import json
import mimetypes
import subprocess
import sys
import threading
import traceback
import webbrowser
from collections import OrderedDict
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

import numpy as np

from . import disco, generar, ia, imagenes, indice, rutas
from .modelo import PRESETS, Modelo, clave_modelo
from .paseos import Paseos, linea_paseo
from .puntuar import Puntuador
from .textos import cargar_textos


class Trabajo:
    """Tarea larga en segundo plano (generar láminas, revisar con IA) con su registro."""

    def __init__(self):
        self.estado = "parado"
        self.log: list[str] = []
        self.resultado = None
        self.lock = threading.Lock()

    def lanzar(self, fn):
        with self.lock:
            if self.estado == "trabajando":
                return False
            self.estado, self.log, self.resultado = "trabajando", [], None

        def correr():
            try:
                self.resultado = fn(self.aviso)
                self.estado = "listo"
            except Exception as e:
                self.aviso(f"ERROR: {e}")
                traceback.print_exc()
                self.estado = "error"

        threading.Thread(target=correr, daemon=True).start()
        return True

    def aviso(self, msg: str):
        print(msg)
        self.log.append(str(msg))

    def json(self):
        return {"estado": self.estado, "log": self.log[-60:], "resultado": self.resultado}


class App:
    def __init__(self, preset: str):
        self.preset = preset
        self.clave = clave_modelo(preset)
        print("· Cargando índice…")
        self.ix = indice.Indice(self.clave)
        if not len(self.ix):
            raise SystemExit("No hay fotos analizadas con este modelo. Ejecuta antes: ./arte analizar")
        self._modelo: Modelo | None = None
        self._modelo_lock = threading.Lock()
        self.tx = cargar_textos(self.clave, self.modelo)
        print("· Puntuando categorías…")
        self.pt = Puntuador(self.ix, self.tx)
        self.pa = Paseos(self.ix, self.tx, self.pt)
        self.cache_cand = {c: self.pt.candidatas(c, 240) for c in self.pt.cats}
        self.mini_cache: OrderedDict = OrderedDict()
        self.trabajo_generar = Trabajo()
        self.trabajo_ia = Trabajo()
        self.ia_notas: dict = ia.leer_notas()
        print(f"  {len(self.ix)} fotos listas.")

    def modelo(self) -> Modelo:
        with self._modelo_lock:
            if self._modelo is None:
                self._modelo = Modelo(self.preset)
            return self._modelo

    def precargar_modelo(self):
        threading.Thread(target=self.modelo, daemon=True).start()

    # -- imágenes ---------------------------------------------------------
    def miniatura(self, uuid: str, lado: int) -> bytes | None:
        clave = (uuid, lado)
        if clave in self.mini_cache:
            self.mini_cache.move_to_end(clave)
            return self.mini_cache[clave]
        f = self.ix.foto(uuid) or indice.foto_cualquiera(uuid)
        if not f:
            return None
        ruta = f.get("ruta_analisis") or f.get("ruta_original")
        if lado > 900 and f.get("ruta_original"):
            ruta = f["ruta_original"]
        if not ruta:
            return None
        try:
            datos = imagenes.miniatura_jpeg(ruta, lado)
        except Exception:
            return None
        self.mini_cache[clave] = datos
        if len(self.mini_cache) > 700:
            self.mini_cache.popitem(last=False)
        return datos

    # -- API ---------------------------------------------------------------
    def estado(self) -> dict:
        cfg = self.tx.cfg
        fuertes = self.pt.resumen()
        return {
            "fotos": len(self.ix),
            "estadisticas": indice.estadisticas(),
            "modelo": {"preset": self.preset, "nombre": PRESETS[self.preset].arquitectura},
            "categorias": [
                {"id": c["id"], "nombre": c["nombre"], "definicion": c.get("definicion", ""),
                 "descripcion": c.get("descripcion_corta", ""), "consejos": c.get("consejos", []),
                 "busquedas": c.get("prompts", [])[:40], "fuertes": fuertes.get(c["id"], 0)}
                for c in cfg["categorias"]
            ],
            "plantillas": cfg.get("paseo", {}).get("plantillas_frase", []),
            "disco": disco.resumen(),
            "ia": ia.disponible(),
            "ia_notas": len(self.ia_notas),
        }

    def candidatas(self, cat: str, desde: int, n: int) -> list[dict]:
        lista = self.cache_cand.get(cat, [])
        notas = self.ia_notas.get(cat, {})
        if notas:
            lista = sorted(lista, key=lambda d: -(d["puntos"] + ia.ajuste(notas.get(d["uuid"]))))
        out = []
        for d in lista[desde:desde + n]:
            d = dict(d)
            nota = notas.get(d["uuid"])
            if nota:
                d["ia"] = nota
            out.append(d)
        return out

    def buscar_texto(self, q: str, n: int) -> list[dict]:
        # ¿es una de las frases de las categorías? entonces su vector ya está calculado
        for c in self.tx.cfg["categorias"]:
            if q in c["prompts"]:
                v = self.tx[f"cat:{c['id']}"][c["prompts"].index(q)]
                return self.pt.buscar_vector(v, n)
        v = self.modelo().vectores_texto([q])[0]
        return self.pt.buscar_vector(v, n)

    def similares(self, uuid: str, n: int) -> list[dict]:
        i = self.ix.pos.get(uuid)
        if i is None:
            return []
        return self.pt.buscar_vector(self.ix.E[i], n, excluir_uuid=uuid)

    def paseo(self, pid: str, k: int) -> dict | None:
        r = self.pa.sugerir(pid, k)
        if not r:
            return None
        todas = {f["uuid"]: f for f in r["todas"]}
        self.pa.completar_altitudes([f["uuid"] for f in r["todas"]])
        sug = [todas[u] for u in r["sugeridas"] if u in todas]
        r["linea"] = linea_paseo(sug, r["paseo"]["inicio"])
        palabras = [f["suceso"]["palabra"] for f in sug if f.get("suceso")]
        r["titulos"] = list(dict.fromkeys(palabras))[:8]
        return r


def _json(h: BaseHTTPRequestHandler, datos, codigo=200):
    cuerpo = json.dumps(datos, ensure_ascii=False, default=str).encode()
    h.send_response(codigo)
    h.send_header("Content-Type", "application/json; charset=utf-8")
    h.send_header("Content-Length", str(len(cuerpo)))
    h.send_header("Cache-Control", "no-store")
    h.end_headers()
    h.wfile.write(cuerpo)


def _bytes(h, datos: bytes, tipo: str, cache=True):
    h.send_response(200)
    h.send_header("Content-Type", tipo)
    h.send_header("Content-Length", str(len(datos)))
    h.send_header("Cache-Control", "max-age=3600" if cache else "no-store")
    h.end_headers()
    h.wfile.write(datos)


def _fichero(h, ruta: Path, raiz: Path):
    try:
        ruta = ruta.resolve()
        ruta.relative_to(raiz.resolve())
    except Exception:
        return h.send_error(403)
    if not ruta.is_file():
        return h.send_error(404)
    tipo = mimetypes.guess_type(ruta.name)[0] or "application/octet-stream"
    _bytes(h, ruta.read_bytes(), tipo, cache=False)


def crear_handler(app: App):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            try:
                self._get()
            except BrokenPipeError:
                pass
            except Exception as e:
                traceback.print_exc()
                _json(self, {"error": str(e)}, 500)

        def do_POST(self):
            try:
                n = int(self.headers.get("Content-Length") or 0)
                cuerpo = json.loads(self.rfile.read(n) or b"{}") if n else {}
                self._post(cuerpo)
            except Exception as e:
                traceback.print_exc()
                _json(self, {"error": str(e)}, 500)

        def _get(self):
            u = urlparse(self.path)
            q = {k: v[0] for k, v in parse_qs(u.query).items()}
            p = u.path
            if p in ("/", "/index.html"):
                return _fichero(self, rutas.WEB / "index.html", rutas.WEB)
            if p.startswith("/web/"):
                return _fichero(self, rutas.WEB / unquote(p[5:]), rutas.WEB)
            if p.startswith("/salida/"):
                return _fichero(self, rutas.SALIDA / unquote(p[8:]), rutas.SALIDA)
            if p.startswith("/mini/"):
                datos = app.miniatura(unquote(p[6:]), int(q.get("s", 360)))
                return _bytes(self, datos, "image/jpeg") if datos else self.send_error(404)
            if p == "/api/estado":
                return _json(self, app.estado())
            if p == "/api/candidatas":
                return _json(self, app.candidatas(q["cat"], int(q.get("desde", 0)), int(q.get("n", 60))))
            if p == "/api/general":
                return _json(self, app.pt.ranking_general(int(q.get("n", 150))))
            if p == "/api/buscar":
                return _json(self, app.buscar_texto(q.get("q", "").strip(), int(q.get("n", 90))))
            if p == "/api/similares":
                return _json(self, app.similares(q["uuid"], int(q.get("n", 60))))
            if p == "/api/foto":
                f = app.ix.foto(q["uuid"]) or indice.foto_cualquiera(q["uuid"]) or {}
                f = {k: v for k, v in f.items() if k not in ("ruta_analisis", "ruta_original")}
                return _json(self, f)
            if p == "/api/paseos":
                return _json(self, [app.pa.publico(x) for x in app.pa.detectar()[:60]])
            if p == "/api/paseo":
                r = app.paseo(q["id"], int(q.get("k", 12)))
                return _json(self, r) if r else _json(self, {"error": "no existe"}, 404)
            if p == "/api/seleccion":
                return _json(self, generar.leer_seleccion())
            if p == "/api/generar":
                return _json(self, app.trabajo_generar.json())
            if p == "/api/ia":
                d = app.trabajo_ia.json()
                d["notas"] = {c: len(v) for c, v in app.ia_notas.items()}
                return _json(self, d)
            self.send_error(404)

        def _post(self, b: dict):
            p = urlparse(self.path).path
            if p == "/api/seleccion":
                generar.guardar_seleccion(b)
                return _json(self, {"ok": True})
            if p == "/api/paseo_rango":
                d0 = datetime.fromisoformat(b["desde"]).astimezone().timestamp()
                d1 = datetime.fromisoformat(b["hasta"]).astimezone().timestamp()
                r = app.pa.por_rango(d0, d1)
                return _json(self, app.pa.publico(r) if r else {"error": "No hay fotos en ese intervalo"})
            if p == "/api/generar":
                sel = b or generar.leer_seleccion()
                generar.guardar_seleccion(sel)
                ok = app.trabajo_generar.lanzar(lambda aviso: generar.generar(sel, aviso=aviso))
                return _json(self, {"ok": ok})
            if p == "/api/ia/revisar":
                cats = b.get("categorias") or app.pt.cats
                n = int(b.get("n", 30))

                def tarea(aviso):
                    for c in cats:
                        lista = app.cache_cand.get(c, [])[:n]
                        notas = ia.revisar_categoria(c, lista, app.tx.cfg, app.ix, aviso)
                        app.ia_notas.setdefault(c, {}).update(notas)
                        ia.guardar_notas(app.ia_notas)
                    return {"ok": True}

                ok = app.trabajo_ia.lanzar(tarea)
                return _json(self, {"ok": ok})
            if p == "/api/ia/frases":
                def tarea(aviso):
                    return ia.frases_paseo(b.get("fotos", []), app.ix, aviso)

                ok = app.trabajo_ia.lanzar(tarea)
                return _json(self, {"ok": ok})
            if p == "/api/abrir_salida":
                if sys.platform == "darwin":
                    subprocess.Popen(["open", str(rutas.SALIDA)])
                return _json(self, {"ok": True, "ruta": str(rutas.SALIDA)})
            self.send_error(404)

    return H


def servir(preset: str, puerto: int = 8765, abrir: bool = True):
    rutas.preparar()
    app = App(preset)
    app.precargar_modelo()
    for intento in range(10):
        try:
            srv = ThreadingHTTPServer(("127.0.0.1", puerto + intento), crear_handler(app))
            break
        except OSError:
            continue
    else:
        raise SystemExit("No encuentro un puerto libre")
    url = f"http://127.0.0.1:{srv.server_address[1]}/"
    print(f"\n  Galería abierta en {url}\n  (deja esta ventana abierta; Ctrl+C para cerrar)\n")
    if abrir:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nHasta luego.")
