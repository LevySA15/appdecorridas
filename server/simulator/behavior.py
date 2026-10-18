"""O jeito de cada pessoa: probabilidades, tempos de reação e sorteios. Tudo aqui é puro e usa um sorteador com semente."""
from __future__ import annotations

import dataclasses
import random
from dataclasses import dataclass

MAX_SPEED_MPS = 36.0          # o servidor descarta saltos acima de 140 km/h (38,9 m/s): fica abaixo disso


@dataclass(frozen=True)
class Profile:
    name: str = "normal"
    # passageiro
    mean_gap_s: float = 360.0               # tempo médio entre o fim de uma corrida e o próximo pedido
    pix_share: float = 0.6                  # quantos preferem Pix
    give_up_price: float = 0.08             # vê o preço e desiste
    cancel_while_searching: float = 0.08
    cancel_after_accept: float = 0.05
    pay_pix_late: float = 0.05              # paga o Pix só depois do prazo (o servidor cancela)
    pay_qr: float = 0.7                     # paga o QR da corrida em dinheiro que ficou sem pagar
    ok_to_check: float = 0.7                # responde "está tudo bem" ao aviso de segurança
    sos_on_check: float = 0.15
    spontaneous_sos: float = 0.01
    rate: float = 0.85
    emergency_contact: float = 0.8
    double_request: float = 0.03            # toca duas vezes em "pedir"
    # motoqueiro
    accept: float = 0.8
    decline: float = 0.12
    late: float = 0.03                      # responde só depois de a oferta vencer; o resto ignora
    cash_by_hand: float = 0.85              # confirma o dinheiro recebido na mão
    wrong_pin: float = 0.03
    stop_mid_trip: float = 0.02
    detour: float = 0.02
    take_break: float = 0.03
    drop_feed: float = 0.02                 # a conexão em tempo real cai sozinha (chance por minuto)
    double_tap: float = 0.03                # toca duas vezes em "aceitar"
    # tempos e velocidade
    pace: float = 1.0                       # multiplica as esperas das pessoas (0,1 = dez vezes mais depressa)
    speed_mps: float = 8.0
    speedup: float = 1.0
    stop_s: float = 200.0                   # quanto tempo dura uma parada longa no meio da corrida
    detour_m: float = 700.0                 # quanto o desvio de rota sai do caminho (o servidor tolera 300 m)
    offer_window_s: float = 15.0            # quanto o servidor espera pela resposta a uma oferta
    pix_window_s: float = 120.0             # quanto o servidor espera pelo Pix antes de cancelar
    position_every_s: float = 4.0
    poll_every_s: float = 10.0               # além dos avisos, o app relê o estado de vez em quando (parado: três vezes mais devagar)
    tick_s: float = 1.0
    city_scale: float = 1.0

    def check(self) -> None:
        if self.accept + self.decline + self.late > 1.0:
            raise ValueError("as chances de aceitar, recusar e responder tarde passam de 100%")
        if self.speed_mps * self.speedup > MAX_SPEED_MPS:
            raise ValueError(f"velocidade alta demais: o servidor descarta acima de {MAX_SPEED_MPS * 3.6:.0f} km/h")


_PRESETS = {
    "calmo": dict(
        give_up_price=0.0, cancel_while_searching=0.0, cancel_after_accept=0.0, pay_pix_late=0.0, pay_qr=1.0,
        ok_to_check=1.0, sos_on_check=0.0, spontaneous_sos=0.0, double_request=0.0, accept=0.95, decline=0.05, late=0.0,
        cash_by_hand=1.0, wrong_pin=0.0, stop_mid_trip=0.0, detour=0.0, take_break=0.0, drop_feed=0.0,
        double_tap=0.0,
    ),
    "normal": {},
    "bagunca": dict(
        give_up_price=0.15, cancel_while_searching=0.2, cancel_after_accept=0.15, pay_pix_late=0.15, pay_qr=0.4,
        ok_to_check=0.5, sos_on_check=0.3, spontaneous_sos=0.05, double_request=0.1, accept=0.6, decline=0.2, late=0.08,
        cash_by_hand=0.5, wrong_pin=0.15, stop_mid_trip=0.15, detour=0.12, take_break=0.1, drop_feed=0.1,
        double_tap=0.1,
    ),
}


def preset(name: str) -> Profile:
    if name not in _PRESETS:
        raise ValueError(f"perfil desconhecido: {name} (use {', '.join(_PRESETS)})")
    return dataclasses.replace(Profile(), name=name, **_PRESETS[name])


def fast_timings(profile: Profile) -> Profile:
    """Ajusta o perfil aos prazos curtos do servidor descartável rápido (ver `sandbox.seed_database`)."""
    return dataclasses.replace(
        profile, pix_window_s=40.0, offer_window_s=8.0, stop_s=55.0, pace=min(profile.pace, 0.4), speedup=4.0
    )


class Choices:
    """Os sorteios de uma pessoa. Cada ator tem o seu, com semente própria, para a rodada ser repetível."""

    def __init__(self, rng: random.Random, profile: Profile) -> None:
        self.rng = rng
        self.profile = profile

    def chance(self, probability: float) -> bool:
        return self.rng.random() < probability

    def think(self, low: float, high: float) -> float:
        return self.rng.uniform(low, high) * self.profile.pace

    def gap_s(self) -> float:
        return max(1.0, self.rng.expovariate(1.0 / self.profile.mean_gap_s)) * self.profile.pace

    def offer_action(self) -> str:
        p = self.profile
        roll = self.rng.random()
        for action, share in (("accept", p.accept), ("decline", p.decline), ("late", p.late)):
            if roll < share:
                return action
            roll -= share
        return "ignore"

    def method(self, allowed: list[str]) -> str:
        if "pix" in allowed and self.chance(self.profile.pix_share):
            return "pix"
        return "cash" if "cash" in allowed else allowed[0]

    def stars(self) -> int:
        return self.rng.choices([5, 4, 3, 2, 1], weights=[55, 25, 12, 5, 3])[0]

    def rider_speed(self) -> float:
        return self.profile.speed_mps * self.rng.uniform(0.8, 1.2) * self.profile.speedup
