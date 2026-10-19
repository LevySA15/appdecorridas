import 'package:corrida_core/corrida_core.dart';
import 'package:test/test.dart';

void main() {
  test('formata reais e centavos como o servidor', () {
    expect(brl(0), 'R\$ 0,00');
    expect(brl(5), 'R\$ 0,05');
    expect(brl(750), 'R\$ 7,50');
    expect(brl(123400), 'R\$ 1.234,00');
    expect(brl(100000000), 'R\$ 1.000.000,00');
  });

  test('valor negativo leva o sinal na frente', () {
    expect(brl(-100), '-R\$ 1,00');
    expect(brl(-5), '-R\$ 0,05');
  });
}
