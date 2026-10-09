"""Montagem rápida de pessoas e corridas no banco de testes."""
from sqlalchemy.orm import Session

from app.db import repositories as repo
from app.db.models import RiderProfileRow
from app.domain.geo import GeoPoint
from app.domain.rides import Ride, accept, start_search
from app.domain.types import PaymentMethod
from tests.helpers import ORIGIN, pt


def add_passenger(session: Session, user_id: str = "p1", phone: str = "+5575900000001") -> None:
    repo.add_user(session, user_id=user_id, phone=phone, name=f"Passageiro {user_id}", role="passenger")
    repo.add_passenger_profile(session, user_id=user_id)


def add_rider(
    session: Session,
    user_id: str = "r1",
    phone: str = "+5575900000002",
    cpf: str = "111.111.111-11",
    cnh: str = "CNH0001",
    plate: str = "AAA1A11",
    debt_cents: int = 0,
) -> None:
    repo.add_user(session, user_id=user_id, phone=phone, name=f"Motoqueiro {user_id}", role="rider")
    repo.add_rider_profile(
        session, user_id=user_id, cpf=cpf, cnh_number=cnh, plate=plate, moto_model="Honda CG 160"
    )
    if debt_cents:
        acc = repo.get_rider_account(session, user_id)
        acc.cash_debt_cents = debt_cents
        repo.save_rider_account(session, acc)


def add_accepted_ride(
    session: Session,
    ride_id: str = "ride-1",
    passenger_id: str = "p1",
    rider_id: str = "r1",
    method: PaymentMethod = PaymentMethod.PIX,
    price: int = 700,
    busy: bool = False,
    now: float = 10.0,
) -> Ride:
    ride = Ride(ride_id, passenger_id, price, method, pin="4821")
    start_search(ride, 0)
    accept(ride, rider_id, now, rider_busy=busy)
    repo.add_ride(session, ride)
    return ride


def make_cpf(base: str) -> str:
    """CPF válido a partir de 9 dígitos (calcula os dois dígitos verificadores)."""
    d = [int(c) for c in base]
    for n in (9, 10):
        total = sum(d[i] * (n + 1 - i) for i in range(n))
        d.append((total * 10 % 11) % 10)
    return "".join(map(str, d))


def make_online_rider(session, positions, n: int, point: GeoPoint, now: float = 100.0) -> str:
    """Motoqueiro aprovado, disponível e com posição fresca. `n` torna CPF, CNH, placa e telefone únicos."""
    rider_id = f"r{n}"
    add_rider(
        session, user_id=rider_id, phone=f"+5575977{n:06d}", cpf=f"{n:011d}", cnh=f"{n:011d}", plate=f"ABC{n:04d}"
    )
    profile = session.get(RiderProfileRow, rider_id)
    profile.status, profile.online = "approved", True
    session.flush()
    positions.update(rider_id, point, now)
    return rider_id


def add_searching_ride(
    session,
    ride_id: str = "ride-1",
    passenger_id: str = "p1",
    method: PaymentMethod = PaymentMethod.PIX,
    price: int = 700,
    pickup: GeoPoint = ORIGIN,
    destination: GeoPoint | None = None,
    now: float = 10.0,
) -> Ride:
    ride = Ride(ride_id, passenger_id, price, method, pin="4821")
    start_search(ride, now)
    repo.add_ride(session, ride)
    repo.set_ride_details(
        session, ride_id,
        repo.RideDetails(pickup, destination or pt(1500, 0), "Rua A", "Feira livre", 1950, 1.0, "Preço normal."),
    )
    return ride
