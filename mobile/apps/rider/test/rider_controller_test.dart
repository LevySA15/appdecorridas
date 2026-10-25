import 'dart:convert';

import 'package:corrida_core/corrida_core.dart';
import 'package:flutter_test/flutter_test.dart';

import 'support/fakes.dart';
import 'support/mundo.dart';

void main() {
  test('comeca sem sessao guardada fica esperando login', () async {
    final m = Mundo();
    await m.controller.start();
    expect(m.controller.session, isNull);
    expect(m.controller.state, isNull);
    expect(m.controller.starting, isFalse);
    expect(m.canais, isEmpty);
  });

  test(
    'comeca com sessao guardada carrega o estado e liga o tempo real',
    () async {
      final m = Mundo();
      await m.store.save(Session(token: 'tok-1', userId: 'u1', role: 'rider'));
      await m.controller.start();
      expect(m.controller.state, isNotNull);
      expect(
        m.controller.state!.registration.status,
        RegistrationStatus.notRegistered,
      );
      expect(m.canais.length, 1);
    },
  );

  test('verify entra pelo papel rider', () async {
    final m = Mundo();
    await m.controller.start();
    await m.controller.verify(phone: '75988510824', code: '123456');
    final corpo = jsonDecode(
      m.sent('POST', '/v1/auth/verify').single.body,
    ) as Map<String, Object?>;
    expect(corpo['role'], 'rider');
    expect(m.controller.session, isNotNull);
    expect(m.controller.state, isNotNull);
    expect(m.canais.length, 1);
  });

  test('sign out desliga o tempo real e limpa tudo', () async {
    final m = Mundo();
    await m.controller.start();
    await m.controller.verify(phone: '75988510824', code: '123456');
    await m.controller.signOut();
    expect(m.controller.session, isNull);
    expect(m.controller.state, isNull);
    expect(m.canais.single.sink.fechado, isTrue);
  });

  test('aviso de tempo real atualiza o estado', () async {
    final m = Mundo();
    await m.controller.start();
    await m.controller.verify(phone: '75988510824', code: '123456');
    m.stateJson = {
      ...estadoNaoCadastrado,
      'registration': {'status': 'pending'},
    };
    m.canais.single.servidorMandaAviso('algum_aviso', {});
    await deixaRodar();
    expect(m.controller.state!.registration.status, RegistrationStatus.pending);
  });

  test('quem assina events recebe os avisos crus', () async {
    final m = Mundo();
    await m.controller.start();
    await m.controller.verify(phone: '75988510824', code: '123456');
    final recebidos = <ServerEvent>[];
    final sub = m.controller.events.listen(recebidos.add);
    m.canais.single.servidorMandaAviso('algum_aviso', {});
    await deixaRodar();
    expect(recebidos.single.type, 'algum_aviso');
    await sub.cancel();
  });

  test('401 fecha o tempo real e limpa sessao e estado', () async {
    final m = Mundo();
    await m.controller.start();
    await m.controller.verify(phone: '75988510824', code: '123456');
    m.stateStatus = 401;
    await expectLater(
      m.controller.refreshState(),
      throwsA(isA<ApiException>()),
    );
    await deixaRodar();
    expect(m.controller.session, isNull);
    expect(m.controller.state, isNull);
    expect(m.canais.single.sink.fechado, isTrue);
  });
}
