import 'dart:async';
import 'dart:convert';

import 'package:corrida_core/corrida_core.dart';
import 'package:stream_channel/stream_channel.dart';
import 'package:test/test.dart';
import 'package:web_socket_channel/web_socket_channel.dart';

class FakeSink implements WebSocketSink {
  final enviado = <Object?>[];
  var fechado = false;
  int? codigoDeFechamento;
  final _done = Completer<void>();

  @override
  void add(Object? data) => enviado.add(data);

  @override
  void addError(Object error, [StackTrace? stackTrace]) {}

  @override
  Future<void> addStream(Stream<Object?> stream) => stream.forEach(add);

  @override
  Future<void> close([int? closeCode, String? closeReason]) async {
    fechado = true;
    codigoDeFechamento = closeCode;
    if (!_done.isCompleted) _done.complete();
  }

  @override
  Future<void> get done => _done.future;
}

class FakeChannel extends StreamChannelMixin<Object?>
    implements WebSocketChannel {
  FakeChannel(
    this.uri, {
    bool falhaAoConectar = false,
    bool nuncaConecta = false,
  }) {
    if (nuncaConecta) {
      // o handshake nunca termina
    } else if (falhaAoConectar) {
      _ready.completeError(StateError('recusou'));
      unawaited(_ready.future.catchError((Object _) {}));
    } else {
      _ready.complete();
    }
  }

  final Uri uri;
  final _entrada = StreamController<Object?>();
  final _ready = Completer<void>();
  @override
  final FakeSink sink = FakeSink();
  @override
  int? closeCode;

  /// O servidor manda um texto.
  void servidorManda(Object? dado) => _entrada.add(dado);

  void servidorMandaAviso(
    String type, [
    Map<String, Object?>? data,
    double at = 1.0,
  ]) => servidorManda(jsonEncode({'type': type, 'data': data, 'at': at}));

  Future<void> servidorFecha(int? codigo) async {
    closeCode = codigo;
    await _entrada.close();
  }

  @override
  Stream<Object?> get stream => _entrada.stream;

  @override
  Future<void> get ready => _ready.future;

  @override
  String? get protocol => null;

  @override
  String? get closeReason => null;
}

class Mundo {
  Mundo({
    String base = 'http://s.teste',
    Duration pingEvery = const Duration(minutes: 5),
    Duration connectTimeout = const Duration(seconds: 10),
    this.tokens = const ['tok-1'],
  }) {
    cliente = RealtimeClient(
      baseUrl: Uri.parse(base),
      tokenProvider: () => tokens[(tokenIndex++).clamp(0, tokens.length - 1)],
      connector: (uri) {
        final canal = FakeChannel(
          uri,
          falhaAoConectar: falharAs.contains(canais.length),
          nuncaConecta: travarAs.contains(canais.length),
        );
        canais.add(canal);
        return canal;
      },
      pingEvery: pingEvery,
      connectTimeout: connectTimeout,
      delay: (d) {
        esperas.add(d);
        return pausa?.future ?? Future<void>.value();
      },
    );
    cliente.events.listen(avisos.add);
    cliente.status.listen(estados.add);
    cliente.resync.listen((_) => releituras++);
  }

  late final RealtimeClient cliente;
  final List<String> tokens;
  var tokenIndex = 0;
  final canais = <FakeChannel>[];
  final avisos = <ServerEvent>[];
  final estados = <RealtimeStatus>[];
  final esperas = <Duration>[];
  final falharAs = <int>{};
  final travarAs = <int>{};
  Completer<void>? pausa;
  var releituras = 0;
}

Future<void> deixaRodar() =>
    Future<void>.delayed(const Duration(milliseconds: 20));

void main() {
  test('manda o token na primeira mensagem e nunca na url', () async {
    final m = Mundo()..cliente.start();
    await deixaRodar();
    expect(m.canais.single.uri.toString(), 'ws://s.teste/v1/ws');
    expect(m.canais.single.uri.toString(), isNot(contains('tok-1')));
    expect(jsonDecode(m.canais.single.sink.enviado.first! as String), {
      'token': 'tok-1',
    });
    await m.cliente.close();
  });

  test('url https vira wss e respeita o caminho base', () async {
    final m = Mundo(base: 'https://corrida.exemplo.com.br/api/')
      ..cliente.start();
    await deixaRodar();
    expect(
      m.canais.single.uri.toString(),
      'wss://corrida.exemplo.com.br/api/v1/ws',
    );
    await m.cliente.close();
  });

  test('ready muda o status e pede para reler o estado', () async {
    final m = Mundo()..cliente.start();
    await deixaRodar();
    expect(m.cliente.currentStatus, RealtimeStatus.connecting);
    m.canais.single.servidorMandaAviso('ready', {
      'user_id': 'u1',
      'role': 'passenger',
    });
    await deixaRodar();
    expect(m.cliente.currentStatus, RealtimeStatus.ready);
    expect(m.estados, [RealtimeStatus.connecting, RealtimeStatus.ready]);
    expect(m.releituras, 1);
    expect(m.avisos, isEmpty);
    await m.cliente.close();
  });

  test('avisos viram ServerEvent', () async {
    final m = Mundo()..cliente.start();
    await deixaRodar();
    m.canais.single.servidorMandaAviso('ready');
    m.canais.single.servidorMandaAviso('rider_accepted', {
      'ride_id': 'ride-1',
      'pin': '4821',
    }, 1800000000.5);
    await deixaRodar();
    final aviso = m.avisos.single;
    expect(
      (aviso.type, aviso.data['ride_id'], aviso.data['pin'], aviso.at),
      ('rider_accepted', 'ride-1', '4821', 1800000000.5),
    );
    await m.cliente.close();
  });

  test('mensagem que não é json ou não é aviso é ignorada', () async {
    final m = Mundo()..cliente.start();
    await deixaRodar();
    final canal = m.canais.single;
    canal.servidorManda('isso não é json');
    canal.servidorManda('"texto"');
    canal.servidorManda('[1,2]');
    canal.servidorManda('{"sem_tipo": 1}');
    canal.servidorManda(<int>[1, 2, 3]);
    canal.servidorManda(null);
    canal.servidorMandaAviso('no_rider', {'ride_id': 'r'});
    await deixaRodar();
    expect(m.avisos.map((a) => a.type), ['no_rider']);
    await m.cliente.close();
  });

  test('aviso sem data vira mapa vazio', () async {
    final m = Mundo()..cliente.start();
    await deixaRodar();
    m.canais.single.servidorManda('{"type": "entry_paid", "at": 2.0}');
    await deixaRodar();
    expect(m.avisos.single.data, isEmpty);
    await m.cliente.close();
  });

  test('ping periódico', () async {
    final m = Mundo(pingEvery: const Duration(milliseconds: 30))
      ..cliente.start();
    await Future<void>.delayed(const Duration(milliseconds: 110));
    final pings = m.canais.single.sink.enviado.where((x) => x == 'ping').length;
    expect(pings, greaterThanOrEqualTo(2));
    await m.cliente.close();
  });

  test(
    'cai e reconecta com recuo crescente, e o recuo zera depois do ready',
    () async {
      final m = Mundo()..falharAs.addAll({0, 1, 2});
      m.cliente.start();
      await deixaRodar();
      // as três primeiras tentativas falham ao conectar; a quarta conecta
      expect(m.canais.length, 4);
      expect(m.esperas, [
        const Duration(seconds: 1),
        const Duration(seconds: 2),
        const Duration(seconds: 4),
      ]);
      m.canais.last.servidorMandaAviso('ready');
      await deixaRodar();
      await m.canais.last.servidorFecha(1006);
      await deixaRodar();
      expect(m.canais.length, 5);
      expect(
        m.esperas.last,
        const Duration(seconds: 1),
      ); // zerou depois do ready
      expect(m.cliente.currentStatus, RealtimeStatus.reconnecting);
      await m.cliente.close();
    },
  );

  test('o recuo não passa do último valor da lista', () async {
    final m = Mundo()..falharAs.addAll({0, 1, 2, 3, 4, 5, 6});
    m.cliente.start();
    await deixaRodar();
    expect(m.esperas.take(7).toList(), [
      const Duration(seconds: 1),
      const Duration(seconds: 2),
      const Duration(seconds: 4),
      const Duration(seconds: 8),
      const Duration(seconds: 15),
      const Duration(seconds: 15),
      const Duration(seconds: 15),
    ]);
    await m.cliente.close();
  });

  test('reconectar pede para reler o estado de novo', () async {
    final m = Mundo()..cliente.start();
    await deixaRodar();
    m.canais.last.servidorMandaAviso('ready');
    await deixaRodar();
    await m.canais.last.servidorFecha(1006);
    await deixaRodar();
    m.canais.last.servidorMandaAviso('ready');
    await deixaRodar();
    expect(m.releituras, 2);
    expect(m.cliente.currentStatus, RealtimeStatus.ready);
    await m.cliente.close();
  });

  test('4401 para e avisa sem reconectar', () async {
    final m = Mundo()..cliente.start();
    await deixaRodar();
    await m.canais.single.servidorFecha(4401);
    await deixaRodar();
    expect(m.cliente.currentStatus, RealtimeStatus.unauthorized);
    expect(m.canais.length, 1);
    expect(m.esperas, isEmpty);
    await m.cliente.close();
  });

  test('4408 reconecta', () async {
    final m = Mundo()..cliente.start();
    await deixaRodar();
    await m.canais.single.servidorFecha(4408);
    await deixaRodar();
    expect(m.canais.length, 2);
    await m.cliente.close();
  });

  test('close não emite mais nada e cancela a tentativa pendente', () async {
    final m = Mundo()
      ..pausa = Completer<void>()
      ..falharAs.add(0);
    m.cliente.start();
    await deixaRodar();
    expect(m.esperas, hasLength(1)); // está esperando para tentar de novo
    await m.cliente.close();
    final quantosEstados = m.estados.length;
    m.pausa!
        .complete(); // a espera acabaria agora, mas o cliente já foi fechado
    await deixaRodar();
    expect(m.canais.length, 1);
    expect(m.estados.length, quantosEstados);
    expect(m.cliente.currentStatus, RealtimeStatus.closed);
  });

  test(
    'close encerra o canal aberto e ignora avisos que chegam depois',
    () async {
      final m = Mundo()..cliente.start();
      await deixaRodar();
      final canal = m.canais.single;
      await m.cliente.close();
      expect(canal.sink.fechado, isTrue);
      canal.servidorMandaAviso('no_rider', {'ride_id': 'r'});
      await deixaRodar();
      expect(m.avisos, isEmpty);
      expect(m.cliente.currentStatus, RealtimeStatus.closed);
    },
  );

  test('usa o token novo a cada tentativa', () async {
    final m = Mundo(tokens: ['velho', 'novo'])..cliente.start();
    await deixaRodar();
    expect(jsonDecode(m.canais[0].sink.enviado.first! as String), {
      'token': 'velho',
    });
    await m.canais[0].servidorFecha(1006);
    await deixaRodar();
    expect(jsonDecode(m.canais[1].sink.enviado.first! as String), {
      'token': 'novo',
    });
    await m.cliente.close();
  });

  test('start duas vezes não abre duas conexões', () async {
    final m = Mundo()
      ..cliente.start()
      ..cliente.start();
    await deixaRodar();
    expect(m.canais.length, 1);
    await m.cliente.close();
  });

  test('conexão que não completa dentro do prazo é fechada e a tentativa seguinte vem depois do recuo', () async {
    final m = Mundo(connectTimeout: const Duration(milliseconds: 30))
      ..travarAs.add(0);
    m.cliente.start();
    await Future<void>.delayed(const Duration(milliseconds: 120));
    expect(m.canais.first.sink.fechado, isTrue);
    expect(m.canais.length, 2);
    expect(m.esperas.first, const Duration(seconds: 1));
    await m.cliente.close();
  });

  test(
    'close durante a tentativa que não completa fecha o canal pendurado',
    () async {
      final m = Mundo()..travarAs.add(0);
      m.cliente.start();
      await deixaRodar();
      await m.cliente.close();
      expect(m.canais.single.sink.fechado, isTrue);
    },
  );

  test('lista de recuo vazia é recusada na criação', () {
    expect(
      () => RealtimeClient(
        baseUrl: Uri.parse('http://x'),
        tokenProvider: () => 't',
        backoff: const [],
      ),
      throwsArgumentError,
    );
  });

  test(
    'sem delay de teste, close cancela a espera real da próxima tentativa',
    () async {
      final canais = <FakeChannel>[];
      final cliente = RealtimeClient(
        baseUrl: Uri.parse('http://s.teste'),
        tokenProvider: () => 't',
        connector: (uri) {
          final canal = FakeChannel(uri, falhaAoConectar: true);
          canais.add(canal);
          return canal;
        },
        backoff: const [Duration(milliseconds: 60)],
      )..start();
      await Future<void>.delayed(const Duration(milliseconds: 20));
      expect(canais.length, 1);
      await cliente.close();
      await Future<void>.delayed(const Duration(milliseconds: 120));
      expect(
        canais.length,
        1,
      ); // a espera de 60 ms foi cancelada: não tentou de novo
    },
  );
}
