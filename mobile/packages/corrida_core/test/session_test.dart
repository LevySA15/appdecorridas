import 'package:corrida_core/corrida_core.dart';
import 'package:test/test.dart';

void main() {
  test('sessão vai e volta em json', () {
    final sessao = Session(
      token: 't1',
      userId: 'u1',
      role: 'passenger',
      name: 'Ana',
    );
    final deVolta = Session.fromJson(sessao.toJson());
    expect(
      (deVolta.token, deVolta.userId, deVolta.role, deVolta.name),
      ('t1', 'u1', 'passenger', 'Ana'),
    );
  });

  test('sessão sem nome volta sem nome', () {
    final sessao = Session.fromJson(
      Session(token: 't', userId: 'u', role: 'rider').toJson(),
    );
    expect(sessao.name, isNull);
  });

  test('json estragado não vira sessão', () {
    expect(() => Session.fromJson({'token': 5}), throwsFormatException);
    expect(() => Session.fromJson({}), throwsFormatException);
  });

  test('armazenamento em memória guarda, devolve e limpa', () async {
    final store = MemorySessionStore();
    expect(await store.load(), isNull);
    await store.save(Session(token: 't', userId: 'u', role: 'rider'));
    expect((await store.load())!.token, 't');
    await store.clear();
    expect(await store.load(), isNull);
  });
}
