import 'package:corrida_core/corrida_core.dart';
import 'package:test/test.dart';

const _pares = [
  [-12.96, -39.26],
  [-12.965, -39.255],
  [-12.97, -39.25],
];

void main() {
  group('placesFromPairs', () {
    test('lê [[lat, lng], ...] e aceita inteiros e decimais', () {
      final route = placesFromPairs([
        [-12.96, -39.26],
        [-13, -39],
      ]);
      expect(route, const [
        Place(lat: -12.96, lng: -39.26),
        Place(lat: -13, lng: -39),
      ]);
    });

    test('sem traçado, nulo ou fora do formato vira lista vazia', () {
      expect(placesFromPairs(null), isEmpty);
      expect(placesFromPairs('lixo'), isEmpty);
      expect(placesFromPairs(const <Object?>[]), isEmpty);
    });

    test('item torto é ignorado e o resto fica', () {
      final route = placesFromPairs([
        [-12.96, -39.26],
        [1],
        'x',
        [null, 2],
        ['a', 'b'],
        [-12.97, -39.25, 99],
        null,
      ]);
      expect(route, const [
        Place(lat: -12.96, lng: -39.26),
        Place(lat: -12.97, lng: -39.25),
      ]);
    });
  });

  group('o traçado nos modelos', () {
    test('cotação', () {
      final quote = Quote.fromJson({'quote_id': 'q', 'route': _pares});
      expect(quote.route, hasLength(3));
      expect(quote.route.first, const Place(lat: -12.96, lng: -39.26));
      expect(quote.route.last, const Place(lat: -12.97, lng: -39.25));
    });

    test('corrida do passageiro', () {
      final ride = PassengerRide.fromJson({
        'ride_id': 'r',
        'state': 'accepted',
        'route': _pares,
      });
      expect(ride.route, hasLength(3));
    });

    test('oferta e corrida do motoqueiro', () {
      expect(
        Offer.fromJson({'ride_id': 'r', 'route': _pares}).route,
        hasLength(3),
      );
      expect(
        RiderRide.fromJson({
          'ride_id': 'r',
          'state': 'accepted',
          'route': _pares,
        }).route,
        hasLength(3),
      );
    });

    test('servidor antigo (sem route) deixa a lista vazia, sem erro', () {
      expect(Quote.fromJson({'quote_id': 'q'}).route, isEmpty);
      expect(PassengerRide.fromJson({'ride_id': 'r'}).route, isEmpty);
      expect(Offer.fromJson({'ride_id': 'r'}).route, isEmpty);
      expect(RiderRide.fromJson({'ride_id': 'r'}).route, isEmpty);
    });
  });
}
