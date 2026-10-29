"""Índice local: metadatos y vector de cada foto en un SQLite pequeño (datos/fototeca.sqlite).

Es incremental: si lo vuelves a lanzar solo procesa las fotos nuevas, y si lo cortas
(Ctrl+C) no se pierde lo ya hecho.
"""
from __future__ import annotations

import json
import sqlite3
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Iterable

import numpy as np

from . import imagenes, rutas
from .fuentes import Foto

ESQUEMA = """
CREATE TABLE IF NOT EXISTS fotos (
    uuid TEXT PRIMARY KEY,
    fuente TEXT,
    ts REAL,
    datos TEXT,
    generacion INTEGER
);
CREATE TABLE IF NOT EXISTS vectores (
    uuid TEXT,
    modelo TEXT,
    v BLOB,
    error TEXT,
    firma TEXT,
    PRIMARY KEY (uuid, modelo)
);
CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT);
CREATE INDEX IF NOT EXISTS fotos_ts ON fotos(ts);
"""


def conectar() -> sqlite3.Connection:
    rutas.preparar()
    con = sqlite3.connect(rutas.BD, timeout=30, check_same_thread=False)
    con.executescript(ESQUEMA)
    columnas = {r[1] for r in con.execute("PRAGMA table_info(vectores)")}
    if "firma" not in columnas:
        con.execute("ALTER TABLE vectores ADD COLUMN firma TEXT")
    con.execute("PRAGMA journal_mode=WAL")
    return con


def _meta(con, k, defecto=None):
    r = con.execute("SELECT v FROM meta WHERE k=?", (k,)).fetchone()
    return r[0] if r else defecto


def _set_meta(con, k, v):
    con.execute("INSERT OR REPLACE INTO meta(k, v) VALUES (?, ?)", (k, str(v)))


def registrar(fotos: Iterable[Foto], fuente: str, borrar_ausentes: bool, origen: str = "") -> dict:
    """Guarda/actualiza los metadatos de todas las fotos de la fuente. Si se cambia de fuente
    (otra carpeta, otra fototeca), las fotos de la anterior salen de la galería, pero sus
    vectores se conservan: volver a ella es instantáneo."""
    con = conectar()
    gen = int(_meta(con, "generacion", 0)) + 1
    origen_previo = _meta(con, "origen")
    n = 0
    sin_imagen = 0
    t0 = time.time()
    lote = []
    for f in fotos:
        if not f.ruta_analisis:
            sin_imagen += 1
        lote.append((f.uuid, f.fuente, f.ts, json.dumps(f.a_dict(), ensure_ascii=False), gen))
        n += 1
        if len(lote) >= 500:
            con.executemany("INSERT OR REPLACE INTO fotos VALUES (?,?,?,?,?)", lote)
            con.commit()
            lote.clear()
            print(f"\r  leídas {n} fotos…", end="", flush=True)
    if lote:
        con.executemany("INSERT OR REPLACE INTO fotos VALUES (?,?,?,?,?)", lote)
    borradas = 0
    if borrar_ausentes or (origen_previo and origen_previo != f"{fuente}:{origen}"):
        cur = con.execute("DELETE FROM fotos WHERE generacion<?", (gen,))
        borradas = cur.rowcount
    _set_meta(con, "generacion", gen)
    _set_meta(con, "fuente", fuente)
    _set_meta(con, "origen", f"{fuente}:{origen}")
    _set_meta(con, "ultima_lectura", time.time())
    con.commit()
    con.close()
    print(f"\r  leídas {n} fotos en {time.time() - t0:.0f} s" + " " * 20)
    return {"fotos": n, "sin_imagen_local": sin_imagen, "borradas": borradas}


def pendientes(modelo_clave: str) -> list[tuple[str, str, str]]:
    con = conectar()
    filas = con.execute(
        """SELECT f.uuid, json_extract(f.datos, '$.ruta_analisis'), json_extract(f.datos, '$.firma') FROM fotos f
           LEFT JOIN vectores v ON v.uuid = f.uuid AND v.modelo = ?
           WHERE (v.uuid IS NULL OR v.firma IS NOT json_extract(f.datos, '$.firma'))
             AND json_extract(f.datos, '$.ruta_analisis') IS NOT NULL
           ORDER BY f.ts DESC""",
        (modelo_clave,),
    ).fetchall()
    con.close()
    return filas


def vectorizar(modelo, lote: int = 32, hilos: int = 4) -> dict:
    """Calcula el vector de cada foto que aún no lo tenga."""
    trabajo = pendientes(modelo.clave)
    total = len(trabajo)
    if not total:
        print("  todas las fotos ya estaban analizadas")
        return {"nuevas": 0, "errores": 0}
    print(f"· Analizando {total} fotos (puedes cortar con Ctrl+C y seguir luego)…")
    con = conectar()
    lado = 448  # suficiente para el modelo (224-256 px) y rapidísimo de decodificar

    firmas = {u: fi for u, _, fi in trabajo}

    def cargar(item):
        uuid, ruta, _ = item
        try:
            im = imagenes.abrir(ruta, lado)
            return uuid, modelo.tensor(im), None
        except Exception as e:  # imagen corrupta, formato raro…
            return uuid, None, str(e)[:200]

    hechas = errores = 0
    t0 = time.time()
    try:
        with ThreadPoolExecutor(max_workers=hilos) as ex:
            for i in range(0, total, lote):
                trozo = list(ex.map(cargar, trabajo[i:i + lote]))
                buenos = [(u, t) for u, t, e in trozo if t is not None]
                malos = [(u, e) for u, t, e in trozo if t is None]
                filas = []
                if buenos:
                    vec = modelo.vectores_imagen([t for _, t in buenos]).astype(np.float16)
                    filas += [(u, modelo.clave, vec[j].tobytes(), None, firmas[u]) for j, (u, _) in enumerate(buenos)]
                filas += [(u, modelo.clave, None, e, firmas[u]) for u, e in malos]
                con.executemany("INSERT OR REPLACE INTO vectores (uuid, modelo, v, error, firma) VALUES (?,?,?,?,?)", filas)
                con.commit()
                hechas += len(buenos)
                errores += len(malos)
                dt = time.time() - t0
                ritmo = (hechas + errores) / dt if dt > 0 else 0
                quedan = (total - hechas - errores) / ritmo if ritmo else 0
                sys.stdout.write(
                    f"\r  {hechas + errores}/{total} fotos · {ritmo:.1f} fotos/s · faltan ~{quedan / 60:.0f} min   "
                )
                sys.stdout.flush()
    except KeyboardInterrupt:
        print("\n  Interrumpido: lo analizado queda guardado.")
    finally:
        con.close()
    print()
    return {"nuevas": hechas, "errores": errores}


class Indice:
    """Todo el índice en memoria: matriz de vectores + metadatos."""

    def __init__(self, modelo_clave: str):
        con = conectar()
        filas = con.execute(
            """SELECT f.uuid, f.datos, v.v FROM fotos f
               JOIN vectores v ON v.uuid = f.uuid AND v.modelo = ?
               WHERE v.v IS NOT NULL ORDER BY f.ts""",
            (modelo_clave,),
        ).fetchall()
        con.close()
        self.modelo_clave = modelo_clave
        self.uuids: list[str] = [f[0] for f in filas]
        self.fotos: list[dict] = [json.loads(f[1]) for f in filas]
        if filas:
            m = np.stack([np.frombuffer(f[2], dtype=np.float16) for f in filas]).astype(np.float32)
            m /= np.linalg.norm(m, axis=1, keepdims=True) + 1e-8
        else:
            m = np.zeros((0, 1), dtype=np.float32)
        self.E = m
        self.pos = {u: i for i, u in enumerate(self.uuids)}

    def __len__(self):
        return len(self.uuids)

    def foto(self, uuid: str) -> dict | None:
        i = self.pos.get(uuid)
        return self.fotos[i] if i is not None else None


def foto_cualquiera(uuid: str) -> dict | None:
    """Metadatos de una foto aunque no tenga vector (p. ej. sin miniatura local)."""
    con = conectar()
    r = con.execute("SELECT datos FROM fotos WHERE uuid=?", (uuid,)).fetchone()
    con.close()
    return json.loads(r[0]) if r else None


def modelo_usado() -> str | None:
    if not rutas.BD.exists():
        return None
    con = conectar()
    m = _meta(con, "modelo")
    con.close()
    return m


def guardar_modelo_usado(preset: str) -> None:
    con = conectar()
    _set_meta(con, "modelo", preset)
    con.commit()
    con.close()


def ultima_lectura() -> float | None:
    if not rutas.BD.exists():
        return None
    con = conectar()
    v = _meta(con, "ultima_lectura")
    con.close()
    try:
        return float(v) if v else None
    except ValueError:
        return None


def sin_imagen() -> list[str]:
    con = conectar()
    filas = con.execute(
        "SELECT uuid FROM fotos WHERE fuente='fotos' AND json_extract(datos,'$.ruta_analisis') IS NULL ORDER BY ts DESC"
    ).fetchall()
    con.close()
    return [f[0] for f in filas]


def actualizar_foto(uuid: str, **cambios) -> None:
    con = conectar()
    r = con.execute("SELECT datos FROM fotos WHERE uuid=?", (uuid,)).fetchone()
    if r:
        d = json.loads(r[0])
        d.update(cambios)
        con.execute("UPDATE fotos SET datos=? WHERE uuid=?", (json.dumps(d, ensure_ascii=False), uuid))
        con.commit()
    con.close()


def estadisticas() -> dict:
    con = conectar()
    total = con.execute("SELECT COUNT(*) FROM fotos").fetchone()[0]
    sin = con.execute("SELECT COUNT(*) FROM fotos WHERE json_extract(datos,'$.ruta_analisis') IS NULL").fetchone()[0]
    # solo las fotos de la fuente actual: los vectores de otra carpeta o fototeca se guardan
    # (volver a ella es instantáneo) pero no cuentan
    por_modelo = dict(con.execute(
        "SELECT v.modelo, COUNT(v.v) FROM vectores v JOIN fotos f ON f.uuid = v.uuid GROUP BY v.modelo").fetchall())
    errores = con.execute(
        "SELECT COUNT(*) FROM vectores v JOIN fotos f ON f.uuid = v.uuid WHERE v.v IS NULL").fetchone()[0]
    fuente = _meta(con, "fuente")
    con.close()
    return {"fotos": total, "sin_imagen_local": sin, "analizadas": por_modelo, "errores": errores, "fuente": fuente}
