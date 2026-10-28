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
    "preciso": Preset("preciso", "MobileCLIP2-S3", "dfndr2b", 1000,
                      "MobileCLIP2-S3 de Apple: algo más fino, ~1,5x más lento, descarga 1 GB."),
}
PRESET_POR_DEFECTO = "rapido"


def resolver_preset(preset: str) -> Preset:
    """«rapido», «preciso» o cualquier modelo de open_clip como «arquitectura:pesos»."""
    if preset in PRESETS:
        return PRESETS[preset]
    if ":" in preset:
        arq, pre = preset.split(":", 1)
        return Preset(preset, arq, pre, 1000, f"{arq} ({pre})")
    raise ValueError(f"Modelo desconocido «{preset}». Opciones: {', '.join(PRESETS)} o arquitectura:pesos")


def clave_modelo(preset: str) -> str:
    p = resolver_preset(preset)
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


def descargado(preset: str) -> bool:
    """¿Están ya los pesos de este modelo en datos/modelos?"""
    p = resolver_preset(preset)
    try:
        import open_clip

        cfg = open_clip.pretrained.get_pretrained_cfg(p.arquitectura, p.pretrained)
        repo = (cfg.get("hf_hub") or "").strip("/")
        if repo:
            carpeta = rutas.MODELOS / "hub" / ("models--" + repo.replace("/", "--"))
            return any(carpeta.rglob("*.safetensors")) or any(carpeta.rglob("*.bin"))
    except Exception:
        pass
    return False


class Modelo:
    def __init__(self, preset: str = PRESET_POR_DEFECTO, dispositivo: str | None = None, verbose: bool = True):
        rutas.preparar()
        import torch
        import open_clip

        from . import disco

        if not descargado(preset):
            mb = resolver_preset(preset).descarga_mb
            disco.comprobar(int(mb * 1.2 * 1024**2), f"descargar el modelo de visión ({mb} MB, solo la primera vez)",
                            rutas.MODELOS)

        self.preset = resolver_preset(preset)
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
        # MobileCLIP trae ramas que se «fusionan» para inferencia: mismo resultado, 1,5-1,8x más rápido.
        try:
            from timm.utils import reparameterize_model

            modelo = reparameterize_model(modelo)
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
