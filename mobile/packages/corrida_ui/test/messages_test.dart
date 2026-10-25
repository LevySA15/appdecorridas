import 'package:corrida_core/corrida_core.dart';
import 'package:corrida_ui/corrida_ui.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('erro da API mostra a frase do servidor', () {
    final error = ApiException(
      status: 409,
      code: 'offer_gone',
      message: 'Essa oferta não está mais disponível.',
    );
    expect(friendlyMessage(error), 'Essa oferta não está mais disponível.');
  });

  test('erro de rede mostra a frase da rede', () {
    expect(
      friendlyMessage(NetworkException('Sem internet.')),
      'Sem internet.',
    );
  });

  test('qualquer outro erro mostra a frase generica', () {
    expect(friendlyMessage(StateError('x')), 'Algo deu errado. Tente de novo.');
  });
}
