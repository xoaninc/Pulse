"""Modelo de visión-lenguaje (CLIP / SigLIP vía open_clip), en local.

Convierte cada foto y cada frase en un vector; si una foto «se parece» a una frase
(p. ej. «a plastic bag caught in the branches of a tree») sus vectores apuntan hacia
el mismo lado. Así se buscan las categorías de Clément sin entrenar nada.
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass

import numpy as np

from . import rutas


@dataclass(frozen=True)
class Preset:
    nombre: str
    arquitectura: str
    pretrained: str
    descarga_mb: int
    descripcion: str


PRESETS: dict[str, Preset] = {
    "rapido": Preset("rapido", "MobileCLIP2-S2", "dfndr2b", 420,
                     "MobileCLIP2-S2 de Apple: rápido y ligero, buena precisión."),
    "preciso": Preset("preciso", "ViT-L-14", "dfn2b", 1750,
                      "ViT-L/14 DFN-2B: más fino con conceptos raros, ~4x más lento."),
}
PRESET_POR_DEFECTO = "rapido"


def clave_modelo(preset: str) -> str:
    p = PRESETS[preset]
    return f"{p.arquitectura}:{p.pretrained}"


def elegir_dispositivo() -> str:
    import torch

    forzado = os.environ.get("ARTE_DISPOSITIVO")
    if forzado:
        return forzado
    if torch.backends.mps.is_available():
        return "mps"
    if torch.cuda.is_available():
        return "cuda"
    return "cpu"


class Modelo:
    def __init__(self, preset: str = PRESET_POR_DEFECTO, dispositivo: str | None = None, verbose: bool = True):
        rutas.preparar()
        import torch
        import open_clip

        if preset not in PRESETS:
            raise ValueError(f"Modelo desconocido «{preset}». Opciones: {', '.join(PRESETS)}")
        self.preset = PRESETS[preset]
        self.clave = clave_modelo(preset)
        self.dispositivo = dispositivo or elegir_dispositivo()
        t0 = time.time()
        if verbose:
            print(f"· Cargando modelo {self.preset.arquitectura} ({self.preset.pretrained}) en {self.dispositivo}…")
        try:
            modelo, _, preprocesado = open_clip.create_model_and_transforms(
                self.preset.arquitectura, pretrained=self.preset.pretrained, device=self.dispositivo
            )
        except Exception:
            if self.dispositivo != "cpu":
                if verbose:
                    print("  (no ha funcionado en la GPU; uso la CPU)")
                self.dispositivo = "cpu"
                modelo, _, preprocesado = open_clip.create_model_and_transforms(
                    self.preset.arquitectura, pretrained=self.preset.pretrained, device="cpu"
                )
            else:
                raise
        modelo.eval()
        # MobileCLIP trae capas que se pueden «fusionar» para inferencia (más rápido).
        try:
            from open_clip import utils as ocu

            if hasattr(ocu, "reparameterize_model"):
                modelo = ocu.reparameterize_model(modelo)
        except Exception:
            pass
        self.modelo = modelo
        self.preprocesado = preprocesado
        self.tokenizador = open_clip.get_tokenizer(self.preset.arquitectura)
        self.torch = torch
        if verbose:
            print(f"  listo en {time.time() - t0:.0f} s")

    # -- imágenes ---------------------------------------------------------
    def tensor(self, im):
        return self.preprocesado(im)

    def vectores_imagen(self, tensores: list) -> np.ndarray:
        torch = self.torch
        with torch.inference_mode():
            lote = torch.stack(tensores).to(self.dispositivo)
            v = self.modelo.encode_image(lote)
            v = v / v.norm(dim=-1, keepdim=True)
        return v.float().cpu().numpy()

    # -- textos -----------------------------------------------------------
    def vectores_texto(self, textos: list[str], lote: int = 128) -> np.ndarray:
        torch = self.torch
        out = []
        with torch.inference_mode():
            for i in range(0, len(textos), lote):
                tok = self.tokenizador(textos[i:i + lote]).to(self.dispositivo)
                v = self.modelo.encode_text(tok)
                v = v / v.norm(dim=-1, keepdim=True)
                out.append(v.float().cpu().numpy())
        return np.concatenate(out) if out else np.zeros((0, 1), dtype=np.float32)
