import 'package:flutter_test/flutter_test.dart';
import 'package:rider/format.dart';

void main() {
  test('km mostra metros abaixo de 1000', () {
    expect(km(350), '350 m');
    expect(km(0), '0 m');
  });

  test('km mostra uma casa e virgula a partir de 1000', () {
    expect(km(1000), '1,0 km');
    expect(km(1250), '1,3 km');
    expect(km(12340), '12,3 km');
  });
}
