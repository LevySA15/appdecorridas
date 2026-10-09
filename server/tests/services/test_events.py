from app.services.events import Event, EventCollector


def test_coletor_guarda_e_entrega_na_ordem_uma_vez_so():
    coletor = EventCollector()
    coletor.add("u1", "oferta", {"ride_id": "ride-1"})
    coletor.add("u2", "aceita")
    assert coletor.events == (Event("u1", "oferta", {"ride_id": "ride-1"}), Event("u2", "aceita", {}))
    assert [e.type for e in coletor.drain()] == ["oferta", "aceita"]
    assert coletor.drain() == []


def test_coletor_desfaz_os_avisos_depois_de_uma_marca():
    # Revisão final do plano 2B (I3): a varredura desfaz o banco de uma corrida que falhou; os avisos também.
    coletor = EventCollector()
    coletor.add("u1", "a")
    marca = coletor.mark()
    coletor.add("u2", "b")
    coletor.add("u3", "c")
    coletor.rollback_to(marca)
    assert [e.type for e in coletor.events] == ["a"]
    coletor.rollback_to(marca)           # repetir não faz mal
    assert [e.type for e in coletor.events] == ["a"]
