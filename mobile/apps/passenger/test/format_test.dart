import 'package:corrida_core/corrida_core.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:passenger/format.dart';

void main() {
  test('formatRideDate escreve dia, mes, ano e hora locais', () {
    final instante =
        DateTime(2026, 11, 20, 18, 5).millisecondsSinceEpoch / 1000;
    expect(formatRideDate(instante), '20/11/2026 18:05');
  });

  test('formatRideDate poe zero a esquerda', () {
    final instante = DateTime(2026, 1, 3, 7, 4).millisecondsSinceEpoch / 1000;
    expect(formatRideDate(instante), '03/01/2026 07:04');
  });

  test('rideStateLabel diz o fim de cada corrida', () {
    expect(rideStateLabel(RideState.completed), 'Concluída');
    expect(rideStateLabel(RideState.cancelled), 'Cancelada');
    expect(rideStateLabel(RideState.noRider), 'Sem moto');
    expect(rideStateLabel(RideState.unknown), 'Encerrada');
  });
}
