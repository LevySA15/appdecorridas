import 'dart:async';
import 'dart:convert';

import 'package:corrida_core/corrida_core.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:test/test.dart';

http.Response json(Object? body, [int status = 200]) => http.Response.bytes(
  utf8.encode(jsonEncode(body)),
  status,
  headers: {'content-type': 'application/json; charset=utf-8'},
);

ApiClient client(
  Future<http.Response> Function(http.Request) handler, {
  String base = 'http://servidor.teste',
  Duration timeout = const Duration(seconds: 2),
  void Function()? onUnauthorized,
}) => ApiClient(
  baseUrl: Uri.parse(base),
  httpClient: MockClient(handler),
  timeout: timeout,
  onUnauthorized: onUnauthorized,
);

void main() {
  test('get devolve o json decodificado em utf-8', () async {
    final api = client((r) async {
      expect(r.method, 'GET');
      expect(r.url.toString(), 'http://servidor.teste/v1/me');
      return json({'name': 'Zé da Conceição'});
    });
    expect(await api.get('/v1/me'), {'name': 'Zé da Conceição'});
  });

  test('204 devolve null', () async {
    final api = client((r) async => http.Response('', 204));
    expect(await api.post('/v1/auth/code', body: {'phone': '75'}), isNull);
  });

  test('manda o token e o tipo do corpo', () async {
    late http.Request visto;
    final api = client((r) async {
      visto = r;
      return json({});
    });
    await api.post('/v1/auth/code', body: {'phone': '75988510824'});
    expect(visto.headers.containsKey('authorization'), isFalse);
    api.token = 'abc';
    await api.post('/v1/x', body: {'a': 1});
    expect(visto.headers['authorization'], 'Bearer abc');
    expect(visto.headers['content-type'], startsWith('application/json'));
    expect(jsonDecode(visto.body), {'a': 1});
    await api.get('/v1/y');
    expect(visto.headers.containsKey('content-type'), isFalse);
  });

  test('put com corpo vai como put', () async {
    late http.Request visto;
    final api = client((r) async {
      visto = r;
      return http.Response('', 204);
    });
    await api.put('/v1/me', body: {'name': 'Ana'});
    expect(visto.method, 'PUT');
    expect(jsonDecode(visto.body), {'name': 'Ana'});
  });

  test('consulta vai codificada', () async {
    late Uri visto;
    final api = client((r) async {
      visto = r.url;
      return json([]);
    });
    await api.get('/v1/admin/passengers', query: {'q': 'maria silva & cia'});
    expect(visto.queryParameters, {'q': 'maria silva & cia'});
    expect(visto.path, '/v1/admin/passengers');
  });

  test('erro da api vira ApiException com código e frase', () async {
    final api = client(
      (r) async => json({
        'error': {
          'code': 'quote_expired',
          'message': 'Esse preço não vale mais. Peça de novo.',
          'field': 'quote_id',
        },
      }, 409),
    );
    try {
      await api.post('/v1/passenger/rides', body: {});
      fail('devia ter falhado');
    } on ApiException catch (e) {
      expect(e.status, 409);
      expect(e.code, 'quote_expired');
      expect(e.message, 'Esse preço não vale mais. Peça de novo.');
      expect(e.field, 'quote_id');
    }
  });

  test('erro com lista de campos', () async {
    final api = client(
      (r) async => json({
        'error': {
          'code': 'invalid',
          'message': 'Confira os campos.',
          'fields': ['name', 'cpf'],
        },
      }, 422),
    );
    try {
      await api.post('/v1/x');
      fail('devia ter falhado');
    } on ApiException catch (e) {
      expect(e.fields, ['name', 'cpf']);
      expect(e.field, isNull);
    }
  });

  test(
    'erro que não é json (proxy) vira ApiException com código http',
    () async {
      final api = client(
        (r) async => http.Response('<html>Bad Gateway</html>', 502),
      );
      try {
        await api.get('/v1/me');
        fail('devia ter falhado');
      } on ApiException catch (e) {
        expect(e.status, 502);
        expect(e.code, 'http_502');
        expect(e.message, isNotEmpty);
        expect(e.message, isNot(contains('<html>')));
      }
    },
  );

  test('erro json sem o formato esperado também vira ApiException', () async {
    final api = client((r) async => json(['estranho'], 500));
    await expectLater(
      api.get('/v1/me'),
      throwsA(isA<ApiException>().having((e) => e.code, 'code', 'http_500')),
    );
  });

  test('sucesso com corpo que não é json vira NetworkException', () async {
    final api = client((r) async => http.Response('<html>oi</html>', 200));
    await expectLater(api.get('/v1/me'), throwsA(isA<NetworkException>()));
  });

  test('401 com token avisa uma vez e limpa o token', () async {
    var avisos = 0;
    final api = client(
      (r) async => json({
        'error': {'code': 'unauthorized', 'message': 'Entre de novo.'},
      }, 401),
      onUnauthorized: () => avisos++,
    );
    api.token = 'abc';
    await expectLater(api.get('/v1/me'), throwsA(isA<ApiException>()));
    await expectLater(api.get('/v1/me'), throwsA(isA<ApiException>()));
    expect(avisos, 1);
    expect(api.token, isNull);
  });

  test('401 sem token não avisa (código de login errado)', () async {
    var avisos = 0;
    final api = client(
      (r) async => json({
        'error': {'code': 'code_invalid', 'message': 'Código errado.'},
      }, 401),
      onUnauthorized: () => avisos++,
    );
    await expectLater(
      api.post('/v1/auth/verify', body: {}),
      throwsA(isA<ApiException>()),
    );
    expect(avisos, 0);
  });

  test('falha de rede vira NetworkException e não vaza o token', () async {
    final api = client(
      (r) async => throw http.ClientException('sem rota', r.url),
    );
    api.token = 'segredo123';
    try {
      await api.get('/v1/me');
      fail('devia ter falhado');
    } on NetworkException catch (e) {
      expect(e.toString(), isNot(contains('segredo123')));
      expect(e.message, isNotEmpty);
    }
  });

  test('tempo esgotado vira NetworkException', () async {
    final api = client(
      (r) => Completer<http.Response>().future,
      timeout: const Duration(milliseconds: 50),
    );
    await expectLater(api.get('/v1/me'), throwsA(isA<NetworkException>()));
  });

  test('putBytes manda os bytes crus com o tipo', () async {
    late http.Request visto;
    final api = client((r) async {
      visto = r;
      return json({'key': 'k1', 'bytes': 3}, 201);
    });
    api.token = 'abc';
    final resposta = await api.putBytes('/v1/rider/documents/selfie', [
      1,
      2,
      3,
    ], contentType: 'image/jpeg');
    expect(resposta, {'key': 'k1', 'bytes': 3});
    expect(visto.method, 'PUT');
    expect(visto.bodyBytes, [1, 2, 3]);
    expect(visto.headers['content-type'], 'image/jpeg');
    expect(visto.headers['authorization'], 'Bearer abc');
  });

  test('url base com ou sem barra final e com caminho', () async {
    final vistos = <String>[];
    Future<http.Response> anota(http.Request r) async {
      vistos.add(r.url.toString());
      return json({});
    }

    await client(anota, base: 'http://x/').get('/v1/me');
    await client(anota, base: 'http://x').get('/v1/me');
    await client(anota, base: 'https://x.com/api/').get('/v1/me');
    expect(vistos, [
      'http://x/v1/me',
      'http://x/v1/me',
      'https://x.com/api/v1/me',
    ]);
  });

  test(
    'upload de foto tem tempo próprio, bem maior que o das outras chamadas',
    () async {
      final api = client((r) async {
        await Future<void>.delayed(const Duration(milliseconds: 120));
        return json({'key': 'k', 'bytes': 1}, 201);
      }, timeout: const Duration(milliseconds: 40));
      await expectLater(api.get('/v1/me'), throwsA(isA<NetworkException>()));
      expect(
        await api.putBytes('/v1/rider/documents/selfie', [
          1,
        ], contentType: 'image/jpeg'),
        {'key': 'k', 'bytes': 1},
      );
    },
  );

  test('o tempo do upload pode ser escolhido', () async {
    final api = client((r) async {
      await Future<void>.delayed(const Duration(milliseconds: 120));
      return json({}, 201);
    });
    await expectLater(
      api.putBytes(
        '/v1/x',
        [1],
        contentType: 'image/jpeg',
        timeout: const Duration(milliseconds: 30),
      ),
      throwsA(isA<NetworkException>()),
    );
  });

  test('401 atrasado de uma sessão antiga não derruba a sessão nova', () async {
    var avisos = 0;
    final liberar = Completer<void>();
    final api = client((r) async {
      await liberar.future;
      return json({
        'error': {'code': 'unauthorized', 'message': 'Entre de novo.'},
      }, 401);
    }, onUnauthorized: () => avisos++);
    api.token = 'velho';
    final atrasada = api.get('/v1/me');
    await Future<void>.delayed(const Duration(milliseconds: 10));
    api.token = 'novo'; // entrou de novo enquanto a chamada antiga ainda voava
    liberar.complete();
    await expectLater(atrasada, throwsA(isA<ApiException>()));
    expect(api.token, 'novo');
    expect(avisos, 0);
  });
}
