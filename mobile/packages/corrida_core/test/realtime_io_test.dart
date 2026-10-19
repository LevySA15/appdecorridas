// A conexão padrão (dart:io) contra um servidor WebSocket de verdade, na própria máquina.
import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:corrida_core/corrida_core.dart';
import 'package:test/test.dart';

class ServidorDeVerdade {
  late final HttpServer http;
  final recebidas = <String>[];
  final conexoes = <WebSocket>[];
  var pararDeLer = false;

  Future<void> iniciar() async {
    http = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
    http.listen((requisicao) async {
      final ws = await WebSocketTransformer.upgrade(requisicao);
      conexoes.add(ws);
      final leitura = ws.listen((mensagem) {
        recebidas.add('$mensagem');
        if ('$mensagem'.contains('"token"')) {
          ws.add(
            jsonEncode({
              'type': 'ready',
              'data': {'user_id': 'u1', 'role': 'passenger'},
              'at': 1.0,
            }),
          );
          ws.add(
            jsonEncode({
              'type': 'no_rider',
              'data': {'ride_id': 'r1'},
              'at': 2.0,
            }),
          );
        }
      });
      if (pararDeLer)
        leitura.pause(); // não responde a nada, nem ao ping do protocolo
    });
  }

  Uri get base => Uri.parse('http://127.0.0.1:${http.port}');

  Future<void> encerrar() async {
    for (final ws in conexoes) {
      await ws.close();
    }
    await http.close(force: true);
  }
}

void main() {
  test(
    'conexão padrão: manda o token, recebe ready e avisos de verdade',
    () async {
      final servidor = ServidorDeVerdade();
      await servidor.iniciar();
      final cliente = RealtimeClient(
        baseUrl: servidor.base,
        tokenProvider: () => 'tok-real',
      );
      final avisos = <ServerEvent>[];
      cliente.events.listen(avisos.add);
      final pronto = cliente.status
          .firstWhere((s) => s == RealtimeStatus.ready)
          .timeout(const Duration(seconds: 5));
      cliente.start();
      await pronto;
      await Future<void>.delayed(const Duration(milliseconds: 100));
      expect(jsonDecode(servidor.recebidas.first), {'token': 'tok-real'});
      expect(avisos.single.type, 'no_rider');
      await cliente.close();
      await servidor.encerrar();
    },
  );

  test('conexão meio aberta (o servidor para de responder) é percebida pelo ping do protocolo e reconectada', () async {
    final servidor = ServidorDeVerdade()..pararDeLer = true;
    await servidor.iniciar();
    final cliente = RealtimeClient(
      baseUrl: servidor.base,
      tokenProvider: () => 'tok',
      pingEvery: const Duration(milliseconds: 100),
      backoff: const [Duration(milliseconds: 10)],
    )..start();
    final antes = DateTime.now();
    while (servidor.conexoes.length < 2 &&
        DateTime.now().difference(antes) < const Duration(seconds: 5)) {
      await Future<void>.delayed(const Duration(milliseconds: 25));
    }
    expect(
      servidor.conexoes.length,
      greaterThanOrEqualTo(2),
      reason: 'o cliente devia ter largado a conexão muda e aberto outra',
    );
    await cliente.close();
    await servidor.encerrar();
  });
}
