import 'dart:async';
import 'dart:convert';

import 'package:corrida_core/corrida_core.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:test/test.dart';

http.Response json(Object? body, [int status = 200]) =>
    http.Response.bytes(utf8.encode(jsonEncode(body)), status, headers: {'content-type': 'application/json'});

const verifyOk = {
  'token': 'tok-1',
  'user_id': 'u1',
  'role': 'passenger',
  'is_new_user': true,
  'name': null,
};

class Mundo {
  Mundo(Future<http.Response> Function(http.Request) handler) {
    api = ApiClient(baseUrl: Uri.parse('http://s.teste'), httpClient: MockClient(handler));
    auth = AuthApi(api);
    store = MemorySessionStore();
    manager = SessionManager(auth, store, api);
  }

  late final ApiClient api;
  late final AuthApi auth;
  late final MemorySessionStore store;
  late final SessionManager manager;
}

void main() {
  test('requestCode posta o telefone', () async {
    late http.Request visto;
    final m = Mundo((r) async {
      visto = r;
      return http.Response('', 204);
    });
    await m.auth.requestCode('75 98851-0824');
    expect(visto.method, 'POST');
    expect(visto.url.path, '/v1/auth/code');
    expect(jsonDecode(visto.body), {'phone': '75 98851-0824'});
  });

  test('verify devolve a sessão e põe o token no cliente', () async {
    late http.Request visto;
    final m = Mundo((r) async {
      visto = r;
      return json(verifyOk);
    });
    final resultado = await m.auth.verify(phone: '75988510824', code: '123456', role: 'passenger', device: 'pixel');
    expect(jsonDecode(visto.body), {'phone': '75988510824', 'code': '123456', 'role': 'passenger', 'device': 'pixel'});
    expect(resultado.isNewUser, isTrue);
    expect((resultado.session.token, resultado.session.userId, resultado.session.role), ('tok-1', 'u1', 'passenger'));
    expect(m.api.token, 'tok-1');
  });

  test('verify sem aparelho não manda o campo', () async {
    late http.Request visto;
    final m = Mundo((r) async {
      visto = r;
      return json(verifyOk);
    });
    await m.auth.verify(phone: '1', code: '2', role: 'rider');
    expect(jsonDecode(visto.body), {'phone': '1', 'code': '2', 'role': 'rider'});
  });

  test('código errado levanta code_invalid e não põe token', () async {
    final m = Mundo((r) async => json({'error': {'code': 'code_invalid', 'message': 'Código errado.'}}, 401));
    await expectLater(
      m.auth.verify(phone: '1', code: '0', role: 'passenger'),
      throwsA(isA<ApiException>().having((e) => e.code, 'code', 'code_invalid')),
    );
    expect(m.api.token, isNull);
  });

  test('resposta de verify sem token é erro de rede, não sessão vazia', () async {
    final m = Mundo((r) async => json({'user_id': 'u1'}));
    await expectLater(m.auth.verify(phone: '1', code: '2', role: 'passenger'), throwsA(isA<NetworkException>()));
    expect(m.api.token, isNull);
  });

  test('me e updateName', () async {
    final pedidos = <String>[];
    final m = Mundo((r) async {
      pedidos.add('${r.method} ${r.url.path}');
      if (r.method == 'PUT') expect(jsonDecode(r.body), {'name': 'Ana Lima'});
      return json({'user_id': 'u1', 'phone': '+5575988510824', 'name': 'Ana Lima', 'role': 'passenger'});
    });
    final eu = await m.auth.me();
    expect((eu.userId, eu.phone, eu.name, eu.role), ('u1', '+5575988510824', 'Ana Lima', 'passenger'));
    expect((await m.auth.updateName('Ana Lima')).name, 'Ana Lima');
    expect(pedidos, ['GET /v1/me', 'PUT /v1/me']);
  });

  test('restore com sessão guardada põe o token', () async {
    final m = Mundo((r) async => json({}));
    await m.store.save(Session(token: 'guardado', userId: 'u1', role: 'rider'));
    final sessao = await m.manager.restore();
    expect(sessao!.userId, 'u1');
    expect(m.api.token, 'guardado');
    expect(m.manager.current, same(sessao));
  });

  test('restore sem nada devolve null', () async {
    final m = Mundo((r) async => json({}));
    expect(await m.manager.restore(), isNull);
    expect(m.api.token, isNull);
  });

  test('signIn guarda a sessão e avisa em changes', () async {
    final m = Mundo((r) async => json(verifyOk));
    final avisos = <Session?>[];
    m.manager.changes.listen(avisos.add);
    final resultado = await m.manager.signIn(phone: '1', code: '2', role: 'passenger');
    await pumpEventQueue();
    expect((await m.store.load())!.token, 'tok-1');
    expect(m.manager.current!.token, 'tok-1');
    expect(resultado.isNewUser, isTrue);
    expect(avisos.map((s) => s?.token), ['tok-1']);
  });

  test('signOut limpa tudo mesmo com a rede fora', () async {
    final m = Mundo((r) async => r.url.path == '/v1/auth/verify' ? json(verifyOk) : throw http.ClientException('sem rede'));
    await m.manager.signIn(phone: '1', code: '2', role: 'passenger');
    final avisos = <Session?>[];
    m.manager.changes.listen(avisos.add);
    await m.manager.signOut();
    await pumpEventQueue();
    expect(await m.store.load(), isNull);
    expect(m.api.token, isNull);
    expect(m.manager.current, isNull);
    expect(avisos, [null]);
  });

  test('signOut chama o logout do servidor quando há rede', () async {
    final pedidos = <String>[];
    final m = Mundo((r) async {
      pedidos.add(r.url.path);
      return r.url.path == '/v1/auth/verify' ? json(verifyOk) : http.Response('', 204);
    });
    await m.manager.signIn(phone: '1', code: '2', role: 'passenger');
    await m.manager.signOut();
    expect(pedidos, ['/v1/auth/verify', '/v1/auth/logout']);
  });

  test('401 no meio do uso limpa a sessão uma vez e avisa, sem chamar a rede de novo', () async {
    final pedidos = <String>[];
    final m = Mundo((r) async {
      pedidos.add(r.url.path);
      if (r.url.path == '/v1/auth/verify') return json(verifyOk);
      return json({'error': {'code': 'unauthorized', 'message': 'Entre de novo.'}}, 401);
    });
    await m.manager.signIn(phone: '1', code: '2', role: 'passenger');
    final avisos = <Session?>[];
    m.manager.changes.listen(avisos.add);
    await expectLater(m.auth.me(), throwsA(isA<ApiException>()));
    await pumpEventQueue();
    expect(m.manager.current, isNull);
    expect(await m.store.load(), isNull);
    expect(avisos, [null]);
    expect(pedidos, ['/v1/auth/verify', '/v1/me']);
  });
}
