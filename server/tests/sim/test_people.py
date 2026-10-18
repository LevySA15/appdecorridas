import datetime as dt

from app.services.auth import normalize_phone
from app.services.riders import normalize_cnh, normalize_plate, validate_cpf
from simulator.people import JPEG, passenger_identity, rider_identity


def test_motoqueiros_de_mentira_passam_nas_conferencias_do_servidor():
    hoje = dt.date(2026, 10, 18)
    for i in (1, 2, 37, 999, 4321):
        pessoa = rider_identity(i, hoje)
        assert normalize_phone(pessoa.phone).startswith("+55")
        assert validate_cpf(pessoa.cpf) and normalize_cnh(pessoa.cnh_number) and normalize_plate(pessoa.plate)
        assert pessoa.name.endswith("(sim)") and pessoa.cnh_expires_on > hoje and pessoa.crlv_expires_on > hoje


def test_cada_motoqueiro_tem_documentos_unicos():
    hoje = dt.date(2026, 10, 18)
    pessoas = [rider_identity(i, hoje) for i in range(1, 400)]
    for campo in ("phone", "cpf", "cnh_number", "plate"):
        assert len({getattr(p, campo) for p in pessoas}) == len(pessoas), campo


def test_passageiros_e_motoqueiros_nunca_dividem_telefone():
    hoje = dt.date(2026, 10, 18)
    telefones = {normalize_phone(rider_identity(i, hoje).phone) for i in range(1, 300)}
    telefones |= {normalize_phone(passenger_identity(i).phone) for i in range(1, 300)}
    assert len(telefones) == 598


def test_a_foto_de_mentira_parece_jpeg_para_o_servidor():
    assert JPEG.startswith(b"\xff\xd8\xff")
