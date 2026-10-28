"""Detección de caminatas (fecha + GPS) y propuesta de secuencia al estilo Hamish Fulton."""
from __future__ import annotations

import math
from collections import Counter
from datetime import datetime

import numpy as np

from . import imagenes
from .puntuar import top_media, z_robusto


def km_entre(a, b) -> float:
    lat1, lon1 = map(math.radians, a)
    lat2, lon2 = map(math.radians, b)
    d = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 12742.0 * math.asin(min(1.0, math.sqrt(d)))


def _gps(f) -> tuple[float, float] | None:
    if f.get("lat") is None or f.get("lon") is None:
        return None
    return (f["lat"], f["lon"])


def _hora(f) -> str:
    try:
        return datetime.fromisoformat(f["fecha"]).strftime("%H:%M")
    except Exception:
        return ""


def _dia(f) -> str:
    try:
        return datetime.fromisoformat(f["fecha"]).strftime("%Y-%m-%d")
    except Exception:
        return ""


MESES = ["ENERO", "FEBRERO", "MARZO", "ABRIL", "MAYO", "JUNIO", "JULIO", "AGOSTO",
         "SEPTIEMBRE", "OCTUBRE", "NOVIEMBRE", "DICIEMBRE"]


def fecha_larga(iso: str | None) -> str:
    try:
        d = datetime.fromisoformat(iso)
        return f"{d.day} {MESES[d.month - 1]} {d.year}"
    except Exception:
        return ""


def num_es(x: float, dec: int = 1) -> str:
    s = f"{x:,.{dec}f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


class Paseos:
    def __init__(self, indice, textos, puntuador=None):
        self.ix = indice
        self.tx = textos
        self.pt = puntuador
        E = indice.E
        n = len(indice)
        if n:
            nat = top_media(E @ textos["naturaleza"].T, 3)
            urb = top_media(E @ textos["urbano"].T, 3)
            self.natural = nat - urb                       # > 0: más paisaje natural que ciudad
            C = textos.get("camino")
            self.camino = z_robusto(top_media(E @ C.T, 2)) if C is not None else np.zeros(n)
            S = textos.get("sucesos")
            self.suc_sim = E @ S.T if S is not None else np.zeros((n, 0))
        else:
            self.natural = np.zeros(0)
            self.camino = np.zeros(0)
            self.suc_sim = np.zeros((0, 0))
        self.sucesos = textos.cfg.get("paseo", {}).get("sucesos", [])
        self._paseos: list[dict] | None = None

    # ------------------------------------------------------------------
    def _es_util(self, i: int) -> bool:
        f = self.ix.fotos[i]
        if f.get("captura") or f.get("selfie"):
            return False
        if float(f.get("cara_max") or 0) > 0.06:
            return False
        return True

    def _sesiones(self, hueco_min: float, salto_km: float) -> list[list[int]]:
        fotos = self.ix.fotos
        orden = [int(i) for i in np.argsort([f.get("ts") or 0 for f in fotos]) if fotos[i].get("ts")]
        sesiones: list[list[int]] = []
        actual: list[int] = []
        ultimo_gps = None
        for k, i in enumerate(orden):
            f = fotos[i]
            if actual:
                prev = fotos[actual[-1]]
                hueco = (f["ts"] - prev["ts"]) / 60
                g = _gps(f)
                salto = km_entre(ultimo_gps, g) if (g and ultimo_gps) else 0
                if salto > salto_km and hueco <= hueco_min and k + 1 < len(orden):
                    # ¿foto suelta con otra ubicación (recibida por WhatsApp, captura…)? si la
                    # siguiente vuelve a estar cerca del recorrido, se ignora en vez de cortar
                    sig = fotos[orden[k + 1]]
                    g2 = _gps(sig)
                    if g2 and km_entre(ultimo_gps, g2) < 3 and (sig["ts"] - prev["ts"]) / 60 <= hueco_min:
                        continue
                if hueco > hueco_min or salto > salto_km:
                    sesiones.append(actual)
                    actual, ultimo_gps = [], None
            actual.append(i)
            ultimo_gps = _gps(f) or ultimo_gps
        if actual:
            sesiones.append(actual)
        return sesiones

    def _resumen(self, idx: list[int], pid: str) -> dict:
        fotos = self.ix.fotos
        utiles = [i for i in idx if self._es_util(i)]
        nat = [i for i in utiles if self.natural[i] > 0]
        pts = [_gps(fotos[i]) for i in idx if _gps(fotos[i])]
        km = sum(km_entre(a, b) for a, b in zip(pts, pts[1:]) if km_entre(a, b) < 5) if len(pts) > 1 else 0.0
        radio = max((km_entre(pts[0], p) for p in pts), default=0.0) if pts else 0.0
        horas = (fotos[idx[-1]]["ts"] - fotos[idx[0]]["ts"]) / 3600
        frac = len(nat) / max(1, len(utiles))
        lugares = Counter(fotos[i].get("lugar_corto") for i in idx if fotos[i].get("lugar_corto"))
        cam = float(np.mean(np.clip(self.camino[nat], -1, 3))) if nat else 0.0
        puntos = (len(nat) ** 0.5) * frac * (1 + min(km, 15) / 5 + min(radio, 5) / 5) * (1 + 0.2 * cam)
        if len(nat) < 6:
            puntos *= 0.3
        portada_src = nat if len(nat) >= 4 else utiles or idx
        paso = max(1, len(portada_src) // 6)
        return {
            "id": pid,
            "inicio": fotos[idx[0]].get("fecha"),
            "fin": fotos[idx[-1]].get("fecha"),
            "dia": _dia(fotos[idx[0]]),
            "fotos": len(idx),
            "naturales": len(nat),
            "km": round(km, 1),
            "radio_km": round(radio, 1),
            "horas": round(horas, 1),
            "lugar": lugares.most_common(1)[0][0] if lugares else "",
            "con_gps": len(pts),
            "puntos": round(float(puntos), 2),
            "portada": [self.ix.uuids[i] for i in portada_src[::paso][:6]],
            "_idx": idx,
        }

    def detectar(self, hueco_min: float = 100, salto_km: float = 20, min_fotos: int = 8) -> list[dict]:
        if self._paseos is not None:
            return self._paseos
        sesiones = [s for s in self._sesiones(hueco_min, salto_km) if len(s) >= min_fotos]
        paseos = [self._resumen(s, f"p{k}") for k, s in enumerate(sesiones)]
        paseos = [p for p in paseos if p["naturales"] >= 4]
        paseos.sort(key=lambda p: -p["puntos"])
        self._paseos = paseos
        return paseos

    def por_id(self, pid: str) -> dict | None:
        for p in self.detectar():
            if p["id"] == pid:
                return p
        return None

    def por_rango(self, desde_ts: float, hasta_ts: float) -> dict | None:
        idx = [i for i, f in enumerate(self.ix.fotos) if f.get("ts") and desde_ts <= f["ts"] <= hasta_ts]
        idx.sort(key=lambda i: self.ix.fotos[i]["ts"])
        if not idx:
            return None
        p = self._resumen(idx, f"r{int(desde_ts)}-{int(hasta_ts)}")
        self.detectar()
        self._paseos = [q for q in self._paseos if q["id"] != p["id"]] + [p]
        return p

    # ------------------------------------------------------------------
    def km_acumulados(self, idx: list[int]) -> list[float | None]:
        """Km recorridos hasta cada foto (interpolando en las que no tienen GPS)."""
        fotos = self.ix.fotos
        acum: list[float | None] = []
        total = 0.0
        ultimo = None
        for i in idx:
            g = _gps(fotos[i])
            if g:
                if ultimo:
                    d = km_entre(ultimo, g)
                    if d < 5:
                        total += d
                ultimo = g
                acum.append(total)
            else:
                acum.append(None)
        if all(a is None for a in acum):
            return acum
        ts = [fotos[i]["ts"] for i in idx]
        conocidos = [(t, a) for t, a in zip(ts, acum) if a is not None]
        out = []
        for t, a in zip(ts, acum):
            if a is not None:
                out.append(a)
            else:
                out.append(float(np.interp(t, [c[0] for c in conocidos], [c[1] for c in conocidos])))
        return out

    def _calidad(self, idx: list[int]) -> np.ndarray:
        suc = self.suc_sim[idx].max(axis=1) if self.suc_sim.shape[1] else np.zeros(len(idx))
        est = np.array([float(self.ix.fotos[i].get("estetica") or 0) for i in idx])
        return (
            z_robusto(self.natural[idx]) if len(idx) > 2 else self.natural[idx] * 0
        ) + 0.5 * self.camino[idx] + 0.5 * (z_robusto(suc) if len(idx) > 2 else 0) + 0.4 * est

    def sugerir(self, pid: str, k: int = 12) -> dict | None:
        p = self.por_id(pid)
        if not p:
            return None
        idx = [i for i in p["_idx"] if self._es_util(i)]
        E = self.ix.E
        # quitar ráfagas: fotos casi idénticas hechas con segundos de diferencia
        limpio: list[int] = []
        for i in idx:
            if limpio:
                j = limpio[-1]
                seg = abs(self.ix.fotos[i]["ts"] - self.ix.fotos[j]["ts"])
                if seg < 90 and float(E[j] @ E[i]) > 0.94:
                    q = self._calidad([j, i])
                    if q[1] > q[0]:
                        limpio[-1] = i
                    continue
            limpio.append(i)
        preferidas = [i for i in limpio if self.natural[i] > -0.005]
        if len(preferidas) < min(k, len(limpio)):
            preferidas = limpio
        if len(preferidas) <= k:
            elegidas = preferidas
        else:
            q = self._calidad(preferidas)
            ts = np.array([self.ix.fotos[i]["ts"] for i in preferidas])
            cortes = np.linspace(ts.min(), ts.max() + 1, k + 1)
            palabra = self._palabra_principal(preferidas)
            usadas: Counter = Counter()
            elegidas = []
            for b in range(k):
                en = [j for j in range(len(preferidas)) if cortes[b] <= ts[j] < cortes[b + 1]]
                if en:
                    j = max(en, key=lambda j: q[j] - (1.5 if usadas[palabra[j]] >= 2 else 0))
                    usadas[palabra[j]] += 1
                    elegidas.append(preferidas[j])
            # si algún tramo estaba vacío, completar con las mejores restantes
            resto = sorted((j for j in range(len(preferidas)) if preferidas[j] not in elegidas), key=lambda j: -q[j])
            for j in resto:
                if len(elegidas) >= k:
                    break
                elegidas.append(preferidas[j])
            # el origen y el final de la secuencia son los del recorrido real
            elegidas.sort(key=lambda i: self.ix.fotos[i]["ts"])
            if preferidas[0] not in elegidas:
                elegidas[0] = preferidas[0]
            if preferidas[-1] not in elegidas:
                elegidas[-1] = preferidas[-1]
            elegidas = sorted(set(elegidas), key=lambda i: self.ix.fotos[i]["ts"])
        return {"paseo": self.publico(p), "todas": self.fichas(p["_idx"]), "sugeridas": [self.ix.uuids[i] for i in elegidas]}

    def _palabra_principal(self, idx: list[int]) -> list[str]:
        if not self.sucesos or not self.suc_sim.shape[1]:
            return [""] * len(idx)
        return [self.sucesos[int(np.argmax(self.suc_sim[i]))]["palabra"] for i in idx]

    def fichas(self, idx: list[int]) -> list[dict]:
        kms = self.km_acumulados(idx)
        usados: Counter = Counter()
        out = []
        for i, km in zip(idx, kms):
            f = self.ix.fotos[i]
            suc = self._suceso(i, usados)
            alt = f.get("alt")
            out.append({
                "uuid": f["uuid"],
                "fecha": f.get("fecha"),
                "hora": _hora(f),
                "km": None if km is None else round(km, 2),
                "alt": alt,
                "lat": f.get("lat"),
                "lon": f.get("lon"),
                "lugar": f.get("lugar_corto") or "",
                "natural": round(float(self.natural[i]) * 100, 1),
                "util": self._es_util(i),
                "suceso": suc,
                "frase": suc["frase"] if suc else "",
            })
        return out

    def _suceso(self, i: int, usados: Counter) -> dict | None:
        """El suceso más parecido a la foto, penalizando los ya usados para que la secuencia
        no repita la misma frase en cada foto."""
        if not self.sucesos or not self.suc_sim.shape[1]:
            return None
        s = self.suc_sim[i]
        orden = np.argsort(-s)[:12]
        mejor = max(orden, key=lambda j: s[j] - 0.008 * usados[self.sucesos[int(j)]["palabra"]])
        d = self.sucesos[int(mejor)]
        usados[d["palabra"]] += 1
        return {"frase": d["frase"], "palabra": d["palabra"], "confianza": round(float(s[mejor]) * 100, 1)}

    def completar_altitudes(self, uuids: list[str]) -> None:
        """Lee la altitud del EXIF de los originales locales (Fotos no la guarda en su base)."""
        for u in uuids:
            i = self.ix.pos.get(u)
            if i is None:
                continue
            f = self.ix.fotos[i]
            if f.get("alt") is not None:
                continue
            for ruta in (f.get("ruta_original"), f.get("ruta_analisis")):
                if ruta:
                    alt = imagenes.exif_basico(ruta).get("alt")
                    if alt is not None:
                        f["alt"] = alt
                        break

    @staticmethod
    def publico(p: dict) -> dict:
        return {k: v for k, v in p.items() if not k.startswith("_")}


def frase_borrador(hora: str, km: float | None, alt: float | None, suceso: str) -> str:
    partes = [hora] if hora else []
    if km is not None:
        partes.append(f"km {num_es(km)}")
    if alt is not None:
        partes.append(f"{num_es(alt, 0)} m")
    cab = " · ".join(partes)
    return f"{cab} — {suceso}" if cab and suceso else (suceso or cab)


def linea_paseo(fichas: list[dict], inicio: str | None) -> str:
    """Línea descriptiva al estilo Fulton: «CAMINATA DE 4 HORAS DESDE X HASTA Y · 12,3 KM · 3 MAYO 2025»."""
    if not fichas:
        return ""
    l0 = fichas[0].get("lugar") or ""
    l1 = fichas[-1].get("lugar") or ""
    try:
        h = (datetime.fromisoformat(fichas[-1]["fecha"]) - datetime.fromisoformat(fichas[0]["fecha"])).total_seconds() / 3600
    except Exception:
        h = 0
    dur = f"{round(h)} HORAS" if h >= 1.5 else ("UNA HORA" if h >= 0.75 else "UN PASEO")
    kms = [f["km"] for f in fichas if f.get("km") is not None]
    km = f" · {num_es(kms[-1] - kms[0])} KM" if len(kms) > 1 and kms[-1] - kms[0] > 0.2 else ""
    if l0 and l1 and l0 != l1:
        donde = f" DESDE {l0} HASTA {l1}"
    elif l0:
        donde = f" CIRCULAR EN {l0}"
    else:
        donde = ""
    pre = "UNA CAMINATA DE " if dur != "UN PASEO" else ""
    return f"{pre}{dur}{donde}{km} · {fecha_larga(inicio)}".upper().strip(" ·")
