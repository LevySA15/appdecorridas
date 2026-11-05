import 'package:corrida_ui/corrida_ui.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('o número de emergência é o 190', () {
    expect(emergencyNumber, '190');
  });

  test('o endereço do discador é tel:<numero>', () {
    expect(dialUri('190').toString(), 'tel:190');
  });

  test('abre o discador com o numero e devolve true', () async {
    Uri? aberto;
    final ok = await dialNumber(
      '190',
      launch: (uri) async {
        aberto = uri;
        return true;
      },
    );
    expect(ok, isTrue);
    expect(aberto.toString(), 'tel:190');
  });

  test('celular que não abre o discador devolve false', () async {
    expect(await dialNumber('190', launch: (_) async => false), isFalse);
  });

  test('erro da plataforma nunca sobe: devolve false', () async {
    expect(
      await dialNumber('190', launch: (_) async => throw Exception('sem app')),
      isFalse,
    );
  });
}
