"""Frases de cada categoría (categorias.json) convertidas en vectores, con caché."""
from __future__ import annotations

import hashlib
import json

import numpy as np

from . import rutas


def cargar_config() -> dict:
    return json.loads(rutas.CONFIG_CATEGORIAS.read_text(encoding="utf-8"))


def grupos_de_frases(cfg: dict) -> dict[str, list[str]]:
    """Todas las listas de frases que hay que vectorizar, con un nombre cada una."""
    g: dict[str, list[str]] = {}
    for c in cfg["categorias"]:
        g[f"cat:{c['id']}"] = c["prompts"]
        g[f"conf:{c['id']}"] = c.get("confusores", [])
    gl = cfg.get("global", {})
    g["arte"] = gl.get("prompts_arte", [])
    g["excluir"] = gl.get("prompts_excluir", [])
    pa = cfg.get("paseo", {})
    g["naturaleza"] = pa.get("prompts_naturaleza", [])
    g["urbano"] = pa.get("prompts_urbano", [])
    g["camino"] = pa.get("prompts_camino", [])
    g["sucesos"] = [s["prompt"] for s in pa.get("sucesos", [])]
    return {k: v for k, v in g.items() if v}


class Textos:
    """Vectores de todas las frases para un modelo concreto."""

    def __init__(self, modelo_clave: str, cfg: dict, grupos: dict[str, np.ndarray]):
        self.modelo_clave = modelo_clave
        self.cfg = cfg
        self.g = grupos

    def __getitem__(self, k: str) -> np.ndarray:
        return self.g[k]

    def get(self, k: str):
        return self.g.get(k)


def _huella(modelo_clave: str, grupos: dict[str, list[str]]) -> str:
    h = hashlib.sha1(modelo_clave.encode())
    h.update(json.dumps(grupos, sort_keys=True).encode())
    return h.hexdigest()[:16]


def cargar_textos(modelo_clave: str, obtener_modelo, cfg: dict | None = None) -> Textos:
    """`obtener_modelo` es una función que devuelve el Modelo (solo se carga si no hay caché)."""
    cfg = cfg or cargar_config()
    grupos = grupos_de_frases(cfg)
    rutas.preparar()
    fichero = rutas.TEXTOS_CACHE / f"{_huella(modelo_clave, grupos)}.npz"
    if fichero.exists():
        datos = np.load(fichero)
        return Textos(modelo_clave, cfg, {k.replace("__", ":"): datos[k] for k in datos.files})
    modelo = obtener_modelo()
    nombres = list(grupos)
    todas = [f for n in nombres for f in grupos[n]]
    vec = modelo.vectores_texto(todas)
    out, i = {}, 0
    for n in nombres:
        k = len(grupos[n])
        out[n] = vec[i:i + k].astype(np.float32)
        i += k
    np.savez(fichero, **{k.replace(":", "__"): v for k, v in out.items()})
    return Textos(modelo_clave, cfg, out)
