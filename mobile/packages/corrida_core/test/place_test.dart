import 'package:corrida_core/corrida_core.dart';
import 'package:test/test.dart';

void main() {
  test('o mesmo lugar lido duas vezes é igual', () {
    const a = Place(lat: -12.96, lng: -39.26, text: 'Rua A');
    final b = Place.fromJson(a.toJson());

    expect(b, a);
    expect(b.hashCode, a.hashCode);
  });

  test('lugares diferentes são diferentes', () {
    const a = Place(lat: -12.96, lng: -39.26);

    expect(a, isNot(const Place(lat: -12.97, lng: -39.26)));
    expect(a, isNot(const Place(lat: -12.96, lng: -39.27)));
    expect(a, isNot(const Place(lat: -12.96, lng: -39.26, text: 'Rua A')));
  });
}
