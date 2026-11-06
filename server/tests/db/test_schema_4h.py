from sqlalchemy import text


def _indices(session) -> dict[str, str]:
    linhas = session.execute(
        text("SELECT indexname, indexdef FROM pg_indexes WHERE schemaname = current_schema()")
    ).all()
    return dict(linhas)


def test_lista_de_corridas_do_painel_tem_indice_por_data(session):
    definicao = _indices(session)["ix_rides_created_at"]
    assert "ON" in definicao and "rides" in definicao and "(created_at)" in definicao


def test_varredura_de_sem_sinal_tem_indice_por_tipo_de_evento(session):
    definicao = _indices(session)["ix_ride_events_kind_ride"]
    assert "ride_events" in definicao and "(kind, ride_id)" in definicao
