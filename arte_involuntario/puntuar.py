"""Puntuación de cada foto para cada categoría de Clément.

Para cada categoría c y foto i:
  pos   = parecido con las frases de c (media de las 3 frases más parecidas + parecido
          con el «centro» de todas ellas)
  conf  = parecido con los «confusores» de c (cosas que se le parecen pero no son)
  z     = pos normalizado sobre TODA tu fototeca (así las 8 categorías son comparables)
  final = z + contraste(pos − conf) + arte_general + etiquetas de Fotos − exclusiones
Las exclusiones (selfies, comida, capturas, documentos…) penalizan; no hace falta acertar
al 100 %: la última palabra la tienes tú en la galería.
"""
from __future__ import annotations

import unicodedata

import numpy as np

ESCALA = 100.0  # escala de los logits de CLIP: 0.01 de coseno ≈ 1 «nat»

# Pesos de cada ingrediente (ajustados con los ejemplos del libro mezclados con 1.000 fotos
# cotidianas; ver tests/). z = parecido normalizado; especificidad = cuánto destaca esta
# categoría sobre la siguiente mejor; contraste = frases propias frente a confusores.
PESOS = {"z": 1.0, "especificidad": 0.5, "contraste": 0.3, "arte": 0.05,
         "etiquetas": 0.9, "estetica": 0.25, "exceso": 1.2}


def top_media(S: np.ndarray, k: int) -> np.ndarray:
    if S.shape[1] == 0:
        return np.zeros(S.shape[0], dtype=np.float32)
    k = max(1, min(k, S.shape[1]))
    return np.partition(S, -k, axis=1)[:, -k:].mean(axis=1)


def centro(P: np.ndarray) -> np.ndarray:
    c = P.mean(axis=0)
    return c / (np.linalg.norm(c) + 1e-8)


def z_robusto(x: np.ndarray) -> np.ndarray:
    if len(x) < 3:
        return np.zeros_like(x)
    med = np.median(x)
    mad = np.median(np.abs(x - med)) * 1.4826
    if mad < 1e-6:
        mad = float(np.std(x)) or 1.0
    return (x - med) / mad


def normalizar(t: str) -> str:
    t = unicodedata.normalize("NFKD", t.lower().strip())
    return "".join(c for c in t if not unicodedata.combining(c))


def _conjunto(etqs) -> set[str]:
    return {normalizar(e) for e in etqs if e}


def coincide(etiquetas_foto: set[str], buscadas: set[str]) -> list[str]:
    hits = []
    for e in etiquetas_foto:
        if e in buscadas:
            hits.append(e)
            continue
        palabras = set(e.replace("-", " ").split())
        if palabras & buscadas:
            hits.append(e)
    return hits


def parecido_categoria(E: np.ndarray, P: np.ndarray) -> np.ndarray:
    S = E @ P.T
    return 0.5 * top_media(S, 3) + 0.5 * (E @ centro(P))


class Puntuador:
    def __init__(self, indice, textos):
        self.ix = indice
        self.tx = textos
        self.cfg = textos.cfg
        self.cats = [c["id"] for c in self.cfg["categorias"]]
        self._calcular()

    def _calcular(self):
        E = self.ix.E
        n = len(self.ix)
        cfg = self.cfg
        tx = self.tx
        self.pos = {}
        self.conf = {}
        for c in self.cats:
            self.pos[c] = parecido_categoria(E, tx[f"cat:{c}"]) if n else np.zeros(0)
            C = tx.get(f"conf:{c}")
            self.conf[c] = top_media(E @ C.T, 3) if (C is not None and n) else np.zeros(n)
        A = tx.get("arte")
        X = tx.get("excluir")
        self.arte = top_media(E @ A.T, 3) if A is not None and n else np.zeros(n)
        self.excl = top_media(E @ X.T, 2) if X is not None and n else np.zeros(n)

        # --- metadatos -------------------------------------------------------
        fotos = self.ix.fotos
        excl_etq = _conjunto(cfg.get("global", {}).get("etiquetas_excluir", []))
        self.etq = [_conjunto(f.get("etiquetas") or []) for f in fotos]
        self.penal_meta = np.zeros(n, dtype=np.float32)
        self.penal_cara = np.zeros(n, dtype=np.float32)
        self.estetica = np.zeros(n, dtype=np.float32)
        for i, f in enumerate(fotos):
            p = 0.0
            if f.get("captura"):
                p += 6.0
            if f.get("selfie"):
                p += 2.0
            if excl_etq and coincide(self.etq[i], excl_etq):
                p += 1.0
            self.penal_meta[i] = p
            cm = float(f.get("cara_max") or 0)
            # caras grandes = retrato: no es arte involuntario (salvo, un poco, en Apariciones)
            self.penal_cara[i] = min(2.0, max(0.0, (cm - 0.04) * 25)) if cm else 0.0
            est = f.get("estetica")
            self.estetica[i] = float(est) if est is not None else 0.0

        # --- puntuación final por categoría ----------------------------------------
        mejor_pos = np.max(np.stack([self.pos[c] for c in self.cats]), axis=0) if n else np.zeros(0)
        self.exceso = np.clip((self.excl - np.maximum(self.arte, mejor_pos)) * ESCALA / 3, 0, 2.5)
        self.z_arte = np.clip(z_robusto(self.arte), -2, 3) if n else self.arte
        self.z = {c: (z_robusto(self.pos[c]) if n else self.pos[c]) for c in self.cats}
        self.bonus = {}
        self.etq_hits = {}
        for c, cat in zip(self.cats, cfg["categorias"]):
            buscadas = _conjunto(cat.get("etiquetas_apple", []))
            bonus = np.zeros(n, dtype=np.float32)
            hits = {}
            if buscadas:
                for i in range(n):
                    h = coincide(self.etq[i], buscadas)
                    if h:
                        bonus[i] = min(1.0, 0.5 * len(h))
                        hits[i] = h
            self.bonus[c] = bonus
            self.etq_hits[c] = hits
        self.combinar(PESOS)

    def combinar(self, w: dict) -> None:
        n = len(self.ix)
        Z = np.stack([self.z[c] for c in self.cats]) if n else np.zeros((len(self.cats), 0))
        self.final = {}
        for k, c in enumerate(self.cats):
            otras = np.delete(Z, k, axis=0).max(axis=0) if n else Z[k]
            especificidad = np.clip(Z[k] - otras, -3, 2)
            contraste = np.clip((self.pos[c] - self.conf[c]) * ESCALA / 3, -1.5, 1.0)
            cara = self.penal_cara * (0.3 if c == "apariciones" else 1.0)
            self.final[c] = (
                w["z"] * Z[k]
                + w["especificidad"] * especificidad
                + w["contraste"] * contraste
                + w["arte"] * self.z_arte
                + w["etiquetas"] * self.bonus[c]
                + w["estetica"] * self.estetica
                - w["exceso"] * self.exceso
                - self.penal_meta
                - cara
            )
        if n:
            self.mejor = np.stack([self.final[c] for c in self.cats]).argmax(axis=0)
        else:
            self.mejor = np.zeros(0, dtype=int)

    # ------------------------------------------------------------------
    def candidatas(self, cat: str, n: int = 120, umbral_dup: float = 0.93) -> list[dict]:
        if not len(self.ix):
            return []
        orden = np.argsort(-self.final[cat])
        E = self.ix.E
        elegidas: list[int] = []
        for i in orden:
            if len(elegidas) >= n:
                break
            if elegidas:
                sim = E[elegidas] @ E[i]
                if float(sim.max()) > umbral_dup:
                    continue  # casi idéntica a otra ya elegida (ráfagas, repeticiones)
            elegidas.append(int(i))
        return [self.ficha(i, cat) for i in elegidas]

    def ficha(self, i: int, cat: str | None = None) -> dict:
        f = self.ix.fotos[i]
        d = {
            "uuid": f["uuid"],
            "fecha": f.get("fecha"),
            "lugar": f.get("lugar_corto") or f.get("lugar") or "",
            "en_icloud": f.get("en_icloud", False),
            "ancho": f.get("ancho", 0),
            "alto": f.get("alto", 0),
            "sugerida": self.cats[int(self.mejor[i])] if len(self.mejor) else None,
        }
        if cat:
            d["puntos"] = round(float(self.final[cat][i]), 2)
            d["etiquetas"] = self.etq_hits.get(cat, {}).get(i, [])
        orden = np.argsort([-self.final[c][i] for c in self.cats])
        d["tambien"] = [self.cats[j] for j in orden[:3] if self.final[self.cats[j]][i] > 1.0 and self.cats[j] != cat][:2]
        return d

    def ranking_general(self, n: int = 150) -> list[dict]:
        """Las fotos más «Clément» en cualquier categoría."""
        if not len(self.ix):
            return []
        Z = np.stack([self.final[c] for c in self.cats])
        mejor = Z.max(axis=0)
        orden = np.argsort(-mejor)
        E = self.ix.E
        out: list[int] = []
        for i in orden:
            if len(out) >= n:
                break
            if out and float((E[out] @ E[i]).max()) > 0.93:
                continue
            out.append(int(i))
        return [self.ficha(i, self.cats[int(self.mejor[i])]) for i in out]

    def buscar_vector(self, v: np.ndarray, n: int = 120, excluir_uuid: str | None = None) -> list[dict]:
        if not len(self.ix):
            return []
        s = self.ix.E @ v
        s = s - 0.02 * self.penal_meta  # que las capturas no salgan arriba
        orden = np.argsort(-s)
        out = []
        for i in orden[: n + 1]:
            if excluir_uuid and self.ix.uuids[i] == excluir_uuid:
                continue
            d = self.ficha(int(i))
            d["puntos"] = round(float(s[i]) * 100, 1)
            out.append(d)
        return out[:n]

    def resumen(self) -> dict:
        """Cuántas candidatas «fuertes» hay por categoría (para avisar si falta alguna)."""
        return {c: int((self.final[c] > 2.0).sum()) for c in self.cats}
