import 'package:flutter_test/flutter_test.dart';
import 'package:rider/dates.dart';

void main() {
  test('parseBrDate le dd/mm/aaaa', () {
    expect(parseBrDate('05/11/2030'), DateTime(2030, 11, 5));
  });

  test('parseBrDate recusa o que nao e uma data de verdade', () {
    expect(parseBrDate('31/02/2030'), isNull);
    expect(parseBrDate('5/11/2030'), isNull); // exige os zeros
    expect(parseBrDate(''), isNull);
    expect(parseBrDate('05/13/2030'), isNull);
    expect(parseBrDate('05/11/1899'), isNull);
    expect(parseBrDate('amanha'), isNull);
  });

  test('formatBrDate escreve dd/mm/aaaa', () {
    expect(formatBrDate(DateTime(2030, 1, 9)), '09/01/2030');
  });
}
