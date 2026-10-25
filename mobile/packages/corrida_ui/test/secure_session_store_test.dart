import 'dart:convert';

import 'package:corrida_core/corrida_core.dart';
import 'package:corrida_ui/corrida_ui.dart';
import 'package:flutter/services.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter_test/flutter_test.dart';

/// Um armazenamento que sempre falha como o Keystore do Android falha quando as chaves estragam.
class _QuebradoStorage implements FlutterSecureStorage {
  _QuebradoStorage({this.apagarTambemFalha = false});

  final bool apagarTambemFalha;
  final apagados = <String>[];

  @override
  dynamic noSuchMethod(Invocation invocation) {
    if (invocation.memberName == #read) {
      return Future<String?>.error(PlatformException(code: 'keystore'));
    }
    if (invocation.memberName == #delete) {
      if (apagarTambemFalha) {
        return Future<void>.error(PlatformException(code: 'keystore'));
      }
      apagados.add(invocation.namedArguments[#key] as String);
      return Future<void>.value();
    }
    return Future<void>.value();
  }
}

void main() {
  setUp(() => FlutterSecureStorage.setMockInitialValues({}));

  test('guarda e devolve a sessao', () async {
    final store = SecureSessionStore();
    await store.save(
      Session(token: 'tok-1', userId: 'u1', role: 'rider', name: 'João'),
    );

    final lida = await store.load();

    expect(lida?.token, 'tok-1');
    expect((lida?.userId, lida?.role, lida?.name), ('u1', 'rider', 'João'));
  });

  test('sem nada guardado devolve nulo', () async {
    expect(await SecureSessionStore().load(), isNull);
  });

  test('clear esquece a sessao', () async {
    final store = SecureSessionStore();
    await store.save(Session(token: 't', userId: 'u', role: 'rider'));

    await store.clear();

    expect(await store.load(), isNull);
  });

  test('o que fica guardado e a sessao em JSON, numa chave so', () async {
    final armazenamento = FlutterSecureStorage();
    await SecureSessionStore(storage: armazenamento)
        .save(Session(token: 'tok-1', userId: 'u1', role: 'rider'));

    final bruto = await armazenamento.readAll();

    expect(bruto.keys, ['session']);
    expect(jsonDecode(bruto['session']!), containsPair('token', 'tok-1'));
  });

  test(
    'valor estragado vira FormatException e o SessionManager esquece',
    () async {
      FlutterSecureStorage.setMockInitialValues({'session': 'isto nao e json'});
      final store = SecureSessionStore();
      final client = ApiClient(baseUrl: Uri.parse('http://s.teste'));
      final manager = SessionManager(AuthApi(client), store, client);

      final restaurada = await manager.restore();

      expect(restaurada, isNull);
      expect(await FlutterSecureStorage().readAll(), isEmpty);
    },
  );

  test('keystore quebrado: nao derruba o app, esquece e pede login', () async {
    final quebrado = _QuebradoStorage();

    final lida = await SecureSessionStore(storage: quebrado).load();

    expect(lida, isNull);
    expect(quebrado.apagados, ['session']);
  });

  test(
    'keystore quebrado ate para apagar: ainda assim pede login, sem derrubar',
    () async {
      final lida = await SecureSessionStore(
        storage: _QuebradoStorage(apagarTambemFalha: true),
      ).load();

      expect(lida, isNull);
    },
  );
}
