import 'dart:async';

import 'package:corrida_core/corrida_core.dart';
import 'package:flutter/foundation.dart';

/// A ponte única entre as telas e o pacote `corrida_core`: guarda a sessão, o último estado lido do
/// servidor e a conexão de tempo real. As telas nunca importam `PassengerApi`/`RealtimeClient` direto.
class PassengerController extends ChangeNotifier {
  // ignore: prefer_initializing_formals
  PassengerController({
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
  final PassengerApi api;
  final Uri realtimeBaseUrl;
  final WebSocketConnector? realtimeConnector;

  late final StreamSubscription<Session?> _sessionSub;
  final _eventsOut = StreamController<ServerEvent>.broadcast();
  RealtimeClient? _realtime;
  StreamSubscription<ServerEvent>? _realtimeEventsSub;
  StreamSubscription<void>? _realtimeResyncSub;

  var _starting = true;
  PassengerState? _state;

  bool get starting => _starting;
  Session? get session => sessionManager.current;
  PassengerState? get state => _state;
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
    await sessionManager.signIn(phone: phone, code: code, role: 'passenger');
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

  Future<Quote> quote(Place pickup, Place destination) =>
      api.quote(pickup, destination);

  Future<void> requestRide({
    required String quoteId,
    required String method,
  }) async {
    await api.requestRide(quoteId: quoteId, method: method);
    await refreshState();
  }

  Future<CancelResult> cancelRide(String rideId) async {
    final result = await api.cancel(rideId);
    await refreshState();
    return result;
  }

  Future<PayFeeResult> payPendingFee() async {
    final result = await api.payFee();
    await refreshState();
    return result;
  }

  Future<void> appealFee(String rideId, String text) async {
    await api.appealFee(rideId, text);
    await refreshState();
  }

  Future<void> rate({required String rideId, required int stars}) =>
      api.rate(rideId, stars);

  Future<SosResult> sos(String rideId) => api.sos(rideId);

  Future<void> safetyOk(String rideId, int alertId) async {
    await api.safetyOk(rideId, alertId);
    await refreshState();
  }

  Future<Charge> topup(int amountCents) => api.topup(amountCents);

  Future<Withdrawal> withdraw({
    required int amountCents,
    required String pixKey,
  }) async {
    final result = await api.withdraw(
      amountCents: amountCents,
      pixKey: pixKey,
    );
    await refreshState();
    return result;
  }

  Future<void> setEmergencyContact({
    required String name,
    required String phone,
  }) async {
    await api.setEmergencyContact(name: name, phone: phone);
    await refreshState();
  }

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
