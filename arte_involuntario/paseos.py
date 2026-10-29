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


# ---------------------------------------------------------------------- limpieza del GPS
# Cada punto es (índice, ts, (lat, lon)).
VEL_MAX = 15.0   # km/h: más rápido que esto no es caminar ni ir en bici
VEL_PICO = 6.0   # km/h: un desvío de ida y vuelta más rápido que esto es un error del GPS
PASO_MIN = 0.06  # km: lo que se mueve menos que esto entre fotos es temblor del GPS


def _plausible(a, b) -> bool:
    """¿Da tiempo a ir de a a b caminando o en bici?"""
    d = km_entre(a[2], b[2])
    return d <= 0.3 or d / max(abs(b[1] - a[1]) / 3600, 1 / 60) <= VEL_MAX


def _sin_picos(pts: list) -> list:
    """Quita posiciones desviadas que se van y vuelven: primero de una en una y después de dos
    en dos (dos fotos seguidas con el mismo error). Un desvío real, como subir a una cumbre y
    bajar por el mismo sitio, se respeta si da tiempo a hacerlo andando."""
    for w in (1, 2):
        out, k = pts[:1], 1
        while k < len(pts):
            if k + w < len(pts):
                tramo = [out[-1]] + pts[k:k + w + 1]
                ida_vuelta = sum(km_entre(a[2], b[2]) for a, b in zip(tramo, tramo[1:]))
                horas = max((tramo[-1][1] - tramo[0][1]) / 3600, 1 / 60)
                if ida_vuelta > 3 * km_entre(tramo[0][2], tramo[-1][2]) + 0.4 and ida_vuelta / horas > VEL_PICO:
                    k += w
                    continue
            out.append(pts[k])
            k += 1
        pts = out
    return pts


def _sin_extremos_raros(pts: list) -> list:
    """La primera foto (o las dos primeras) a veces lleva la posición de antes de abrir la cámara,
    a kilómetros. Si no da tiempo a llegar desde ahí y lo que sigue sí encaja, se descarta.
    Lo mismo con las últimas."""
    for _ in range(2):
        for n in (1, 2):
            if len(pts) > n + 1 and not _plausible(pts[n - 1], pts[n]) and _plausible(pts[n], pts[n + 1]):
                pts = pts[n:]
                break
        pts = pts[::-1]
    return pts


def _desvio(a, g, b) -> float:
    """Km de g a la recta que une a y b (o a a, si a y b coinciden)."""
    c = math.cos(math.radians(a[0]))
    bx, by = (b[1] - a[1]) * c, b[0] - a[0]
    gx, gy = (g[1] - a[1]) * c, g[0] - a[0]
    largo = math.hypot(bx, by)
    return 111.2 * (abs(gx * by - gy * bx) / largo if largo > 1e-5 else math.hypot(gx, gy))


def _suavizar(pts: list) -> list:
    """Si el temblor del GPS es comparable a lo que se avanza de foto a foto (fotos muy seguidas),
    cada posición pasa a ser la mediana de 3 (lat y lon por separado). Con fotos espaciadas no se
    toca, para no recortar curvas ni cumbres."""
    if len(pts) < 5:
        return pts
    temblor = float(np.median([_desvio(pts[k - 1][2], pts[k][2], pts[k + 1][2]) for k in range(1, len(pts) - 1)]))
    paso = float(np.median([km_entre(a[2], b[2]) for a, b in zip(pts, pts[1:])]))
    if temblor <= 0.2 * paso:
        return pts
    med = [(pts[k][0], pts[k][1], (sorted(p[2][0] for p in pts[k - 1:k + 2])[1],
                                   sorted(p[2][1] for p in pts[k - 1:k + 2])[1]))
           for k in range(1, len(pts) - 1)]
    return [pts[0]] + med + [pts[-1]]


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

    def _traza(self, idx: list[int]) -> list[tuple[int, float]]:
        """(índice, km acumulados) de las fotos con GPS fiable. Descarta picos (una o dos
        posiciones desviadas que van y vuelven), una primera o última posición a la que no da
        tiempo a llegar y velocidades imposibles a pie; suaviza el temblor del GPS cuando las
        fotos están muy seguidas y no suma pasos de menos de 60 m."""
        fotos = self.ix.fotos
        pts = [(i, fotos[i]["ts"], _gps(fotos[i])) for i in idx if _gps(fotos[i])]
        buenos: list = []
        for p in _sin_extremos_raros(_sin_picos(pts)):
            if buenos and not _plausible(buenos[-1], p):
                continue  # más rápido que caminando o en bici
            buenos.append(p)
        out: list[tuple[int, float]] = []
        total, ultimo = 0.0, None
        for i, _, g in _suavizar(buenos):
            if ultimo is None:
                ultimo = g
            else:
                d = km_entre(ultimo, g)
                if d >= PASO_MIN:
                    total += d
                    ultimo = g
            out.append((i, total))
        return out

    def _resumen(self, idx: list[int], pid: str) -> dict:
        fotos = self.ix.fotos
        utiles = [i for i in idx if self._es_util(i)]
        nat = [i for i in utiles if self.natural[i] > 0]
        pts = [_gps(fotos[i]) for i in idx if _gps(fotos[i])]
        traza = self._traza(idx)
        km = traza[-1][1] if traza else 0.0
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
        # id = instante de la primera foto: no cambia aunque se analicen más fotos después
        paseos = [self._resumen(s, f"p{int(self.ix.fotos[s[0]]['ts'])}") for s in sesiones]
        paseos = [p for p in paseos if p["naturales"] >= 4]
        paseos.sort(key=lambda p: -p["puntos"])
        self._paseos = paseos
        return paseos

    def por_id(self, pid: str) -> dict | None:
        for p in self.detectar():
            if p["id"] == pid:
                return p
        if pid.startswith("r") and "-" in pid:  # intervalo elegido a mano: se reconstruye
            try:
                d0, d1 = (float(x) for x in pid[1:].split("-", 1))
                return self.por_rango(d0, d1)
            except ValueError:
                return None
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
        """Km recorridos hasta cada foto (interpolando en las que no tienen GPS fiable)."""
        traza = self._traza(idx)
        if not traza:
            return [None] * len(idx)
        fotos = self.ix.fotos
        t_con = [fotos[i]["ts"] for i, _ in traza]
        km_con = [km for _, km in traza]
        return [float(np.interp(fotos[i]["ts"], t_con, km_con)) for i in idx]

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
        S, R = self._sucesos_de(idx)
        return [self.sucesos[self._elegir(s, r)]["palabra"] for s, r in zip(S, R)]

    def _sucesos_de(self, idx: list[int]) -> tuple[np.ndarray, np.ndarray]:
        """Parecido de cada foto con cada suceso (S) y lo que la distingue del resto del paseo (R).
        En un paseo por el monte todas las fotos se parecen a «sendero con sombras»: el suceso
        singular es lo que pasa en esa foto y no en las demás."""
        S = self.suc_sim[idx]
        return S, (S - 0.5 * S.mean(axis=0) if len(idx) >= 4 else S)

    @staticmethod
    def _elegir(s: np.ndarray, r: np.ndarray, palabras=None, evitar: Counter | None = None) -> int:
        """Entre los sucesos que de verdad se ven (≤ 0,025 del mejor parecido absoluto), el más
        propio de esta foto; con `evitar`, cada vez que un suceso ya se ha usado pierde puntos y,
        si ya va por dos, se busca otro algo más lejos (≤ 0,045) antes de repetirlo una tercera vez."""
        posibles = np.flatnonzero(s >= s.max() - 0.025)
        if evitar is None or palabras is None:
            return int(posibles[np.argmax(r[posibles])])
        libres = [int(j) for j in np.flatnonzero(s >= s.max() - 0.045) if evitar[palabras[j]] < 2]
        cand = [int(j) for j in posibles if evitar[palabras[j]] < 2] or libres or [int(j) for j in posibles]
        mejor = max(cand, key=lambda j: r[j] - 0.012 * evitar[palabras[j]])
        evitar[palabras[mejor]] += 1
        return mejor

    def fichas(self, idx: list[int]) -> list[dict]:
        kms = self.km_acumulados(idx)
        S, R = self._sucesos_de(idx) if self.sucesos and self.suc_sim.shape[1] else (None, None)
        out = []
        for n, (i, km) in enumerate(zip(idx, kms)):
            f = self.ix.fotos[i]
            suc = self._suceso(S[n], R[n]) if S is not None else None
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

    def _suceso(self, s: np.ndarray, r: np.ndarray, evitar: Counter | None = None) -> dict | None:
        j = self._elegir(s, r, [d["palabra"] for d in self.sucesos], evitar)
        d = self.sucesos[j]
        return {"frase": d["frase"], "palabra": d["palabra"], "confianza": round(float(s[j]) * 100, 1)}

    def variar_sucesos(self, fichas: list[dict], elegidas: list[str]) -> None:
        """Reparte los sucesos entre las fotos elegidas evitando repetir la misma frase."""
        if not self.sucesos or not self.suc_sim.shape[1]:
            return
        idx = [self.ix.pos[f["uuid"]] for f in fichas if f["uuid"] in self.ix.pos]
        if not idx:
            return
        S, R = self._sucesos_de(idx)
        fila = {self.ix.uuids[i]: n for n, i in enumerate(idx)}
        por_uuid = {f["uuid"]: f for f in fichas}
        evitar: Counter = Counter()
        for u in elegidas:
            n, f = fila.get(u), por_uuid.get(u)
            if n is None or f is None:
                continue
            suc = self._suceso(S[n], R[n], evitar)
            f["suceso"], f["frase"] = suc, suc["frase"]

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
    """Línea descriptiva al estilo Fulton: «UNA CAMINATA DE 4 HORAS DESDE X HASTA Y · 12,3 KM · 3 MAYO 2025»."""
    if not fichas:
        return ""
    l0 = fichas[0].get("lugar") or ""
    l1 = fichas[-1].get("lugar") or ""
    try:
        h = (datetime.fromisoformat(fichas[-1]["fecha"]) - datetime.fromisoformat(fichas[0]["fecha"])).total_seconds() / 3600
    except Exception:
        h = 0
    dur = f"{round(h)} HORAS" if h >= 1.5 else ("UNA HORA" if h >= 0.75 else "")
    kms = [f["km"] for f in fichas if f.get("km") is not None]
    total = (kms[-1] - kms[0]) if len(kms) > 1 else 0.0
    km = f" · {num_es(total)} KM" if total > 0.2 else ""
    con_gps = [f for f in fichas if f.get("lat") is not None and f.get("lon") is not None]
    circular = False
    if len(con_gps) >= 2:
        d = km_entre((con_gps[0]["lat"], con_gps[0]["lon"]), (con_gps[-1]["lat"], con_gps[-1]["lon"]))
        circular = total > 0.5 and d < max(0.3, 0.15 * total)
    if circular:
        donde = f" DESDE Y HASTA {l0}" if l0 else ""
    elif l0 and l1 and l0 != l1:
        donde = f" DESDE {l0} HASTA {l1}"
    elif l0:
        donde = f" EN {l0}"
    else:
        donde = ""
    tipo = "UNA CAMINATA CIRCULAR" if circular else "UNA CAMINATA"
    cuerpo = f"{tipo} DE {dur}" if dur else ("UN PASEO CIRCULAR" if circular else "UN PASEO")
    return f"{cuerpo}{donde}{km} · {fecha_larga(inicio)}".upper().strip(" ·")
