# Núcleo de regras do servidor — Plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Construir, em Python puro e com testes, as regras de negócio do app de corrida de moto (preço, taxa, dívida, divisão do pagamento, livro-caixa, etapas da corrida com fila, escolha de moto e alertas de segurança), sem banco, sem rede e sem dinheiro real.

**Architecture:** Uma biblioteca `app.domain` de funções e dataclasses sem efeitos colaterais, com todos os números ajustáveis em `app/domain/config.py`. Provedores externos (pagamento e mapas) aparecem como interfaces (`Protocol`) com versões falsas em `app/adapters/`, para o servidor da etapa seguinte poder trocar o falso pelo real. Todo dinheiro é inteiro em centavos.

**Tech Stack:** Python 3.12, pytest 8. Nenhuma dependência de execução.

**Spec:** `docs/superpowers/specs/2026-10-08-app-corrida-reconcavo-design.md` (seções 2, 5, 6, 7, 9, 12). Este é o plano 1 de 8; ver `docs/superpowers/plans/2026-10-08-00-roteiro-dos-planos.md`.

## Global Constraints

- Dinheiro sempre em **centavos inteiros** (`int`), nunca `float`. R$ 7,00 = `700`.
- Preço dinâmico: fator entre **0,8 e 1,6**, preço arredondado para **R$ 0,50** (`50` centavos); o fator muda aos poucos; o app mostra o motivo.
- Piso de preço **R$ 5,00** (`500`): o Levy citou R$ 5 como o menor preço visto (adição deste plano à seção 6 da spec).
- Taxa por corrida em **faixas por corrida do dia**, nunca abaixo do piso de lucro de **R$ 0,70** (`70`): Pix da Woovi R$ 0,50 + mapas ~R$ 0,19 (spec 7.4). Valores padrão das faixas são provisórios: `100`, `90`, `80`.
- As **10 primeiras corridas do motoqueiro têm taxa**; depois da 10ª corrida concluída ele fica bloqueado até pagar **R$ 50** (`5000`) uma vez.
- Pagamento: **Pix (Woovi) e dinheiro**. Sem saldo recarregável na v1. O dinheiro do motoqueiro **não passa pela conta da empresa**: a divisão é feita pelo provedor.
- Taxa de corrida em dinheiro vira **dívida** do motoqueiro, descontada da próxima corrida paga por Pix; limite de dívida de **R$ 10,00** (`1000`) para continuar recebendo corridas em dinheiro.
- Nunca duas corridas ativas por motoqueiro; no máximo **1 corrida na fila**; o motoqueiro aceita ou recusa sem penalidade.
- Pix criado quando o motoqueiro aceita; passageiro tem **120 s** para pagar.
- Cancelamento grátis até a moto aceitar e por **60 s** depois; depois disso, compensação de **R$ 2,00** (`200`) ao motoqueiro.
- Oferta de corrida a **uma moto por vez**, **15 s** para aceitar; rota calculada só para as **3** motos mais próximas; desiste da procura em **120 s**; fila vence em **480 s**.
- Livro-caixa **só acrescenta** lançamentos, nunca apaga nem altera; cada corrida fecha em zero.
- Mensagens de erro e textos para o usuário em português do Brasil.
- Commits terminam com a linha `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`.
- Todos os comandos abaixo partem da pasta `server/` (dentro de `/home/levy-anjos/Documentos/projetos/app-corrida-reconcavo`).

## Review Focus

Entradas e situações que a spec sugere, mas que nenhum teste "óbvio" cobriria, da mais provável para a menos provável. Cada linha tem um teste na tarefa indicada.

1. **Motoqueiro com dívida de dinheiro maior que o ganho da corrida Pix.** O esperado é ele não ficar com R$ 0,00: o desconto é limitado a **50%** do que ele receberia (Tarefa 5, `max_debt_share`).
2. **Aviso repetido do provedor / estorno ou pagamento lançado duas vezes.** O esperado é o dinheiro não ser contado duas vezes (Tarefas 5 e 6).
3. **Cancelamento exatamente no limite de 60 s.** O esperado é ainda ser grátis; com 61 s há compensação (Tarefa 7).
4. **GPS com a primeira amostra errada ou com retomada de sinal em outro lugar.** O esperado é o sistema voltar a aceitar as posições depois de 3 saltos seguidos, e não rejeitar tudo para sempre (Tarefa 9).
5. **Corrida na fila com Pix já pago que precisa voltar para a busca.** O esperado é o sistema avisar que há **estorno** a fazer (Tarefa 7).

---

### Task 1: Esqueleto do projeto

**Files:**
- Create: `server/pyproject.toml`
- Create: `server/README.md`
- Create: `server/app/__init__.py`, `server/app/domain/__init__.py`, `server/app/adapters/__init__.py` (vazios)
- Create: `server/tests/__init__.py`, `server/tests/domain/__init__.py` (vazios)
- Create: `server/tests/helpers.py`
- Create: `server/tests/test_smoke.py`
- Modify: `.gitignore` (na raiz do projeto)

**Interfaces:**
- Produces: `tests.helpers.ORIGIN: GeoPoint` e `tests.helpers.pt(north_m: float = 0.0, east_m: float = 0.0) -> GeoPoint` (usados por testes das tarefas 2, 8 e 9).

- [ ] **Step 1: Criar a pasta, o ambiente virtual e os arquivos base**

```bash
mkdir -p server/app/domain server/app/adapters server/tests/domain
touch server/app/__init__.py server/app/domain/__init__.py server/app/adapters/__init__.py
touch server/tests/__init__.py server/tests/domain/__init__.py
```

`server/pyproject.toml`:

```toml
[project]
name = "app-corrida-server"
version = "0.1.0"
description = "Servidor do app de corrida de moto do Recôncavo"
requires-python = ">=3.12"
dependencies = []

[project.optional-dependencies]
dev = ["pytest>=8"]

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["."]
```

`server/README.md`:

```markdown
# Servidor do app de corrida (núcleo de regras)

Biblioteca Python pura com as regras de negócio. Dinheiro sempre em centavos inteiros.

## Rodar os testes

    python3 -m venv .venv
    .venv/bin/pip install -q "pytest>=8"
    .venv/bin/pytest -q

## Mapa do código

- `app/domain/config.py` — todos os números ajustáveis.
- `app/domain/geo.py` — distâncias.
- `app/domain/pricing.py` — preço dinâmico.
- `app/domain/fees.py` — taxa por faixa, entrada de R$ 50, dívida de dinheiro.
- `app/domain/payments.py` — divisão do pagamento, eventos repetidos, interface do provedor.
- `app/domain/ledger.py` — livro-caixa que só acrescenta.
- `app/domain/rides.py` — etapas da corrida (com fila e cancelamento).
- `app/domain/dispatch.py` — escolha da moto e reserva.
- `app/domain/safety.py` — alertas de segurança.
- `app/adapters/` — versões falsas de pagamento e mapas para teste.
```

`server/tests/helpers.py`:

```python
"""Ajudantes de teste: pontos em metros a partir do centro de Santo Antônio de Jesus (aproximado)."""
import math

from app.domain.geo import GeoPoint

ORIGIN = GeoPoint(-12.9644, -39.2597)
_M_PER_DEG_LAT = 111_195.0


def pt(north_m: float = 0.0, east_m: float = 0.0) -> GeoPoint:
    """Ponto a `north_m` metros ao norte e `east_m` metros a leste da origem."""
    lat = ORIGIN.lat + north_m / _M_PER_DEG_LAT
    lng = ORIGIN.lng + east_m / (_M_PER_DEG_LAT * math.cos(math.radians(ORIGIN.lat)))
    return GeoPoint(lat, lng)
```

`server/tests/test_smoke.py`:

```python
def test_pacotes_do_dominio_importam():
    import app.adapters  # noqa: F401
    import app.domain  # noqa: F401
```

Acrescentar ao final de `.gitignore` (raiz do projeto), mantendo a linha existente `.superpowers/`:

```
server/.venv/
__pycache__/
.pytest_cache/
```

- [ ] **Step 2: Criar o ambiente virtual e rodar o teste de fumaça**

Run: `python3 -m venv .venv && .venv/bin/pip install -q "pytest>=8" && .venv/bin/pytest tests/test_smoke.py -v`
Expected: `1 passed`. (O `helpers.py` ainda não é importado por nenhum teste, e depende de `app.domain.geo`, criado na tarefa 2.)

- [ ] **Step 3: Commit**

```bash
cd .. && git add .gitignore server/ && git commit -m "chore(server): esqueleto do projeto e ambiente de testes" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>" && cd server
```

---

### Task 2: Tipos, configuração e distâncias

**Files:**
- Create: `server/app/domain/types.py`
- Create: `server/app/domain/config.py`
- Create: `server/app/domain/geo.py`
- Test: `server/tests/domain/test_geo.py`

**Interfaces:**
- Produces:
  - `PaymentMethod(str, Enum)` com `PIX = "pix"` e `CASH = "cash"`.
  - Dataclasses congeladas `PricingConfig`, `FeeTier`, `FeeConfig`, `RideConfig`, `DispatchConfig`, `SafetyConfig` (campos e padrões abaixo).
  - `GeoPoint(lat: float, lng: float)` (congelada); `haversine_m(a, b) -> float`; `distance_to_segment_m(p, a, b) -> float`; `distance_to_route_m(p, route: list[GeoPoint]) -> float`.

- [ ] **Step 1: Escrever os testes que falham**

`server/tests/domain/test_geo.py`:

```python
import pytest

from app.domain.geo import GeoPoint, distance_to_route_m, distance_to_segment_m, haversine_m
from tests.helpers import ORIGIN, pt


def test_haversine_um_grau_de_latitude():
    assert haversine_m(GeoPoint(0, 0), GeoPoint(1, 0)) == pytest.approx(111_195, abs=50)


def test_haversine_mesmo_ponto_e_zero():
    assert haversine_m(ORIGIN, ORIGIN) == 0


def test_distancia_ao_segmento_perpendicular():
    a, b = pt(0, -1000), pt(0, 1000)
    assert distance_to_segment_m(pt(111, 0), a, b) == pytest.approx(111, abs=2)


def test_distancia_ao_segmento_alem_da_ponta():
    a, b = pt(0, -1000), pt(0, 1000)
    assert distance_to_segment_m(pt(0, 1500), a, b) == pytest.approx(500, abs=5)


def test_distancia_a_rota_usa_o_trecho_mais_proximo():
    route = [pt(0, 0), pt(0, 1000), pt(1000, 1000)]
    assert distance_to_route_m(pt(500, 1050), route) == pytest.approx(50, abs=3)


def test_rota_vazia_da_erro():
    with pytest.raises(ValueError):
        distance_to_route_m(ORIGIN, [])


def test_rota_de_um_ponto_usa_distancia_direta():
    assert distance_to_route_m(pt(0, 300), [ORIGIN]) == pytest.approx(300, abs=3)
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `.venv/bin/pytest tests/domain/test_geo.py -v`
Expected: erro de importação (`ModuleNotFoundError: No module named 'app.domain.geo'`).

- [ ] **Step 3: Implementar**

`server/app/domain/types.py`:

```python
from enum import Enum


class PaymentMethod(str, Enum):
    PIX = "pix"
    CASH = "cash"
```

`server/app/domain/config.py`:

```python
"""Todos os números ajustáveis do sistema. Valores em centavos, segundos ou metros.

Os padrões abaixo vêm da spec (seções 2, 5, 6, 7, 9) ou são propostas iniciais que o Levy
ajusta com dados reais. Nada aqui é lido de arquivo ainda: o servidor da etapa seguinte
vai carregar estes valores do banco.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PricingConfig:
    base_fare_cents: int = 300      # bandeirada
    per_km_cents: int = 150         # por quilômetro
    min_price_cents: int = 500      # piso: R$ 5,00
    round_to_cents: int = 50        # arredonda para R$ 0,50
    factor_min: float = 0.8
    factor_max: float = 1.6
    max_factor_step: float = 0.1    # mudança máxima do fator por atualização


@dataclass(frozen=True)
class FeeTier:
    from_ride: int                  # número da corrida do dia (começa em 1)
    to_ride: int | None             # None = faixa aberta (última)
    fee_cents: int


@dataclass(frozen=True)
class FeeConfig:
    tiers: tuple[FeeTier, ...] = (FeeTier(1, 5, 100), FeeTier(6, 10, 90), FeeTier(11, None, 80))
    min_fee_cents: int = 70             # piso de lucro: Pix R$ 0,50 + mapas ~R$ 0,19
    trial_rides: int = 10               # corridas antes de pagar a entrada
    entry_fee_cents: int = 5000         # R$ 50, uma vez só
    cash_debt_limit_cents: int = 1000   # R$ 10 de dívida de corridas em dinheiro
    max_debt_share: float = 0.5         # no máximo 50% do ganho da corrida Pix abate dívida


@dataclass(frozen=True)
class RideConfig:
    pix_window_s: int = 120
    free_cancel_after_accept_s: int = 60
    cancel_compensation_cents: int = 200
    max_wait_at_arrival_s: int = 300
    queue_max_wait_s: int = 480
    search_give_up_s: int = 120


@dataclass(frozen=True)
class DispatchConfig:
    offer_timeout_s: int = 15
    max_candidates_routed: int = 3
    finishing_max_s: int = 120
    finishing_max_m: int = 500


@dataclass(frozen=True)
class SafetyConfig:
    stopped_after_s: int = 180
    stopped_radius_m: float = 30.0
    off_route_m: float = 300.0
    off_route_confirmations: int = 3
    max_plausible_speed_kmh: float = 140.0
    reanchor_after_rejects: int = 3
    mock_location_jumps: int = 2
```

`server/app/domain/geo.py`:

```python
"""Distâncias geográficas simples (sem bibliotecas externas)."""
from __future__ import annotations

import math
from dataclasses import dataclass

EARTH_RADIUS_M = 6_371_000.0


@dataclass(frozen=True)
class GeoPoint:
    lat: float
    lng: float


def haversine_m(a: GeoPoint, b: GeoPoint) -> float:
    lat1, lat2 = math.radians(a.lat), math.radians(b.lat)
    dlat = lat2 - lat1
    dlng = math.radians(b.lng - a.lng)
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlng / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(h))


def distance_to_segment_m(p: GeoPoint, a: GeoPoint, b: GeoPoint) -> float:
    """Menor distância de `p` ao segmento a–b, em metros (projeção local plana)."""
    lat0 = math.radians(p.lat)

    def to_xy(q: GeoPoint) -> tuple[float, float]:
        x = math.radians(q.lng - p.lng) * math.cos(lat0) * EARTH_RADIUS_M
        y = math.radians(q.lat - p.lat) * EARTH_RADIUS_M
        return x, y

    ax, ay = to_xy(a)
    bx, by = to_xy(b)
    dx, dy = bx - ax, by - ay
    seg_len2 = dx * dx + dy * dy
    if seg_len2 == 0:
        return math.hypot(ax, ay)
    t = max(0.0, min(1.0, -(ax * dx + ay * dy) / seg_len2))
    return math.hypot(ax + t * dx, ay + t * dy)


def distance_to_route_m(p: GeoPoint, route: list[GeoPoint]) -> float:
    if not route:
        raise ValueError("a rota está vazia")
    if len(route) == 1:
        return haversine_m(p, route[0])
    return min(distance_to_segment_m(p, a, b) for a, b in zip(route, route[1:]))
```

- [ ] **Step 4: Rodar e ver passar**

Run: `.venv/bin/pytest -q`
Expected: todos os testes passam (teste de fumaça e os 7 de geo).

- [ ] **Step 5: Commit**

```bash
git add app/domain/types.py app/domain/config.py app/domain/geo.py tests/domain/test_geo.py && git commit -m "feat(domain): tipos, configuração e distâncias" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Preço dinâmico

**Files:**
- Create: `server/app/domain/pricing.py`
- Test: `server/tests/domain/test_pricing.py`

**Interfaces:**
- Consumes: `PricingConfig` (tarefa 2).
- Produces:
  - `distance_fare_cents(distance_m: float, cfg: PricingConfig = PricingConfig()) -> int`
  - `target_factor(pending_requests: int, free_riders: int, cfg: PricingConfig = PricingConfig()) -> float`
  - `smooth_factor(previous: float, target: float, cfg: PricingConfig = PricingConfig()) -> float`
  - `final_price_cents(distance_m: float, factor: float, cfg: PricingConfig = PricingConfig()) -> int`
  - `price_reason(factor: float) -> str`

- [ ] **Step 1: Escrever os testes que falham**

`server/tests/domain/test_pricing.py`:

```python
import pytest

from app.domain.config import PricingConfig
from app.domain.pricing import (
    distance_fare_cents,
    final_price_cents,
    price_reason,
    smooth_factor,
    target_factor,
)


def test_tarifa_pela_distancia():
    assert distance_fare_cents(0) == 300
    assert distance_fare_cents(2000) == 600
    assert distance_fare_cents(3000) == 750


def test_distancia_negativa_da_erro():
    with pytest.raises(ValueError):
        distance_fare_cents(-1)


def test_fator_alvo_com_muita_moto_livre_cai_para_o_minimo():
    assert target_factor(pending_requests=0, free_riders=10) == 0.8


def test_fator_alvo_com_pouca_moto_sobe_para_o_maximo():
    assert target_factor(pending_requests=5, free_riders=2) == 1.6


def test_fator_alvo_equilibrado_e_um():
    assert target_factor(pending_requests=3, free_riders=3) == 1.0
    assert target_factor(pending_requests=0, free_riders=0) == 1.0


def test_fator_alvo_intermediario():
    assert target_factor(pending_requests=2, free_riders=1) == pytest.approx(1.5)


def test_fator_alvo_com_numero_negativo_da_erro():
    with pytest.raises(ValueError):
        target_factor(-1, 0)
    with pytest.raises(ValueError):
        target_factor(0, -1)


def test_fator_muda_aos_poucos():
    assert smooth_factor(1.0, 1.6) == pytest.approx(1.1)
    assert smooth_factor(1.2, 0.8) == pytest.approx(1.1)


def test_fator_perto_do_alvo_vai_direto():
    assert smooth_factor(1.0, 1.05) == pytest.approx(1.05)


def test_preco_final_tipico():
    assert final_price_cents(2000, 1.0) == 600
    assert final_price_cents(3000, 1.0) == 750


def test_preco_final_com_fator_alto_arredonda_para_50_centavos():
    assert final_price_cents(2000, 1.6) == 950


def test_preco_final_nunca_fica_abaixo_do_piso():
    assert final_price_cents(2000, 0.8) == 500
    assert final_price_cents(0, 0.8) == 500


def test_preco_final_com_fator_fora_da_faixa_e_limitado():
    assert final_price_cents(3000, 5.0) == 1200
    assert final_price_cents(3000, 0.1) == 600


def test_arredondamento_meio_para_cima():
    cfg = PricingConfig(base_fare_cents=500, per_km_cents=0)
    assert final_price_cents(0, 1.25, cfg) == 650


def test_motivo_do_preco():
    assert price_reason(0.8) == "Muita moto livre agora, preço menor."
    assert price_reason(1.0) == "Preço normal para este horário."
    assert price_reason(1.6) == "Poucas motos agora, preço maior."
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `.venv/bin/pytest tests/domain/test_pricing.py -v`
Expected: `ModuleNotFoundError: No module named 'app.domain.pricing'`.

- [ ] **Step 3: Implementar**

`server/app/domain/pricing.py`:

```python
"""Preço da corrida (spec, seção 6). Valores em centavos inteiros."""
from __future__ import annotations

import math

from app.domain.config import PricingConfig

_DEFAULT = PricingConfig()


def _round_half_up(value: float) -> int:
    return int(math.floor(value + 0.5))


def _clamp_factor(factor: float, cfg: PricingConfig) -> float:
    return max(cfg.factor_min, min(cfg.factor_max, factor))


def distance_fare_cents(distance_m: float, cfg: PricingConfig = _DEFAULT) -> int:
    if distance_m < 0:
        raise ValueError("a distância não pode ser negativa")
    return cfg.base_fare_cents + _round_half_up(cfg.per_km_cents * distance_m / 1000)


def target_factor(pending_requests: int, free_riders: int, cfg: PricingConfig = _DEFAULT) -> float:
    """Fator desejado: relação entre pedidos e motos livres, limitada à faixa da config."""
    if pending_requests < 0 or free_riders < 0:
        raise ValueError("pedidos e motos não podem ser negativos")
    ratio = (pending_requests + 1) / (free_riders + 1)
    return _clamp_factor(ratio, cfg)


def smooth_factor(previous: float, target: float, cfg: PricingConfig = _DEFAULT) -> float:
    """Anda do fator anterior para o alvo em passos de no máximo `max_factor_step`."""
    delta = target - previous
    if abs(delta) <= cfg.max_factor_step:
        return target
    return previous + math.copysign(cfg.max_factor_step, delta)


def final_price_cents(distance_m: float, factor: float, cfg: PricingConfig = _DEFAULT) -> int:
    raw = distance_fare_cents(distance_m, cfg) * _clamp_factor(factor, cfg)
    rounded = _round_half_up(raw / cfg.round_to_cents) * cfg.round_to_cents
    return max(cfg.min_price_cents, rounded)


def price_reason(factor: float) -> str:
    if factor <= 0.9:
        return "Muita moto livre agora, preço menor."
    if factor >= 1.2:
        return "Poucas motos agora, preço maior."
    return "Preço normal para este horário."
```

- [ ] **Step 4: Rodar e ver passar**

Run: `.venv/bin/pytest tests/domain/test_pricing.py -v`
Expected: todos passam (15 testes).

- [ ] **Step 5: Commit**

```bash
git add app/domain/pricing.py tests/domain/test_pricing.py && git commit -m "feat(domain): preço dinâmico com fator suavizado e piso" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Taxa por corrida, entrada de R$ 50 e dívida de dinheiro

**Files:**
- Create: `server/app/domain/fees.py`
- Test: `server/tests/domain/test_fees.py`

**Interfaces:**
- Consumes: `FeeConfig`, `FeeTier` (tarefa 2), `PaymentMethod` (tarefa 2).
- Produces:
  - `validate_fee_config(cfg: FeeConfig) -> None` (levanta `ValueError`)
  - `fee_for_ride(ride_number_today: int, cfg: FeeConfig = FeeConfig()) -> int`
  - `RiderAccount(rider_id: str, completed_rides: int = 0, entry_paid: bool = False, cash_debt_cents: int = 0)` (dataclass mutável)
  - `offer_block_reason(acc: RiderAccount, cfg: FeeConfig = FeeConfig()) -> str | None` (devolve `"entrada_pendente"` ou `None`)
  - `can_receive_offers(acc, cfg=FeeConfig()) -> bool`
  - `can_receive_cash_offers(acc, cfg=FeeConfig()) -> bool`
  - `register_completed_ride(acc: RiderAccount, method: PaymentMethod, fee_cents: int) -> None`
  - `mark_entry_paid(acc: RiderAccount) -> None`

- [ ] **Step 1: Escrever os testes que falham**

`server/tests/domain/test_fees.py`:

```python
import pytest

from app.domain.config import FeeConfig, FeeTier
from app.domain.fees import (
    RiderAccount,
    can_receive_cash_offers,
    can_receive_offers,
    fee_for_ride,
    mark_entry_paid,
    offer_block_reason,
    register_completed_ride,
    validate_fee_config,
)
from app.domain.types import PaymentMethod


def test_taxa_por_faixa_do_dia():
    assert fee_for_ride(1) == 100
    assert fee_for_ride(5) == 100
    assert fee_for_ride(6) == 90
    assert fee_for_ride(10) == 90
    assert fee_for_ride(11) == 80
    assert fee_for_ride(50) == 80


def test_numero_de_corrida_invalido():
    with pytest.raises(ValueError):
        fee_for_ride(0)


def test_config_padrao_e_valida():
    validate_fee_config(FeeConfig())


def test_faixa_abaixo_do_piso_de_lucro_e_invalida():
    cfg = FeeConfig(tiers=(FeeTier(1, None, 60),), min_fee_cents=70)
    with pytest.raises(ValueError, match="piso"):
        validate_fee_config(cfg)


def test_faixas_com_buraco_sao_invalidas():
    cfg = FeeConfig(tiers=(FeeTier(1, 5, 100), FeeTier(7, None, 90)))
    with pytest.raises(ValueError):
        validate_fee_config(cfg)


def test_ultima_faixa_precisa_ser_aberta():
    cfg = FeeConfig(tiers=(FeeTier(1, 5, 100), FeeTier(6, 10, 90)))
    with pytest.raises(ValueError):
        validate_fee_config(cfg)


def test_faixa_aberta_so_pode_ser_a_ultima():
    cfg = FeeConfig(tiers=(FeeTier(1, None, 100), FeeTier(6, None, 90)))
    with pytest.raises(ValueError):
        validate_fee_config(cfg)


def test_as_dez_corridas_de_teste_nao_bloqueiam_e_a_decima_primeira_sim():
    acc = RiderAccount("r1", completed_rides=9)
    assert can_receive_offers(acc) is True
    acc.completed_rides = 10
    assert can_receive_offers(acc) is False
    assert offer_block_reason(acc) == "entrada_pendente"


def test_pagar_a_entrada_libera():
    acc = RiderAccount("r1", completed_rides=10)
    mark_entry_paid(acc)
    assert can_receive_offers(acc) is True
    assert offer_block_reason(acc) is None


def test_corrida_em_dinheiro_vira_divida_e_pix_nao():
    acc = RiderAccount("r1")
    register_completed_ride(acc, PaymentMethod.CASH, 100)
    assert acc.cash_debt_cents == 100
    register_completed_ride(acc, PaymentMethod.PIX, 100)
    assert acc.cash_debt_cents == 100
    assert acc.completed_rides == 2


def test_limite_de_divida_bloqueia_so_corridas_em_dinheiro():
    acc = RiderAccount("r1", cash_debt_cents=999)
    assert can_receive_cash_offers(acc) is True
    acc.cash_debt_cents = 1000
    assert can_receive_cash_offers(acc) is False
    assert can_receive_offers(acc) is True


def test_entrada_pendente_bloqueia_tambem_o_dinheiro():
    acc = RiderAccount("r1", completed_rides=10)
    assert can_receive_cash_offers(acc) is False
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `.venv/bin/pytest tests/domain/test_fees.py -v`
Expected: `ModuleNotFoundError: No module named 'app.domain.fees'`.

- [ ] **Step 3: Implementar**

`server/app/domain/fees.py`:

```python
"""Taxa por corrida, entrada de R$ 50 e dívida de corridas em dinheiro (spec, seções 2 e 7)."""
from __future__ import annotations

from dataclasses import dataclass

from app.domain.config import FeeConfig
from app.domain.types import PaymentMethod

_DEFAULT = FeeConfig()


def validate_fee_config(cfg: FeeConfig) -> None:
    """Confere que as faixas cobrem 1..∞ sem buracos e nenhuma fica abaixo do piso de lucro."""
    if not cfg.tiers:
        raise ValueError("a configuração de taxas não tem faixas")
    expected_start = 1
    for index, tier in enumerate(cfg.tiers):
        if tier.from_ride != expected_start:
            raise ValueError(f"a faixa {index + 1} deveria começar na corrida {expected_start}")
        if tier.fee_cents < cfg.min_fee_cents:
            raise ValueError(f"a faixa {index + 1} está abaixo do piso de lucro")
        if tier.to_ride is None:
            if index != len(cfg.tiers) - 1:
                raise ValueError("só a última faixa pode ser aberta")
            return
        if tier.to_ride < tier.from_ride:
            raise ValueError(f"a faixa {index + 1} termina antes de começar")
        expected_start = tier.to_ride + 1
    raise ValueError("a última faixa precisa ser aberta")


def fee_for_ride(ride_number_today: int, cfg: FeeConfig = _DEFAULT) -> int:
    if ride_number_today < 1:
        raise ValueError("o número da corrida do dia começa em 1")
    for tier in cfg.tiers:
        if ride_number_today >= tier.from_ride and (tier.to_ride is None or ride_number_today <= tier.to_ride):
            return tier.fee_cents
    raise ValueError(f"nenhuma faixa cobre a corrida {ride_number_today}")


@dataclass
class RiderAccount:
    rider_id: str
    completed_rides: int = 0
    entry_paid: bool = False
    cash_debt_cents: int = 0


def offer_block_reason(acc: RiderAccount, cfg: FeeConfig = _DEFAULT) -> str | None:
    if acc.completed_rides >= cfg.trial_rides and not acc.entry_paid:
        return "entrada_pendente"
    return None


def can_receive_offers(acc: RiderAccount, cfg: FeeConfig = _DEFAULT) -> bool:
    return offer_block_reason(acc, cfg) is None


def can_receive_cash_offers(acc: RiderAccount, cfg: FeeConfig = _DEFAULT) -> bool:
    return can_receive_offers(acc, cfg) and acc.cash_debt_cents < cfg.cash_debt_limit_cents


def register_completed_ride(acc: RiderAccount, method: PaymentMethod, fee_cents: int) -> None:
    """Conta a corrida concluída; se foi em dinheiro, a taxa vira dívida do motoqueiro."""
    acc.completed_rides += 1
    if method is PaymentMethod.CASH:
        acc.cash_debt_cents += fee_cents


def mark_entry_paid(acc: RiderAccount) -> None:
    acc.entry_paid = True
```

- [ ] **Step 4: Rodar e ver passar**

Run: `.venv/bin/pytest tests/domain/test_fees.py -v`
Expected: todos passam (12 testes).

- [ ] **Step 5: Commit**

```bash
git add app/domain/fees.py tests/domain/test_fees.py && git commit -m "feat(domain): taxa por faixa, entrada de R\$ 50 e dívida de dinheiro" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Divisão do pagamento, eventos repetidos e provedor falso

**Files:**
- Create: `server/app/domain/payments.py`
- Create: `server/app/adapters/fake_payments.py`
- Test: `server/tests/domain/test_payments.py`

**Interfaces:**
- Consumes: `RiderAccount` (tarefa 4).
- Produces:
  - `Split(rider_cents: int, company_cents: int, debt_paid_cents: int)` (congelada)
  - `compute_split(price_cents: int, fee_cents: int, debt_cents: int = 0, max_debt_share: float = 0.5) -> Split`
  - `settle_pix_ride(acc: RiderAccount, price_cents: int, fee_cents: int, max_debt_share: float = 0.5) -> Split` (abate `acc.cash_debt_cents`)
  - `ProcessedEvents` com `first_time(event_id: str) -> bool`
  - `PixCharge(charge_id, ride_id, rider_id, amount_cents, split, paid=False, refunded=False)` (dataclass mutável)
  - `PaymentProvider` (Protocol): `create_pix_charge(ride_id: str, rider_id: str, amount_cents: int, split: Split) -> PixCharge` e `refund(charge_id: str) -> None`
  - `FakePaymentProvider` com `charges: dict[str, PixCharge]`, `create_pix_charge`, `mark_paid(charge_id) -> dict`, `refund`.

- [ ] **Step 1: Escrever os testes que falham**

`server/tests/domain/test_payments.py`:

```python
import pytest

from app.adapters.fake_payments import FakePaymentProvider
from app.domain.fees import RiderAccount
from app.domain.payments import ProcessedEvents, Split, compute_split, settle_pix_ride


def test_divisao_sem_divida():
    assert compute_split(700, 100) == Split(rider_cents=600, company_cents=100, debt_paid_cents=0)


def test_divisao_com_divida_pequena_abate_tudo():
    assert compute_split(700, 100, 300) == Split(rider_cents=300, company_cents=400, debt_paid_cents=300)


def test_divisao_limita_o_desconto_da_divida_a_metade_do_ganho():
    # Review Focus 1: divida (1000) maior que o ganho (600): o motoqueiro nao fica com R$ 0,00.
    split = compute_split(700, 100, 1000)
    assert split == Split(rider_cents=300, company_cents=400, debt_paid_cents=300)


def test_divisao_com_limite_configuravel():
    split = compute_split(700, 100, 1000, max_debt_share=1.0)
    assert split == Split(rider_cents=0, company_cents=700, debt_paid_cents=600)


def test_divisao_taxa_maior_que_o_preco_da_erro():
    with pytest.raises(ValueError):
        compute_split(100, 200)


def test_divisao_preco_zero_ou_negativo_da_erro():
    with pytest.raises(ValueError):
        compute_split(0, 0)
    with pytest.raises(ValueError):
        compute_split(-5, 0)


def test_divisao_soma_sempre_o_preco():
    for debt in (0, 50, 300, 5000):
        s = compute_split(950, 90, debt)
        assert s.rider_cents + s.company_cents == 950


def test_settle_pix_ride_abate_a_divida_da_conta():
    acc = RiderAccount("r1", cash_debt_cents=1000)
    split = settle_pix_ride(acc, 700, 100)
    assert split.debt_paid_cents == 300
    assert acc.cash_debt_cents == 700


def test_evento_repetido_so_vale_uma_vez():
    # Review Focus 2: aviso repetido do provedor nao pode ser tratado duas vezes.
    events = ProcessedEvents()
    assert events.first_time("e1") is True
    assert events.first_time("e1") is False
    assert events.first_time("e2") is True


def test_provedor_falso_cria_e_paga_cobranca():
    provider = FakePaymentProvider()
    charge = provider.create_pix_charge("ride-1", "rider-1", 700, compute_split(700, 100))
    assert charge.charge_id == "ch-1"
    assert charge.paid is False
    event = provider.mark_paid("ch-1")
    assert event == {
        "event_id": "evt-ch-1-paid",
        "type": "paid",
        "charge_id": "ch-1",
        "ride_id": "ride-1",
        "amount_cents": 700,
    }
    assert provider.charges["ch-1"].paid is True


def test_provedor_falso_so_estorna_cobranca_paga_e_uma_vez():
    provider = FakePaymentProvider()
    provider.create_pix_charge("ride-1", "rider-1", 700, compute_split(700, 100))
    with pytest.raises(ValueError, match="não paga"):
        provider.refund("ch-1")
    provider.mark_paid("ch-1")
    provider.refund("ch-1")
    assert provider.charges["ch-1"].refunded is True
    with pytest.raises(ValueError, match="já devolvida"):
        provider.refund("ch-1")


def test_provedor_falso_recusa_divisao_que_nao_fecha():
    provider = FakePaymentProvider()
    with pytest.raises(ValueError, match="divisão"):
        provider.create_pix_charge("ride-1", "rider-1", 700, Split(100, 100, 0))
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `.venv/bin/pytest tests/domain/test_payments.py -v`
Expected: `ModuleNotFoundError: No module named 'app.adapters.fake_payments'`.

- [ ] **Step 3: Implementar**

`server/app/domain/payments.py`:

```python
"""Divisão do pagamento, eventos repetidos do provedor e interface do provedor (spec, seção 7)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from app.domain.fees import RiderAccount


@dataclass(frozen=True)
class Split:
    rider_cents: int
    company_cents: int
    debt_paid_cents: int


def compute_split(
    price_cents: int, fee_cents: int, debt_cents: int = 0, max_debt_share: float = 0.5
) -> Split:
    """Divide o preço entre motoqueiro e empresa.

    A empresa fica com a taxa mais o que for abatido da dívida de corridas em dinheiro.
    O abatimento é limitado a `max_debt_share` do que o motoqueiro receberia.
    """
    if price_cents <= 0 or fee_cents < 0 or debt_cents < 0:
        raise ValueError("preço, taxa e dívida precisam ser positivos")
    if fee_cents > price_cents:
        raise ValueError("a taxa é maior que o preço da corrida")
    rider_gross = price_cents - fee_cents
    debt_paid = min(debt_cents, int(rider_gross * max_debt_share))
    return Split(
        rider_cents=rider_gross - debt_paid,
        company_cents=fee_cents + debt_paid,
        debt_paid_cents=debt_paid,
    )


def settle_pix_ride(
    acc: RiderAccount, price_cents: int, fee_cents: int, max_debt_share: float = 0.5
) -> Split:
    """Calcula a divisão de uma corrida Pix e abate a dívida da conta do motoqueiro."""
    split = compute_split(price_cents, fee_cents, acc.cash_debt_cents, max_debt_share)
    acc.cash_debt_cents -= split.debt_paid_cents
    return split


class ProcessedEvents:
    """Guarda os avisos do provedor já tratados, para nunca tratar o mesmo aviso duas vezes."""

    def __init__(self) -> None:
        self._seen: set[str] = set()

    def first_time(self, event_id: str) -> bool:
        if event_id in self._seen:
            return False
        self._seen.add(event_id)
        return True


@dataclass
class PixCharge:
    charge_id: str
    ride_id: str
    rider_id: str
    amount_cents: int
    split: Split
    paid: bool = False
    refunded: bool = False


class PaymentProvider(Protocol):
    def create_pix_charge(
        self, ride_id: str, rider_id: str, amount_cents: int, split: Split
    ) -> PixCharge: ...

    def refund(self, charge_id: str) -> None: ...
```

`server/app/adapters/fake_payments.py`:

```python
"""Provedor de pagamento falso, para testes e para o simulador. Não fala com ninguém."""
from __future__ import annotations

from app.domain.payments import PixCharge, Split


class FakePaymentProvider:
    def __init__(self) -> None:
        self.charges: dict[str, PixCharge] = {}
        self._counter = 0

    def create_pix_charge(
        self, ride_id: str, rider_id: str, amount_cents: int, split: Split
    ) -> PixCharge:
        if split.rider_cents + split.company_cents != amount_cents:
            raise ValueError("a divisão não fecha com o valor da cobrança")
        self._counter += 1
        charge = PixCharge(
            charge_id=f"ch-{self._counter}",
            ride_id=ride_id,
            rider_id=rider_id,
            amount_cents=amount_cents,
            split=split,
        )
        self.charges[charge.charge_id] = charge
        return charge

    def mark_paid(self, charge_id: str) -> dict:
        charge = self.charges[charge_id]
        charge.paid = True
        return {
            "event_id": f"evt-{charge_id}-paid",
            "type": "paid",
            "charge_id": charge_id,
            "ride_id": charge.ride_id,
            "amount_cents": charge.amount_cents,
        }

    def refund(self, charge_id: str) -> None:
        charge = self.charges[charge_id]
        if not charge.paid:
            raise ValueError("cobrança não paga, não há o que devolver")
        if charge.refunded:
            raise ValueError("cobrança já devolvida")
        charge.refunded = True
```

- [ ] **Step 4: Rodar e ver passar**

Run: `.venv/bin/pytest tests/domain/test_payments.py -v`
Expected: todos passam (12 testes).

- [ ] **Step 5: Commit**

```bash
git add app/domain/payments.py app/adapters/fake_payments.py tests/domain/test_payments.py && git commit -m "feat(domain): divisão do pagamento, eventos repetidos e provedor falso" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 6: Livro-caixa que só acrescenta

**Files:**
- Create: `server/app/domain/ledger.py`
- Test: `server/tests/domain/test_ledger.py`

**Interfaces:**
- Consumes: `Split` (tarefa 5).
- Produces:
  - `EntryKind(str, Enum)`: `RIDE_PAYMENT`, `REFUND`, `ENTRY_FEE`, `CORRECTION`.
  - `LedgerEntry(entry_id: int, ref: str, account: str, amount_cents: int, kind: EntryKind, note: str = "")` (congelada).
  - `Ledger` com constantes `PROVIDER = "provider"`, `COMPANY = "company"` e métodos: `entries -> tuple[LedgerEntry, ...]`, `post_ride_payment(ride_id: str, rider_id: str, price_cents: int, split: Split) -> None`, `post_refund(ride_id: str) -> None`, `post_entry_fee(rider_id: str, amount_cents: int) -> None`, `post_correction(ref: str, lines: list[tuple[str, int]], reason: str) -> None`, `balance(account: str) -> int`, `is_balanced() -> bool`, `reconcile(provider_received_by_ref: dict[str, int]) -> dict[str, int]`.
  - Convenção de `ref`: `"ride:<ride_id>"` e `"entry:<rider_id>"`. Conta do motoqueiro: `"rider:<rider_id>"`. O provedor é lançado com valor **negativo** (origem do dinheiro); motoqueiro e empresa com valor positivo (destino). Cada `ref` soma zero.

- [ ] **Step 1: Escrever os testes que falham**

`server/tests/domain/test_ledger.py`:

```python
import dataclasses

import pytest

from app.domain.ledger import Ledger
from app.domain.payments import Split, compute_split


def _ledger_com_corrida() -> Ledger:
    ledger = Ledger()
    ledger.post_ride_payment("ride-1", "rider-1", 700, compute_split(700, 100))
    return ledger


def test_pagamento_de_corrida_fecha_em_zero():
    ledger = _ledger_com_corrida()
    assert ledger.is_balanced() is True
    assert ledger.balance("rider:rider-1") == 600
    assert ledger.balance(Ledger.COMPANY) == 100
    assert ledger.balance(Ledger.PROVIDER) == -700


def test_divisao_que_nao_fecha_com_o_preco_e_recusada():
    with pytest.raises(ValueError, match="divisão"):
        Ledger().post_ride_payment("ride-1", "rider-1", 700, Split(500, 100, 0))


def test_pagamento_lancado_duas_vezes_e_recusado():
    # Review Focus 2: o mesmo pagamento nao pode entrar duas vezes no livro.
    ledger = _ledger_com_corrida()
    with pytest.raises(ValueError, match="já lançado"):
        ledger.post_ride_payment("ride-1", "rider-1", 700, compute_split(700, 100))


def test_estorno_zera_os_saldos():
    ledger = _ledger_com_corrida()
    ledger.post_refund("ride-1")
    assert ledger.balance("rider:rider-1") == 0
    assert ledger.balance(Ledger.COMPANY) == 0
    assert ledger.balance(Ledger.PROVIDER) == 0
    assert ledger.is_balanced() is True


def test_estorno_duplo_e_recusado():
    ledger = _ledger_com_corrida()
    ledger.post_refund("ride-1")
    with pytest.raises(ValueError, match="já devolvido"):
        ledger.post_refund("ride-1")


def test_estorno_de_corrida_sem_pagamento_e_recusado():
    with pytest.raises(ValueError, match="não encontrado"):
        Ledger().post_refund("ride-9")


def test_taxa_de_entrada():
    ledger = Ledger()
    ledger.post_entry_fee("rider-1", 5000)
    assert ledger.balance(Ledger.COMPANY) == 5000
    assert ledger.balance(Ledger.PROVIDER) == -5000
    assert ledger.is_balanced() is True
    with pytest.raises(ValueError, match="já lançada"):
        ledger.post_entry_fee("rider-1", 5000)


def test_lancamentos_sao_imutaveis_e_a_lista_e_uma_copia():
    ledger = _ledger_com_corrida()
    entry = ledger.entries[0]
    with pytest.raises(dataclasses.FrozenInstanceError):
        entry.amount_cents = 1  # type: ignore[misc]
    assert isinstance(ledger.entries, tuple)
    assert len(ledger.entries) == 3


def test_correcao_balanceada_e_registrada():
    ledger = _ledger_com_corrida()
    ledger.post_correction("ride:ride-1", [(Ledger.COMPANY, -50), ("rider:rider-1", 50)], "ajuste de taxa")
    assert ledger.balance(Ledger.COMPANY) == 50
    assert ledger.balance("rider:rider-1") == 650
    assert ledger.is_balanced() is True


def test_correcao_que_nao_fecha_em_zero_e_recusada():
    ledger = _ledger_com_corrida()
    with pytest.raises(ValueError, match="zero"):
        ledger.post_correction("ride:ride-1", [(Ledger.COMPANY, -50)], "erro")


def test_correcao_sem_motivo_ou_de_referencia_desconhecida_e_recusada():
    ledger = _ledger_com_corrida()
    with pytest.raises(ValueError, match="motivo"):
        ledger.post_correction("ride:ride-1", [(Ledger.COMPANY, -50), ("rider:rider-1", 50)], " ")
    with pytest.raises(ValueError, match="desconhecida"):
        ledger.post_correction("ride:nao-existe", [(Ledger.COMPANY, -50), ("rider:rider-1", 50)], "x")


def test_conciliacao_sem_diferenca():
    assert _ledger_com_corrida().reconcile({"ride:ride-1": 700}) == {}


def test_conciliacao_aponta_diferencas():
    ledger = _ledger_com_corrida()
    assert ledger.reconcile({"ride:ride-1": 600}) == {"ride:ride-1": -100}
    assert ledger.reconcile({}) == {"ride:ride-1": -700}
    assert ledger.reconcile({"ride:ride-1": 700, "ride:ride-9": 500}) == {"ride:ride-9": 500}


def test_conciliacao_depois_de_estorno_nao_acusa_diferenca():
    ledger = _ledger_com_corrida()
    ledger.post_refund("ride-1")
    assert ledger.reconcile({}) == {}
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `.venv/bin/pytest tests/domain/test_ledger.py -v`
Expected: `ModuleNotFoundError: No module named 'app.domain.ledger'`.

- [ ] **Step 3: Implementar**

`server/app/domain/ledger.py`:

```python
"""Livro-caixa que só acrescenta (spec, seção 7.6).

Cada `ref` (uma corrida, uma entrada) soma zero: o provedor é a origem do dinheiro
(valor negativo); o motoqueiro e a empresa são o destino (valores positivos).
A dívida de corridas em dinheiro vive na conta do motoqueiro (`RiderAccount`), não aqui.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from app.domain.payments import Split


class EntryKind(str, Enum):
    RIDE_PAYMENT = "ride_payment"
    REFUND = "refund"
    ENTRY_FEE = "entry_fee"
    CORRECTION = "correction"


@dataclass(frozen=True)
class LedgerEntry:
    entry_id: int
    ref: str
    account: str
    amount_cents: int
    kind: EntryKind
    note: str = ""


class Ledger:
    PROVIDER = "provider"
    COMPANY = "company"

    def __init__(self) -> None:
        self._entries: list[LedgerEntry] = []

    @property
    def entries(self) -> tuple[LedgerEntry, ...]:
        return tuple(self._entries)

    def _append(self, ref: str, account: str, amount_cents: int, kind: EntryKind, note: str = "") -> None:
        self._entries.append(LedgerEntry(len(self._entries) + 1, ref, account, amount_cents, kind, note))

    def _has(self, ref: str, kind: EntryKind) -> bool:
        return any(e.ref == ref and e.kind is kind for e in self._entries)

    def post_ride_payment(self, ride_id: str, rider_id: str, price_cents: int, split: Split) -> None:
        if split.rider_cents + split.company_cents != price_cents:
            raise ValueError("a divisão não fecha com o preço da corrida")
        ref = f"ride:{ride_id}"
        if self._has(ref, EntryKind.RIDE_PAYMENT):
            raise ValueError(f"pagamento da corrida {ride_id} já lançado")
        self._append(ref, self.PROVIDER, -price_cents, EntryKind.RIDE_PAYMENT)
        self._append(ref, f"rider:{rider_id}", split.rider_cents, EntryKind.RIDE_PAYMENT)
        self._append(ref, self.COMPANY, split.company_cents, EntryKind.RIDE_PAYMENT)

    def post_refund(self, ride_id: str) -> None:
        ref = f"ride:{ride_id}"
        originals = [e for e in self._entries if e.ref == ref and e.kind is EntryKind.RIDE_PAYMENT]
        if not originals:
            raise ValueError(f"pagamento da corrida {ride_id} não encontrado")
        if self._has(ref, EntryKind.REFUND):
            raise ValueError(f"corrida {ride_id} já devolvido")
        for e in originals:
            self._append(ref, e.account, -e.amount_cents, EntryKind.REFUND)

    def post_entry_fee(self, rider_id: str, amount_cents: int) -> None:
        ref = f"entry:{rider_id}"
        if self._has(ref, EntryKind.ENTRY_FEE):
            raise ValueError(f"entrada do motoqueiro {rider_id} já lançada")
        self._append(ref, self.PROVIDER, -amount_cents, EntryKind.ENTRY_FEE)
        self._append(ref, self.COMPANY, amount_cents, EntryKind.ENTRY_FEE)

    def post_correction(self, ref: str, lines: list[tuple[str, int]], reason: str) -> None:
        if not reason.strip():
            raise ValueError("a correção precisa de um motivo")
        if not any(e.ref == ref for e in self._entries):
            raise ValueError(f"referência desconhecida: {ref}")
        if sum(amount for _, amount in lines) != 0:
            raise ValueError("as linhas da correção precisam somar zero")
        for account, amount in lines:
            self._append(ref, account, amount, EntryKind.CORRECTION, reason)

    def balance(self, account: str) -> int:
        return sum(e.amount_cents for e in self._entries if e.account == account)

    def is_balanced(self) -> bool:
        totals: dict[str, int] = {}
        for e in self._entries:
            totals[e.ref] = totals.get(e.ref, 0) + e.amount_cents
        return all(total == 0 for total in totals.values())

    def reconcile(self, provider_received_by_ref: dict[str, int]) -> dict[str, int]:
        """Compara o livro com o extrato do provedor. Devolve só as referências com diferença
        (valor do extrato menos valor do livro)."""
        mine: dict[str, int] = {}
        for e in self._entries:
            if e.account == self.PROVIDER:
                mine[e.ref] = mine.get(e.ref, 0) - e.amount_cents
        diffs: dict[str, int] = {}
        for ref in set(mine) | set(provider_received_by_ref):
            diff = provider_received_by_ref.get(ref, 0) - mine.get(ref, 0)
            if diff != 0:
                diffs[ref] = diff
        return diffs
```

- [ ] **Step 4: Rodar e ver passar**

Run: `.venv/bin/pytest tests/domain/test_ledger.py -v`
Expected: todos passam (14 testes).

- [ ] **Step 5: Commit**

```bash
git add app/domain/ledger.py tests/domain/test_ledger.py && git commit -m "feat(domain): livro-caixa que só acrescenta, com estorno e conciliação" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 7: Etapas da corrida, fila e cancelamento

**Files:**
- Create: `server/app/domain/rides.py`
- Test: `server/tests/domain/test_rides.py`

**Interfaces:**
- Consumes: `RideConfig` e `PaymentMethod` (tarefa 2).
- Produces:
  - `RideState(str, Enum)`: `REQUESTED`, `SEARCHING`, `QUEUED`, `ACCEPTED`, `ARRIVED`, `IN_PROGRESS`, `COMPLETED`, `CANCELLED`, `NO_RIDER`.
  - `InvalidTransition(Exception)`.
  - `Ride(ride_id, passenger_id, price_cents, payment_method, pin, state=REQUESTED, rider_id=None, helmet_confirmed=False, pix_paid=False, pix_charge_created_at=None, searching_since=None, queued_since=None, en_route_since=None, arrived_at=None, end_payment_confirmed=False)` (dataclass mutável; instantes são `float` em segundos).
  - Funções (todas mudam a corrida no lugar): `start_search(ride, now)`, `accept(ride, rider_id, now, rider_busy: bool)`, `promote_from_queue(ride, now)`, `release_from_queue(ride, now) -> bool` (devolve se há estorno a fazer), `confirm_pix_paid(ride)`, `pix_window_expired(ride, now, cfg=RideConfig()) -> bool`, `cancel_unpaid_pix(ride)`, `mark_arrived(ride, now)`, `confirm_helmet(ride)`, `start_ride(ride, pin)`, `complete(ride)`, `cancel(ride, now, cfg=RideConfig()) -> int` (devolve a compensação em centavos), `arrival_wait_expired(ride, now, cfg=RideConfig()) -> bool`, `cancel_after_arrival_timeout(ride, now, cfg=RideConfig()) -> int`, `mark_no_rider(ride, now, cfg=RideConfig())`, `queue_wait_expired(ride, now, cfg=RideConfig()) -> bool`, `confirm_end_payment(ride)`.
  - `PassengerAccount(passenger_id, unpaid_cents=0)`; `can_request(acc) -> bool`; `report_non_payment(ride, acc)`; `settle_passenger_debt(acc, amount_cents)`.

- [ ] **Step 1: Escrever os testes que falham**

`server/tests/domain/test_rides.py`:

```python
import pytest

from app.domain.config import RideConfig
from app.domain.rides import (
    InvalidTransition,
    PassengerAccount,
    Ride,
    RideState,
    accept,
    arrival_wait_expired,
    can_request,
    cancel,
    cancel_after_arrival_timeout,
    cancel_unpaid_pix,
    complete,
    confirm_end_payment,
    confirm_helmet,
    confirm_pix_paid,
    mark_arrived,
    mark_no_rider,
    pix_window_expired,
    promote_from_queue,
    queue_wait_expired,
    release_from_queue,
    report_non_payment,
    settle_passenger_debt,
    start_ride,
    start_search,
)
from app.domain.types import PaymentMethod

CFG = RideConfig()


def make_ride(method: PaymentMethod = PaymentMethod.PIX) -> Ride:
    return Ride(ride_id="ride-1", passenger_id="p1", price_cents=700, payment_method=method, pin="4821")


def accepted_ride(method: PaymentMethod = PaymentMethod.PIX, now: float = 10.0) -> Ride:
    ride = make_ride(method)
    start_search(ride, 0)
    accept(ride, "rider-1", now, rider_busy=False)
    return ride


def arrived_ride(method: PaymentMethod = PaymentMethod.PIX) -> Ride:
    ride = accepted_ride(method)
    mark_arrived(ride, 100)
    return ride


def test_corrida_pix_do_pedido_ao_fim():
    ride = make_ride()
    start_search(ride, now=0)
    assert ride.state is RideState.SEARCHING
    accept(ride, "rider-1", now=10, rider_busy=False)
    assert ride.state is RideState.ACCEPTED
    assert ride.rider_id == "rider-1"
    assert ride.pix_charge_created_at == 10
    confirm_pix_paid(ride)
    mark_arrived(ride, now=100)
    confirm_helmet(ride)
    start_ride(ride, pin="4821")
    assert ride.state is RideState.IN_PROGRESS
    complete(ride)
    assert ride.state is RideState.COMPLETED


def test_corrida_em_dinheiro_nao_cria_cobranca_pix():
    ride = arrived_ride(PaymentMethod.CASH)
    assert ride.pix_charge_created_at is None
    confirm_helmet(ride)
    start_ride(ride, "4821")
    complete(ride)
    confirm_end_payment(ride)
    assert ride.end_payment_confirmed is True


def test_nao_inicia_sem_confirmar_o_capacete():
    ride = arrived_ride(PaymentMethod.CASH)
    with pytest.raises(InvalidTransition, match="capacete"):
        start_ride(ride, "4821")


def test_nao_inicia_com_codigo_errado():
    ride = arrived_ride(PaymentMethod.CASH)
    confirm_helmet(ride)
    with pytest.raises(ValueError, match="código"):
        start_ride(ride, "0000")
    assert ride.state is RideState.ARRIVED


def test_nao_inicia_corrida_pix_sem_pagamento():
    ride = arrived_ride(PaymentMethod.PIX)
    confirm_helmet(ride)
    with pytest.raises(InvalidTransition, match="Pix"):
        start_ride(ride, "4821")


def test_nao_pula_etapas():
    ride = accepted_ride(PaymentMethod.CASH)
    with pytest.raises(InvalidTransition):
        start_ride(ride, "4821")
    with pytest.raises(InvalidTransition):
        complete(ride)
    with pytest.raises(InvalidTransition):
        confirm_helmet(ride)


def test_confirmar_pix_em_corrida_de_dinheiro_e_recusado():
    ride = accepted_ride(PaymentMethod.CASH)
    with pytest.raises(InvalidTransition):
        confirm_pix_paid(ride)


def test_corrida_na_fila_espera_e_depois_vira_a_caminho():
    ride = make_ride()
    start_search(ride, 0)
    accept(ride, "rider-1", now=10, rider_busy=True)
    assert ride.state is RideState.QUEUED
    assert ride.queued_since == 10
    assert ride.pix_charge_created_at == 10
    promote_from_queue(ride, now=200)
    assert ride.state is RideState.ACCEPTED
    assert ride.en_route_since == 200


def test_fila_vence_depois_de_480_segundos():
    ride = make_ride()
    start_search(ride, 0)
    accept(ride, "rider-1", now=10, rider_busy=True)
    assert queue_wait_expired(ride, 10 + 479, CFG) is False
    assert queue_wait_expired(ride, 10 + 480, CFG) is True


def test_fila_vencida_volta_para_a_busca_sem_estorno_se_nao_pagou():
    ride = make_ride()
    start_search(ride, 0)
    accept(ride, "rider-1", now=10, rider_busy=True)
    assert release_from_queue(ride, now=500) is False
    assert ride.state is RideState.SEARCHING
    assert ride.rider_id is None
    assert ride.pix_charge_created_at is None
    assert ride.searching_since == 500


def test_fila_vencida_com_pix_pago_pede_estorno():
    # Review Focus 5: o passageiro ja pagou o motoqueiro A; ao trocar de moto o dinheiro tem que voltar.
    ride = make_ride()
    start_search(ride, 0)
    accept(ride, "rider-1", now=10, rider_busy=True)
    confirm_pix_paid(ride)
    assert release_from_queue(ride, now=500) is True
    assert ride.pix_paid is False
    assert ride.state is RideState.SEARCHING


def test_janela_de_120_segundos_para_pagar_o_pix():
    ride = accepted_ride(PaymentMethod.PIX, now=10)
    assert pix_window_expired(ride, 10 + 119, CFG) is False
    assert pix_window_expired(ride, 10 + 120, CFG) is True
    confirm_pix_paid(ride)
    assert pix_window_expired(ride, 10 + 500, CFG) is False


def test_janela_do_pix_nao_vale_para_dinheiro():
    ride = accepted_ride(PaymentMethod.CASH)
    assert pix_window_expired(ride, 10_000, CFG) is False


def test_cancelar_por_pix_nao_pago():
    ride = accepted_ride(PaymentMethod.PIX)
    cancel_unpaid_pix(ride)
    assert ride.state is RideState.CANCELLED


def test_cancelar_durante_a_procura_e_gratis():
    ride = make_ride()
    start_search(ride, 0)
    assert cancel(ride, now=5, cfg=CFG) == 0
    assert ride.state is RideState.CANCELLED


def test_cancelar_no_limite_de_60_segundos_ainda_e_gratis():
    # Review Focus 3
    ride = accepted_ride(now=10)
    assert cancel(ride, now=70, cfg=CFG) == 0


def test_cancelar_depois_de_60_segundos_paga_compensacao():
    ride = accepted_ride(now=10)
    assert cancel(ride, now=71, cfg=CFG) == 200
    assert ride.state is RideState.CANCELLED


def test_cancelar_na_fila_e_sempre_gratis():
    ride = make_ride()
    start_search(ride, 0)
    accept(ride, "rider-1", now=10, rider_busy=True)
    assert cancel(ride, now=10_000, cfg=CFG) == 0


def test_nao_cancela_corrida_em_andamento():
    ride = arrived_ride(PaymentMethod.CASH)
    confirm_helmet(ride)
    start_ride(ride, "4821")
    with pytest.raises(InvalidTransition):
        cancel(ride, now=500, cfg=CFG)


def test_espera_maxima_na_chegada():
    ride = arrived_ride(PaymentMethod.CASH)  # chegou em t=100
    assert arrival_wait_expired(ride, 399, CFG) is False
    assert arrival_wait_expired(ride, 400, CFG) is True
    with pytest.raises(InvalidTransition):
        cancel_after_arrival_timeout(ride, 399, CFG)
    assert cancel_after_arrival_timeout(ride, 400, CFG) == 200
    assert ride.state is RideState.CANCELLED


def test_desiste_da_procura_em_120_segundos():
    ride = make_ride()
    start_search(ride, 0)
    with pytest.raises(InvalidTransition):
        mark_no_rider(ride, 119, CFG)
    mark_no_rider(ride, 120, CFG)
    assert ride.state is RideState.NO_RIDER


def test_passageiro_que_sai_sem_pagar_fica_bloqueado_ate_pagar():
    ride = arrived_ride(PaymentMethod.CASH)
    confirm_helmet(ride)
    start_ride(ride, "4821")
    complete(ride)
    acc = PassengerAccount("p1")
    assert can_request(acc) is True
    report_non_payment(ride, acc)
    assert acc.unpaid_cents == 700
    assert can_request(acc) is False
    settle_passenger_debt(acc, 700)
    assert can_request(acc) is True


def test_nao_da_para_denunciar_calote_de_corrida_ja_paga():
    ride = arrived_ride(PaymentMethod.CASH)
    confirm_helmet(ride)
    start_ride(ride, "4821")
    complete(ride)
    confirm_end_payment(ride)
    with pytest.raises(InvalidTransition):
        report_non_payment(ride, PassengerAccount("p1"))


def test_pagar_mais_que_a_divida_do_passageiro_e_recusado():
    with pytest.raises(ValueError):
        settle_passenger_debt(PassengerAccount("p1", unpaid_cents=100), 200)
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `.venv/bin/pytest tests/domain/test_rides.py -v`
Expected: `ModuleNotFoundError: No module named 'app.domain.rides'`.

- [ ] **Step 3: Implementar**

`server/app/domain/rides.py`:

```python
"""Etapas da corrida, fila e cancelamento (spec, seção 5). Instantes em segundos (float)."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from app.domain.config import RideConfig
from app.domain.types import PaymentMethod

_DEFAULT = RideConfig()


class RideState(str, Enum):
    REQUESTED = "requested"
    SEARCHING = "searching"
    QUEUED = "queued"
    ACCEPTED = "accepted"
    ARRIVED = "arrived"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    NO_RIDER = "no_rider"


class InvalidTransition(Exception):
    """A ação não é permitida no estado atual da corrida."""


@dataclass
class Ride:
    ride_id: str
    passenger_id: str
    price_cents: int
    payment_method: PaymentMethod
    pin: str
    state: RideState = RideState.REQUESTED
    rider_id: str | None = None
    helmet_confirmed: bool = False
    pix_paid: bool = False
    pix_charge_created_at: float | None = None
    searching_since: float | None = None
    queued_since: float | None = None
    en_route_since: float | None = None
    arrived_at: float | None = None
    end_payment_confirmed: bool = False


def _require(ride: Ride, *states: RideState) -> None:
    if ride.state not in states:
        esperados = ", ".join(s.value for s in states)
        raise InvalidTransition(
            f"corrida {ride.ride_id}: estado {ride.state.value}, esperado {esperados}"
        )


def start_search(ride: Ride, now: float) -> None:
    _require(ride, RideState.REQUESTED)
    ride.state = RideState.SEARCHING
    ride.searching_since = now


def accept(ride: Ride, rider_id: str, now: float, rider_busy: bool) -> None:
    """O motoqueiro aceitou. Se ele ainda está em outra corrida, esta fica na fila."""
    _require(ride, RideState.SEARCHING)
    ride.rider_id = rider_id
    if ride.payment_method is PaymentMethod.PIX:
        ride.pix_charge_created_at = now
    if rider_busy:
        ride.state = RideState.QUEUED
        ride.queued_since = now
    else:
        ride.state = RideState.ACCEPTED
        ride.en_route_since = now


def promote_from_queue(ride: Ride, now: float) -> None:
    _require(ride, RideState.QUEUED)
    ride.state = RideState.ACCEPTED
    ride.en_route_since = now


def release_from_queue(ride: Ride, now: float) -> bool:
    """Tira a corrida da fila e volta para a busca. Devolve True se há Pix pago para estornar."""
    _require(ride, RideState.QUEUED)
    refund_needed = ride.pix_paid
    ride.state = RideState.SEARCHING
    ride.rider_id = None
    ride.pix_paid = False
    ride.pix_charge_created_at = None
    ride.queued_since = None
    ride.searching_since = now
    return refund_needed


def confirm_pix_paid(ride: Ride) -> None:
    _require(ride, RideState.QUEUED, RideState.ACCEPTED, RideState.ARRIVED)
    if ride.payment_method is not PaymentMethod.PIX:
        raise InvalidTransition("esta corrida não é paga por Pix")
    ride.pix_paid = True


def pix_window_expired(ride: Ride, now: float, cfg: RideConfig = _DEFAULT) -> bool:
    if ride.payment_method is not PaymentMethod.PIX or ride.pix_paid:
        return False
    if ride.state not in (RideState.QUEUED, RideState.ACCEPTED, RideState.ARRIVED):
        return False
    if ride.pix_charge_created_at is None:
        return False
    return now - ride.pix_charge_created_at >= cfg.pix_window_s


def cancel_unpaid_pix(ride: Ride) -> None:
    """Cancela porque o passageiro não pagou o Pix a tempo. Sem compensação."""
    _require(ride, RideState.QUEUED, RideState.ACCEPTED, RideState.ARRIVED)
    ride.state = RideState.CANCELLED


def mark_arrived(ride: Ride, now: float) -> None:
    _require(ride, RideState.ACCEPTED)
    ride.state = RideState.ARRIVED
    ride.arrived_at = now


def confirm_helmet(ride: Ride) -> None:
    _require(ride, RideState.ARRIVED)
    ride.helmet_confirmed = True


def start_ride(ride: Ride, pin: str) -> None:
    _require(ride, RideState.ARRIVED)
    if not ride.helmet_confirmed:
        raise InvalidTransition("o capacete extra ainda não foi confirmado")
    if ride.payment_method is PaymentMethod.PIX and not ride.pix_paid:
        raise InvalidTransition("o Pix ainda não foi pago")
    if pin != ride.pin:
        raise ValueError("código errado")
    ride.state = RideState.IN_PROGRESS


def complete(ride: Ride) -> None:
    _require(ride, RideState.IN_PROGRESS)
    ride.state = RideState.COMPLETED


def cancel(ride: Ride, now: float, cfg: RideConfig = _DEFAULT) -> int:
    """Cancelamento pelo passageiro. Devolve a compensação ao motoqueiro, em centavos."""
    _require(
        ride,
        RideState.REQUESTED,
        RideState.SEARCHING,
        RideState.QUEUED,
        RideState.ACCEPTED,
        RideState.ARRIVED,
    )
    compensation = 0
    if ride.state in (RideState.ACCEPTED, RideState.ARRIVED):
        if ride.en_route_since is not None and now - ride.en_route_since > cfg.free_cancel_after_accept_s:
            compensation = cfg.cancel_compensation_cents
    ride.state = RideState.CANCELLED
    return compensation


def arrival_wait_expired(ride: Ride, now: float, cfg: RideConfig = _DEFAULT) -> bool:
    if ride.state is not RideState.ARRIVED or ride.arrived_at is None:
        return False
    return now - ride.arrived_at >= cfg.max_wait_at_arrival_s


def cancel_after_arrival_timeout(ride: Ride, now: float, cfg: RideConfig = _DEFAULT) -> int:
    if not arrival_wait_expired(ride, now, cfg):
        raise InvalidTransition("o tempo de espera na chegada ainda não acabou")
    ride.state = RideState.CANCELLED
    return cfg.cancel_compensation_cents


def mark_no_rider(ride: Ride, now: float, cfg: RideConfig = _DEFAULT) -> None:
    _require(ride, RideState.SEARCHING)
    if ride.searching_since is None or now - ride.searching_since < cfg.search_give_up_s:
        raise InvalidTransition("ainda está dentro do tempo de procura")
    ride.state = RideState.NO_RIDER


def queue_wait_expired(ride: Ride, now: float, cfg: RideConfig = _DEFAULT) -> bool:
    if ride.state is not RideState.QUEUED or ride.queued_since is None:
        return False
    return now - ride.queued_since >= cfg.queue_max_wait_s


def confirm_end_payment(ride: Ride) -> None:
    """O motoqueiro apertou "confirmar pagamento" ao fim de uma corrida paga no final."""
    _require(ride, RideState.COMPLETED)
    if ride.payment_method is not PaymentMethod.CASH:
        raise InvalidTransition("esta corrida foi paga por Pix antes de começar")
    ride.end_payment_confirmed = True


@dataclass
class PassengerAccount:
    passenger_id: str
    unpaid_cents: int = 0


def can_request(acc: PassengerAccount) -> bool:
    return acc.unpaid_cents == 0


def report_non_payment(ride: Ride, acc: PassengerAccount) -> None:
    _require(ride, RideState.COMPLETED)
    if ride.payment_method is not PaymentMethod.CASH or ride.end_payment_confirmed:
        raise InvalidTransition("não há pagamento pendente nesta corrida")
    acc.unpaid_cents += ride.price_cents


def settle_passenger_debt(acc: PassengerAccount, amount_cents: int) -> None:
    if amount_cents <= 0 or amount_cents > acc.unpaid_cents:
        raise ValueError("valor inválido para quitar a dívida do passageiro")
    acc.unpaid_cents -= amount_cents
```

- [ ] **Step 4: Rodar e ver passar**

Run: `.venv/bin/pytest tests/domain/test_rides.py -v`
Expected: todos passam (24 testes).

- [ ] **Step 5: Commit**

```bash
git add app/domain/rides.py tests/domain/test_rides.py && git commit -m "feat(domain): etapas da corrida com fila, Pix, cancelamento e calote" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 8: Escolha da moto e reserva

**Files:**
- Create: `server/app/adapters/fake_maps.py`
- Create: `server/app/domain/dispatch.py`
- Test: `server/tests/domain/test_dispatch.py`

**Interfaces:**
- Consumes: `GeoPoint`, `haversine_m` (tarefa 2), `DispatchConfig` (tarefa 2).
- Produces:
  - `EtaProvider` (Protocol): `eta_seconds(origin: GeoPoint, destination: GeoPoint) -> int`.
  - `StraightLineEta(speed_mps: float = 8.0)` em `app/adapters/fake_maps.py`, que implementa `EtaProvider`.
  - `RiderStatus(rider_id, position, online=True, active_ride_id=None, queued_ride_id=None, seconds_to_finish=None, finish_point=None)` (dataclass mutável).
  - `Candidate(rider_id: str, eta_seconds: int, will_queue: bool)` (congelada).
  - `is_finishing(r: RiderStatus, cfg=DispatchConfig()) -> bool`, `is_eligible(r, cfg=DispatchConfig()) -> bool`.
  - `rank_candidates(riders: Sequence[RiderStatus], pickup: GeoPoint, eta: EtaProvider, cfg=DispatchConfig()) -> list[Candidate]`.
  - `next_offer(candidates: list[Candidate], declined: set[str]) -> Candidate | None`.
  - `ReservationBook` com `reserve(rider_id: str, ride_id: str) -> bool` e `release(rider_id: str, ride_id: str) -> None`.

- [ ] **Step 1: Escrever os testes que falham**

`server/tests/domain/test_dispatch.py`:

```python
import threading

from app.adapters.fake_maps import StraightLineEta
from app.domain.config import DispatchConfig
from app.domain.dispatch import (
    Candidate,
    ReservationBook,
    RiderStatus,
    is_eligible,
    is_finishing,
    next_offer,
    rank_candidates,
)
from tests.helpers import ORIGIN, pt

ETA = StraightLineEta(speed_mps=8.0)
CFG = DispatchConfig()


class CountingEta:
    def __init__(self, inner):
        self.inner = inner
        self.calls = 0

    def eta_seconds(self, origin, destination):
        self.calls += 1
        return self.inner.eta_seconds(origin, destination)


def free(rider_id: str, north_m: float) -> RiderStatus:
    return RiderStatus(rider_id, pt(north_m, 0))


def test_ordena_pelo_tempo_e_calcula_rota_so_dos_3_mais_proximos():
    riders = [free("r4", 800), free("r2", 400), free("r1", 200), free("r3", 600)]
    eta = CountingEta(ETA)
    result = rank_candidates(riders, ORIGIN, eta, CFG)
    assert [c.rider_id for c in result] == ["r1", "r2", "r3"]
    assert eta.calls == 3
    assert result[0] == Candidate("r1", ETA.eta_seconds(pt(200, 0), ORIGIN), False)


def test_moto_offline_nao_entra():
    riders = [RiderStatus("off", pt(100, 0), online=False), free("r1", 300)]
    assert [c.rider_id for c in rank_candidates(riders, ORIGIN, ETA, CFG)] == ["r1"]


def test_moto_em_corrida_longe_do_fim_nao_entra():
    busy = RiderStatus(
        "busy", pt(200, 0), active_ride_id="x", seconds_to_finish=600, finish_point=pt(5000, 0)
    )
    assert is_finishing(busy, CFG) is False
    assert is_eligible(busy, CFG) is False
    assert rank_candidates([busy], ORIGIN, ETA, CFG) == []


def test_moto_terminando_entra_na_fila_com_tempo_somado():
    finishing = RiderStatus(
        "fin", pt(100, 0), active_ride_id="x", seconds_to_finish=60, finish_point=pt(300, 0)
    )
    assert is_finishing(finishing, CFG) is True
    result = rank_candidates([finishing], ORIGIN, ETA, CFG)
    assert result == [Candidate("fin", 60 + ETA.eta_seconds(pt(300, 0), ORIGIN), True)]


def test_moto_perto_do_destino_conta_como_terminando_mesmo_sem_tempo():
    near_end = RiderStatus(
        "near", pt(4800, 0), active_ride_id="x", seconds_to_finish=None, finish_point=pt(5000, 0)
    )
    assert is_finishing(near_end, CFG) is True


def test_moto_que_ja_tem_corrida_na_fila_nao_entra():
    queued = RiderStatus(
        "q", pt(100, 0), active_ride_id="x", queued_ride_id="y", seconds_to_finish=30, finish_point=pt(200, 0)
    )
    assert is_eligible(queued, CFG) is False


def test_moto_terminando_longe_do_passageiro_perde_para_moto_livre():
    finishing = RiderStatus(
        "fin", pt(100, 0), active_ride_id="x", seconds_to_finish=100, finish_point=pt(100, 0)
    )
    result = rank_candidates([finishing, free("livre", 400)], ORIGIN, ETA, CFG)
    assert [c.rider_id for c in result] == ["livre", "fin"]


def test_proxima_oferta_pula_quem_recusou():
    candidates = [Candidate("a", 10, False), Candidate("b", 20, False), Candidate("c", 30, False)]
    assert next_offer(candidates, set()).rider_id == "a"
    assert next_offer(candidates, {"a"}).rider_id == "b"
    assert next_offer(candidates, {"a", "b", "c"}) is None


def test_reserva_e_idempotente_para_a_mesma_corrida_e_recusa_outra():
    book = ReservationBook()
    assert book.reserve("rider-1", "ride-1") is True
    assert book.reserve("rider-1", "ride-1") is True
    assert book.reserve("rider-1", "ride-2") is False
    book.release("rider-1", "ride-2")  # corrida errada: não libera
    assert book.reserve("rider-1", "ride-2") is False
    book.release("rider-1", "ride-1")
    assert book.reserve("rider-1", "ride-2") is True


def test_reserva_com_pedidos_ao_mesmo_tempo_so_um_ganha():
    book = ReservationBook()
    results: list[bool] = []
    lock = threading.Lock()

    def tentar(ride_id: str) -> None:
        ok = book.reserve("rider-1", ride_id)
        with lock:
            results.append(ok)

    threads = [threading.Thread(target=tentar, args=(f"ride-{i}",)) for i in range(50)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sum(results) == 1
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `.venv/bin/pytest tests/domain/test_dispatch.py -v`
Expected: `ModuleNotFoundError: No module named 'app.adapters.fake_maps'`.

- [ ] **Step 3: Implementar**

`server/app/adapters/fake_maps.py`:

```python
"""Tempo de chegada falso: linha reta a velocidade constante. Para testes e para o simulador."""
from __future__ import annotations

from app.domain.geo import GeoPoint, haversine_m


class StraightLineEta:
    def __init__(self, speed_mps: float = 8.0) -> None:
        # 8 m/s ≈ 29 km/h, uma velocidade plausível para moto na cidade.
        self.speed_mps = speed_mps

    def eta_seconds(self, origin: GeoPoint, destination: GeoPoint) -> int:
        return int(haversine_m(origin, destination) / self.speed_mps)
```

`server/app/domain/dispatch.py`:

```python
"""Escolha da moto e reserva (spec, seção 5). Sem rede: o tempo de rota vem de um EtaProvider."""
from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Protocol, Sequence

from app.domain.config import DispatchConfig
from app.domain.geo import GeoPoint, haversine_m

_DEFAULT = DispatchConfig()


class EtaProvider(Protocol):
    def eta_seconds(self, origin: GeoPoint, destination: GeoPoint) -> int: ...


@dataclass
class RiderStatus:
    rider_id: str
    position: GeoPoint
    online: bool = True
    active_ride_id: str | None = None
    queued_ride_id: str | None = None
    seconds_to_finish: int | None = None
    finish_point: GeoPoint | None = None


@dataclass(frozen=True)
class Candidate:
    rider_id: str
    eta_seconds: int
    will_queue: bool


def is_finishing(r: RiderStatus, cfg: DispatchConfig = _DEFAULT) -> bool:
    """A moto tem corrida ativa, mas está acabando: perto do tempo ou perto do destino."""
    if r.active_ride_id is None:
        return False
    if r.seconds_to_finish is not None and r.seconds_to_finish <= cfg.finishing_max_s:
        return True
    if r.finish_point is not None and haversine_m(r.position, r.finish_point) <= cfg.finishing_max_m:
        return True
    return False


def is_eligible(r: RiderStatus, cfg: DispatchConfig = _DEFAULT) -> bool:
    if not r.online or r.queued_ride_id is not None:
        return False
    if r.active_ride_id is None:
        return True
    return is_finishing(r, cfg)


def _origin(r: RiderStatus) -> GeoPoint:
    """De onde a moto sai para buscar o passageiro: do fim da corrida atual, se houver."""
    if r.active_ride_id is not None and r.finish_point is not None:
        return r.finish_point
    return r.position


def rank_candidates(
    riders: Sequence[RiderStatus],
    pickup: GeoPoint,
    eta: EtaProvider,
    cfg: DispatchConfig = _DEFAULT,
) -> list[Candidate]:
    """Motos elegíveis, ordenadas pelo tempo total até o passageiro.

    A rota só é calculada para as `max_candidates_routed` motos mais próximas em linha reta
    (economiza o custo de mapas).
    """
    eligible = [r for r in riders if is_eligible(r, cfg)]
    eligible.sort(key=lambda r: haversine_m(_origin(r), pickup))
    candidates: list[Candidate] = []
    for r in eligible[: cfg.max_candidates_routed]:
        busy = r.active_ride_id is not None
        wait = (r.seconds_to_finish or 0) if busy else 0
        candidates.append(Candidate(r.rider_id, wait + eta.eta_seconds(_origin(r), pickup), busy))
    candidates.sort(key=lambda c: c.eta_seconds)
    return candidates


def next_offer(candidates: list[Candidate], declined: set[str]) -> Candidate | None:
    for c in candidates:
        if c.rider_id not in declined:
            return c
    return None


class ReservationBook:
    """Garante que uma moto recebe a oferta de um pedido só de cada vez (nunca dois ao mesmo tempo)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._by_rider: dict[str, str] = {}

    def reserve(self, rider_id: str, ride_id: str) -> bool:
        with self._lock:
            current = self._by_rider.get(rider_id)
            if current is not None and current != ride_id:
                return False
            self._by_rider[rider_id] = ride_id
            return True

    def release(self, rider_id: str, ride_id: str) -> None:
        with self._lock:
            if self._by_rider.get(rider_id) == ride_id:
                del self._by_rider[rider_id]
```

- [ ] **Step 4: Rodar e ver passar**

Run: `.venv/bin/pytest tests/domain/test_dispatch.py -v`
Expected: todos passam (10 testes).

- [ ] **Step 5: Commit**

```bash
git add app/adapters/fake_maps.py app/domain/dispatch.py tests/domain/test_dispatch.py && git commit -m "feat(domain): escolha da moto, corrida na fila e reserva" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 9: Alertas de segurança

**Files:**
- Create: `server/app/domain/safety.py`
- Test: `server/tests/domain/test_safety.py`

**Interfaces:**
- Consumes: `GeoPoint`, `haversine_m`, `distance_to_route_m` (tarefa 2), `SafetyConfig` (tarefa 2).
- Produces:
  - `AlertType(str, Enum)`: `STOPPED = "stopped"`, `OFF_ROUTE = "off_route"`.
  - `PositionSample(point: GeoPoint, t: float)` (congelada, `t` em segundos).
  - `speed_kmh(a: PositionSample, b: PositionSample) -> float`.
  - `clean_samples(samples: list[PositionSample], cfg=SafetyConfig()) -> tuple[list[PositionSample], int]` (amostras aceitas e quantidade de saltos rejeitados).
  - `is_stopped_too_long(samples, cfg=SafetyConfig()) -> bool`; `is_off_route(samples, route, cfg=SafetyConfig()) -> bool`.
  - `SafetyResult(alert: AlertType | None, suspected_mock_location: bool)` (congelada).
  - `evaluate(samples, route, cfg=SafetyConfig()) -> SafetyResult`. Vale só para corridas **em andamento**.

- [ ] **Step 1: Escrever os testes que falham**

`server/tests/domain/test_safety.py`:

```python
from app.domain.safety import (
    AlertType,
    PositionSample,
    clean_samples,
    evaluate,
    speed_kmh,
)
from tests.helpers import pt

ROUTE = [pt(0, 0), pt(5000, 0)]  # reta para o norte


def walk(n: int, step_m: float = 100.0, dt: float = 10.0) -> list[PositionSample]:
    """`n` amostras andando pela rota para o norte: 100 m a cada 10 s = 36 km/h."""
    return [PositionSample(pt(i * step_m, 0), i * dt) for i in range(n)]


def test_velocidade_em_kmh():
    a, b = PositionSample(pt(0, 0), 0), PositionSample(pt(100, 0), 10)
    assert round(speed_kmh(a, b)) == 36


def test_andando_pela_rota_nao_gera_alerta():
    result = evaluate(walk(30), ROUTE)
    assert result.alert is None
    assert result.suspected_mock_location is False


def test_parada_por_mais_de_3_minutos_gera_alerta():
    samples = walk(10) + [PositionSample(pt(900, 0), 100 + i * 10) for i in range(22)]
    assert evaluate(samples, ROUTE).alert is AlertType.STOPPED


def test_parada_curta_nao_gera_alerta():
    samples = walk(10) + [PositionSample(pt(900, 0), 100 + i * 10) for i in range(10)]
    assert evaluate(samples, ROUTE).alert is None


def test_pouco_historico_nao_gera_alerta_de_parada():
    assert evaluate([PositionSample(pt(0, 0), 0)], ROUTE).alert is None


def test_fora_da_rota_exige_tres_amostras_seguidas():
    base = walk(10)  # termina em t=90, em (900, 0)
    off1 = PositionSample(pt(900, 400), 110)
    off2 = PositionSample(pt(900, 800), 130)
    off3 = PositionSample(pt(900, 1200), 150)
    assert evaluate(base + [off1, off2], ROUTE).alert is None
    assert evaluate(base + [off1, off2, off3], ROUTE).alert is AlertType.OFF_ROUTE


def test_um_salto_de_gps_e_ignorado():
    samples = walk(10) + [PositionSample(pt(900, 50_000), 100), PositionSample(pt(1000, 0), 110)]
    good, jumps = clean_samples(samples)
    assert jumps == 1
    assert good[-1].t == 110
    result = evaluate(samples, ROUTE)
    assert result.alert is None
    assert result.suspected_mock_location is False


def test_dois_saltos_marcam_suspeita_de_localizacao_falsa():
    samples = (
        walk(5)
        + [PositionSample(pt(400, 50_000), 50), PositionSample(pt(500, 0), 60)]
        + [PositionSample(pt(500, -50_000), 70), PositionSample(pt(600, 0), 80)]
    )
    result = evaluate(samples, ROUTE)
    assert result.suspected_mock_location is True
    assert result.alert is None


def test_retomada_de_sinal_em_outro_lugar_volta_a_ser_aceita():
    # Review Focus 4: depois de 3 saltos seguidos o sistema aceita a nova posição.
    samples = walk(3) + [PositionSample(pt(200, 30_000), 30 + i * 10) for i in range(4)]
    good, jumps = clean_samples(samples)
    assert jumps == 3
    assert len(good) == 5
    assert good[-1].t == 60


def test_primeira_amostra_errada_nao_trava_o_sistema():
    # Review Focus 4: a primeira amostra veio de longe; as seguintes, corretas, não podem ser jogadas fora para sempre.
    samples = [PositionSample(pt(0, 50_000), 0)] + [PositionSample(pt(0, 0), 10 * i) for i in range(1, 7)]
    good, _ = clean_samples(samples)
    assert good[-1].t == 60
    assert evaluate(samples, ROUTE).alert is None


def test_amostras_fora_de_ordem_sao_descartadas():
    good, jumps = clean_samples([PositionSample(pt(0, 0), 10), PositionSample(pt(10, 0), 5)])
    assert [s.t for s in good] == [10]
    assert jumps == 0
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `.venv/bin/pytest tests/domain/test_safety.py -v`
Expected: `ModuleNotFoundError: No module named 'app.domain.safety'`.

- [ ] **Step 3: Implementar**

`server/app/domain/safety.py`:

```python
"""Alertas de segurança durante a corrida (spec, seção 9). Só vale para corridas em andamento."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from app.domain.config import SafetyConfig
from app.domain.geo import GeoPoint, distance_to_route_m, haversine_m

_DEFAULT = SafetyConfig()


class AlertType(str, Enum):
    STOPPED = "stopped"
    OFF_ROUTE = "off_route"


@dataclass(frozen=True)
class PositionSample:
    point: GeoPoint
    t: float  # segundos


@dataclass(frozen=True)
class SafetyResult:
    alert: AlertType | None
    suspected_mock_location: bool


def speed_kmh(a: PositionSample, b: PositionSample) -> float:
    dt = b.t - a.t
    if dt <= 0:
        raise ValueError("o tempo precisa avançar entre as amostras")
    return haversine_m(a.point, b.point) / dt * 3.6


def clean_samples(
    samples: list[PositionSample], cfg: SafetyConfig = _DEFAULT
) -> tuple[list[PositionSample], int]:
    """Descarta amostras fora de ordem e saltos impossíveis. Devolve (aceitas, saltos rejeitados).

    Depois de `reanchor_after_rejects` saltos seguidos, aceita a nova posição: o sinal pode ter
    voltado em outro lugar, ou a primeira amostra pode ter sido a errada.
    """
    good: list[PositionSample] = []
    jumps = 0
    consecutive_rejects = 0
    for s in samples:
        if not good:
            good.append(s)
            continue
        last = good[-1]
        if s.t <= last.t:
            continue
        if speed_kmh(last, s) > cfg.max_plausible_speed_kmh:
            jumps += 1
            consecutive_rejects += 1
            if consecutive_rejects >= cfg.reanchor_after_rejects:
                good.append(s)
                consecutive_rejects = 0
            continue
        consecutive_rejects = 0
        good.append(s)
    return good, jumps


def is_stopped_too_long(samples: list[PositionSample], cfg: SafetyConfig = _DEFAULT) -> bool:
    """A moto ficou dentro de `stopped_radius_m` do último ponto por pelo menos `stopped_after_s`."""
    if not samples:
        return False
    last = samples[-1]
    cutoff = last.t - cfg.stopped_after_s
    older = [s for s in samples if s.t <= cutoff]
    if not older:
        return False
    anchor = older[-1]
    recent = [s for s in samples if s.t >= anchor.t]
    return all(haversine_m(s.point, last.point) <= cfg.stopped_radius_m for s in recent)


def is_off_route(
    samples: list[PositionSample], route: list[GeoPoint], cfg: SafetyConfig = _DEFAULT
) -> bool:
    """Confirma antes de avisar: as últimas amostras, todas, estão longe da rota."""
    if len(samples) < cfg.off_route_confirmations:
        return False
    tail = samples[-cfg.off_route_confirmations :]
    return all(distance_to_route_m(s.point, route) > cfg.off_route_m for s in tail)


def evaluate(
    samples: list[PositionSample], route: list[GeoPoint], cfg: SafetyConfig = _DEFAULT
) -> SafetyResult:
    good, jumps = clean_samples(samples, cfg)
    suspected = jumps >= cfg.mock_location_jumps
    if is_stopped_too_long(good, cfg):
        return SafetyResult(AlertType.STOPPED, suspected)
    if is_off_route(good, route, cfg):
        return SafetyResult(AlertType.OFF_ROUTE, suspected)
    return SafetyResult(None, suspected)
```

- [ ] **Step 4: Rodar e ver passar**

Run: `.venv/bin/pytest tests/domain/test_safety.py -v`
Expected: todos passam (11 testes).

- [ ] **Step 5: Commit**

```bash
git add app/domain/safety.py tests/domain/test_safety.py && git commit -m "feat(domain): alertas de parada, fora da rota e localização suspeita" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 10: Cenário de ponta a ponta e fechamento do plano

**Files:**
- Test: `server/tests/test_cenarios.py`

**Interfaces:**
- Consumes: tudo das tarefas 2 a 9. Este teste prova que os nomes e tipos combinam entre os módulos.

- [ ] **Step 1: Escrever o teste de cenários**

`server/tests/test_cenarios.py`:

```python
from app.adapters.fake_maps import StraightLineEta
from app.adapters.fake_payments import FakePaymentProvider
from app.domain.dispatch import RiderStatus, rank_candidates
from app.domain.fees import (
    RiderAccount,
    can_receive_offers,
    fee_for_ride,
    register_completed_ride,
)
from app.domain.ledger import Ledger
from app.domain.payments import ProcessedEvents, compute_split, settle_pix_ride
from app.domain.pricing import final_price_cents, smooth_factor, target_factor
from app.domain.rides import (
    Ride,
    RideState,
    accept,
    complete,
    confirm_helmet,
    confirm_pix_paid,
    mark_arrived,
    start_ride,
    start_search,
)
from app.domain.types import PaymentMethod
from tests.helpers import ORIGIN, pt


def test_corrida_pix_completa_fecha_as_contas():
    # preço pelo movimento do momento
    factor = smooth_factor(1.0, target_factor(pending_requests=3, free_riders=3))
    price = final_price_cents(distance_m=2000, factor=factor)
    assert price == 600
    fee = fee_for_ride(1)
    assert fee == 100

    # escolha da moto
    riders = [RiderStatus("rider-1", pt(200, 0)), RiderStatus("rider-2", pt(900, 0))]
    best = rank_candidates(riders, ORIGIN, StraightLineEta())[0]
    assert best.rider_id == "rider-1"
    assert best.will_queue is False

    # corrida: aceita, Pix pago, chega, capacete, código, termina
    acc = RiderAccount("rider-1")
    assert can_receive_offers(acc)
    ride = Ride("ride-1", "p1", price, PaymentMethod.PIX, pin="4821")
    start_search(ride, 0)
    accept(ride, best.rider_id, now=10, rider_busy=False)

    provider = FakePaymentProvider()
    split = settle_pix_ride(acc, price, fee)
    charge = provider.create_pix_charge(ride.ride_id, best.rider_id, price, split)
    event = provider.mark_paid(charge.charge_id)
    events = ProcessedEvents()
    assert events.first_time(event["event_id"]) is True
    confirm_pix_paid(ride)

    ledger = Ledger()
    ledger.post_ride_payment(ride.ride_id, best.rider_id, price, split)

    mark_arrived(ride, 100)
    confirm_helmet(ride)
    start_ride(ride, "4821")
    complete(ride)
    register_completed_ride(acc, PaymentMethod.PIX, fee)

    assert ride.state is RideState.COMPLETED
    assert acc.completed_rides == 1
    assert ledger.balance("rider:rider-1") == 500
    assert ledger.balance(Ledger.COMPANY) == 100
    assert ledger.balance(Ledger.PROVIDER) == -600
    assert ledger.is_balanced() is True
    assert ledger.reconcile({"ride:ride-1": 600}) == {}

    # o provedor repete o aviso: nada é contado duas vezes
    assert events.first_time(event["event_id"]) is False


def test_corrida_em_dinheiro_gera_divida_que_a_proxima_corrida_pix_abate():
    acc = RiderAccount("rider-1")
    fee = fee_for_ride(1)
    register_completed_ride(acc, PaymentMethod.CASH, fee)
    assert acc.cash_debt_cents == 100

    price = 700
    split = settle_pix_ride(acc, price, fee_for_ride(2))
    assert split.debt_paid_cents == 100
    assert split.rider_cents == 500
    assert split.company_cents == 200
    assert acc.cash_debt_cents == 0

    ledger = Ledger()
    ledger.post_ride_payment("ride-2", "rider-1", price, split)
    assert ledger.is_balanced() is True
    assert compute_split(price, 100, 0).rider_cents == 600
```

- [ ] **Step 2: Rodar a suíte inteira**

Run: `.venv/bin/pytest -q`
Expected: todos os testes passam, sem falhas e sem avisos de teste ignorado. Anotar o total de testes no resumo final do plano.

- [ ] **Step 3: Conferir que as faixas padrão cumprem o piso de lucro**

Run: `.venv/bin/python -c "from app.domain.config import FeeConfig; from app.domain.fees import validate_fee_config; validate_fee_config(FeeConfig()); print('faixas ok')"`
Expected: `faixas ok`

- [ ] **Step 4: Commit**

```bash
git add tests/test_cenarios.py && git commit -m "test: cenários de ponta a ponta do núcleo de regras" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

## Autoavaliação (feita ao escrever o plano)

**Cobertura da spec:**
- Seção 5.1 etapas, 5.2 fila, 5.3 cancelamento: Tarefa 7 (e Tarefa 8 para a escolha da moto e a reserva).
- Seção 6 preço dinâmico: Tarefa 3.
- Seção 2 (taxa por faixa, 10 corridas com taxa, R$ 50, piso de lucro) e 7.2 (dívida em dinheiro, limite de dívida, divisão): Tarefas 4 e 5.
- Seção 7.2 passageiro que sai sem pagar: Tarefa 7.
- Seção 7.6 livro-caixa e conciliação: Tarefa 6.
- Seção 9 alertas de parada, fora da rota, localização falsa: Tarefa 9.
- Seção 12 (Pix não pago, estorno, aviso repetido, dois pedidos para a mesma moto, GPS): Tarefas 5, 6, 7, 8 e 9.

**Fora deste plano de propósito:** cadastro e documentos, login, API, banco, tempo real, telas, painel, integrações reais, SOS na tela (planos 2 a 8 do roteiro).

**Decisões novas que este plano acrescenta e que o Levy deve conhecer:**
1. Piso de preço de R$ 5,00 (a spec só fala do fator 0,8 a 1,6).
2. O abatimento da dívida de dinheiro é limitado a 50% do ganho da corrida Pix, para o motoqueiro nunca ficar com R$ 0,00.
3. Padrões provisórios: compensação de cancelamento de R$ 2,00, limite de dívida de R$ 10,00, faixas de taxa 100/90/80 centavos, espera máxima de 5 minutos na chegada.

**Varredura de lacunas e nomes:** nenhum passo tem "a definir", "tratar erros depois" ou "similar à tarefa N". Os nomes usados nas tarefas seguintes (`PaymentMethod`, `RiderAccount`, `Split`, `compute_split`, `settle_pix_ride`, `Ledger`, `Ride`, `RideState`, `RiderStatus`, `Candidate`, `PositionSample`, `SafetyResult`, `StraightLineEta`, `FakePaymentProvider`) são os mesmos definidos nas tarefas que os produzem.
