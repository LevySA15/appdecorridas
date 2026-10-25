import 'dart:async';

import 'package:corrida_core/corrida_core.dart';
import 'package:flutter/foundation.dart';

/// A ponte única entre as telas e o pacote `corrida_core`: guarda a sessão, o último estado lido do
/// servidor e a conexão de tempo real. As telas nunca importam `RiderApi`/`RealtimeClient` direto.
class RiderController extends ChangeNotifier {
  // ignore: prefer_initializing_formals
  RiderController({
    required this.authApi,
    required SessionManager session,
    required this.api,
    required this.realtimeBaseUrl,
    this.realtimeConnector,
  }) : sessionManager = session {
    _sessionSub = sessionManager.changes.listen(_onSessionChanged);
  }

  final AuthApi authApi;
  // o parâmetro chama-se `session` (o nome que o chamador usa) porque o getter público `session` já é
  // o valor atual da sessão, não o `SessionManager` que a guarda.
  final SessionManager sessionManager;
  final RiderApi api;
  final Uri realtimeBaseUrl;
  final WebSocketConnector? realtimeConnector;

  late final StreamSubscription<Session?> _sessionSub;
  final _eventsOut = StreamController<ServerEvent>.broadcast();
  RealtimeClient? _realtime;
  StreamSubscription<ServerEvent>? _realtimeEventsSub;
  StreamSubscription<void>? _realtimeResyncSub;

  var _starting = true;
  RiderState? _state;

  bool get starting => _starting;
  Session? get session => sessionManager.current;
  RiderState? get state => _state;
  Stream<ServerEvent> get events => _eventsOut.stream;

  Future<void> start() async {
    final restored = await sessionManager.restore();
    if (restored != null) {
      _connectRealtime();
      await refreshState();
    }
    _starting = false;
    notifyListeners();
  }

  Future<void> requestCode(String phone) => authApi.requestCode(phone);

  Future<void> verify({required String phone, required String code}) async {
    await sessionManager.signIn(phone: phone, code: code, role: 'rider');
    _connectRealtime();
    await refreshState();
  }

  Future<void> signOut() async {
    await _disconnectRealtime();
    await sessionManager.signOut();
    _state = null;
    notifyListeners();
  }

  Future<void> refreshState() async {
    _state = await api.state();
    notifyListeners();
  }

  /// Faz uma ação no servidor e relê o estado. Se o servidor recusar (a oferta venceu, a corrida mudou),
  /// relê o estado mesmo assim antes de repassar o erro: a tela não pode ficar com a oferta velha.
  Future<T> _act<T>(Future<T> Function() call) async {
    final T result;
    try {
      result = await call();
    } on ApiException {
      await _quietRefresh();
      rethrow;
    }
    await refreshState();
    return result;
  }

  Future<void> goOnline() => _act(api.goOnline);

  Future<void> goOffline() => _act(api.goOffline);

  Future<RiderRide> accept(String rideId) => _act(() => api.accept(rideId));

  Future<void> decline(String rideId) => _act(() => api.decline(rideId));

  Future<void> arrive(String rideId) => _act(() => api.arrive(rideId));

  Future<void> confirmHelmet(String rideId) =>
      _act(() => api.confirmHelmet(rideId));

  Future<void> startTrip(String rideId, String pin) =>
      _act(() => api.start(rideId, pin));

  Future<void> completeTrip(String rideId) => _act(() => api.complete(rideId));

  Future<void> cashReceived(String rideId) =>
      _act(() => api.cashReceived(rideId));

  /// Avalia o passageiro. Não relê o estado: a corrida terminada já saiu dele.
  Future<void> rate({required String rideId, required int stars}) =>
      api.rate(rideId, stars);

  Future<Charge> entryCharge() => api.entryCharge();

  Future<Charge> debtCharge() => api.debtCharge();

  Future<Charge> loadCharge(String chargeId) => api.charge(chargeId);

  void _connectRealtime() {
    final realtime = RealtimeClient(
      baseUrl: realtimeBaseUrl,
      tokenProvider: () => sessionManager.current!.token,
      connector: realtimeConnector,
    );
    _realtime = realtime;
    _realtimeEventsSub = realtime.events.listen((event) {
      _eventsOut.add(event);
      unawaited(_quietRefresh());
    });
    _realtimeResyncSub = realtime.resync.listen((_) {
      unawaited(_quietRefresh());
    });
    realtime.start();
  }

  Future<void> _disconnectRealtime() async {
    await _realtimeEventsSub?.cancel();
    await _realtimeResyncSub?.cancel();
    _realtimeEventsSub = null;
    _realtimeResyncSub = null;
    final realtime = _realtime;
    _realtime = null;
    if (realtime != null) await realtime.close();
  }

  /// Releitura automática disparada por um aviso de tempo real: um erro de rede não derruba o app, o
  /// próximo aviso tenta de novo.
  Future<void> _quietRefresh() async {
    try {
      await refreshState();
    } on Exception {
      // sem rede ou servidor fora do ar: ignora, o próximo aviso tenta de novo
    }
  }

  void _onSessionChanged(Session? session) {
    if (session == null) {
      unawaited(_disconnectRealtime());
      _state = null;
      notifyListeners();
    }
  }

  @override
  void dispose() {
    unawaited(_sessionSub.cancel());
    unawaited(_disconnectRealtime());
    unawaited(_eventsOut.close());
    super.dispose();
  }
}
