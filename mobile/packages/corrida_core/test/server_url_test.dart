import 'package:corrida_core/corrida_core.dart';
import 'package:test/test.dart';

void main() {
  group('serverUrlFrom', () {
    test('sem API_URL usa o localhost do adb reverse', () {
      expect(serverUrlFrom(''), Uri.parse('http://localhost:8000'));
    });

    test('tira a barra do fim e aceita HTTPS', () {
      expect(serverUrlFrom('https://corrida.exemplo.com.br/'), Uri.parse('https://corrida.exemplo.com.br'));
      expect(serverUrlFrom('https://corrida.exemplo.com.br'), Uri.parse('https://corrida.exemplo.com.br'));
    });

    test('aceita HTTP com porta em depuração (emulador, rede de casa)', () {
      expect(serverUrlFrom('http://10.0.2.2:8000'), Uri.parse('http://10.0.2.2:8000'));
    });

    test('guarda o caminho se o servidor ficar numa subpasta', () {
      expect(serverUrlFrom('https://exemplo.com.br/api/'), Uri.parse('https://exemplo.com.br/api'));
    });

    for (final ruim in ['ftp://x', 'corrida.exemplo.com.br', 'https://', 'http:///so-caminho']) {
      test('recusa "$ruim"', () {
        expect(
          () => serverUrlFrom(ruim),
          throwsA(isA<FormatException>().having((e) => e.message, 'mensagem', startsWith('API_URL inválida'))),
        );
      });
    }

    test('no release o HTTP puro é recusado com a razão', () {
      expect(
        () => serverUrlFrom('http://servidor.exemplo', isRelease: true),
        throwsA(isA<FormatException>().having((e) => e.message, 'mensagem', contains('HTTPS'))),
      );
    });

    test('no release o HTTPS e o padrão continuam valendo', () {
      expect(serverUrlFrom('https://corrida.exemplo.com.br', isRelease: true), Uri.parse('https://corrida.exemplo.com.br'));
      expect(serverUrlFrom('', isRelease: true), Uri.parse('http://localhost:8000'));
    });
  });
}
