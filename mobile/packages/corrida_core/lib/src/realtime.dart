import 'dart:async';
import 'dart:convert';

import 'package:web_socket_channel/web_socket_channel.dart';

import 'models/common.dart';

/// Um aviso do servidor (`docs/api-v1.md`, "Tempo real"). Os avisos são dicas: a fonte da verdade é o `state`.
class ServerEvent {
  const ServerEvent({required this.type, required this.data, required this.at});

  final String type;
  final Json data;
  final double at;
}

enum RealtimeStatus {
  connecting,
  ready,
  reconnecting,
  closed,

  /// O servidor recusou o token (fechou com 4401): o app precisa pedir login de novo; não reconecta sozinho.
  unauthorized,
}

typedef WebSocketConnector = WebSocketChannel Function(Uri uri);

/// Conexão em tempo real (`/v1/ws`) com reconexão. A primeira mensagem é o token (nunca vai na URL). A cada `ready`
/// (inclusive depois de reconectar) [resync] avisa para reler o estado.
class RealtimeClient {
  RealtimeClient({
    required this.baseUrl,
    required this.tokenProvider,
    WebSocketConnector? connector,
    this.pingEvery = const Duration(seconds: 25),
    this.connectTimeout = const Duration(seconds: 10),
    this.backoff = const [
      Duration(seconds: 1),
      Duration(seconds: 2),
      Duration(seconds: 4),
      Duration(seconds: 8),
      Duration(seconds: 15),
    ],
    Future<void> Function(Duration)? delay,
  })  : _connector = connector ?? ((uri) => WebSocketChannel.connect(uri)),
        _delay = delay ?? Future<void>.delayed;

  final Uri baseUrl;
  final Duration pingEvery;
  final Duration connectTimeout;
  final List<Duration> backoff;
  /// Chamado a cada tentativa: o token pode ter mudado entre uma e outra.
  final String Function() tokenProvider;
  final WebSocketConnector _connector;
  final Future<void> Function(Duration) _delay;

  final _events = StreamController<ServerEvent>.broadcast();
  final _status = StreamController<RealtimeStatus>.broadcast();
  final _resync = StreamController<void>.broadcast();
  final _closedSignal = Completer<void>();

  var _started = false;
  var _closed = false;
  var _current = RealtimeStatus.connecting;
  WebSocketChannel? _channel;
  StreamSubscription<Object?>? _subscription;
  Timer? _pingTimer;

  Stream<ServerEvent> get events => _events.stream;

  Stream<RealtimeStatus> get status => _status.stream;

  /// Cada evento é um pedido para reler `GET /v1/*/state`.
  Stream<void> get resync => _resync.stream;

  RealtimeStatus get currentStatus => _current;

  Uri get _wsUri {
    final base = baseUrl.path.endsWith('/') ? baseUrl.path.substring(0, baseUrl.path.length - 1) : baseUrl.path;
    return Uri(
      scheme: baseUrl.scheme == 'https' ? 'wss' : 'ws',
      host: baseUrl.host,
      port: baseUrl.hasPort ? baseUrl.port : null,
      path: '$base/v1/ws',
    );
  }

  void start() {
    if (_started || _closed) return;
    _started = true;
    unawaited(_loop());
  }

  Future<void> close() async {
    if (_closed) return;
    _closed = true;
    _setStatus(RealtimeStatus.closed);
    if (!_closedSignal.isCompleted) _closedSignal.complete();
    _pingTimer?.cancel();
    await _subscription?.cancel();
    final channel = _channel;
    _channel = null;
    if (channel != null) {
      try {
        await channel.sink.close(1000).timeout(const Duration(seconds: 2));
      } on Exception {
        // fechar com o servidor fora do ar não precisa de cerimônia
      }
    }
    await _events.close();
    await _status.close();
    await _resync.close();
  }

  void _setStatus(RealtimeStatus status, {bool force = false}) {
    if (_current == status && !force && status != RealtimeStatus.closed) return;
    _current = status;
    if (!_status.isClosed) _status.add(status);
  }

  Future<void> _loop() async {
    var attempt = 0;
    var first = true;
    while (!_closed) {
      _setStatus(first ? RealtimeStatus.connecting : RealtimeStatus.reconnecting, force: first);
      first = false;
      final outcome = await _session();
      if (_closed) return;
      if (outcome.closeCode == 4401) {
        _setStatus(RealtimeStatus.unauthorized);
        return;
      }
      if (outcome.wasReady) attempt = 0;
      final wait = backoff[attempt < backoff.length ? attempt : backoff.length - 1];
      attempt++;
      await Future.any<void>([_delay(wait), _closedSignal.future]);
    }
  }

  /// Uma conexão, do começo ao fim. Devolve por que acabou e se chegou a ficar pronta.
  Future<({int? closeCode, bool wasReady})> _session() async {
    var wasReady = false;
    final WebSocketChannel channel;
    try {
      channel = _connector(_wsUri);
      _channel = channel;
      await channel.ready.timeout(connectTimeout);
      if (_closed) return (closeCode: null, wasReady: false);
      channel.sink.add(jsonEncode({'token': tokenProvider()}));
    } on Object {
      return (closeCode: null, wasReady: false);
    }
    _pingTimer = Timer.periodic(pingEvery, (_) {
      try {
        channel.sink.add('ping');
      } on Object {
        // a conexão está caindo; o laço principal trata
      }
    });
    final finished = Completer<void>();
    _subscription = channel.stream.listen(
      (message) {
        if (_closed) return;
        final event = _parse(message);
        if (event == null) return;
        if (event.type == 'ready') {
          wasReady = true;
          _setStatus(RealtimeStatus.ready);
          if (!_resync.isClosed) _resync.add(null);
          return;
        }
        if (!_events.isClosed) _events.add(event);
      },
      onError: (Object _) {
        if (!finished.isCompleted) finished.complete();
      },
      onDone: () {
        if (!finished.isCompleted) finished.complete();
      },
      cancelOnError: true,
    );
    await Future.any<void>([finished.future, _closedSignal.future]);
    _pingTimer?.cancel();
    final code = channel.closeCode;
    await _subscription?.cancel();
    _subscription = null;
    _channel = null;
    return (closeCode: code, wasReady: wasReady);
  }

  ServerEvent? _parse(Object? message) {
    if (message is! String) return null;
    final Object? decoded;
    try {
      decoded = jsonDecode(message);
    } on FormatException {
      return null;
    }
    final map = asMap(decoded);
    final type = asStringOrNull(map?['type']);
    if (map == null || type == null) return null;
    return ServerEvent(type: type, data: asMap(map['data']) ?? const {}, at: asDouble(map['at']));
  }
}
