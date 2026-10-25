import 'dart:async';

import 'package:corrida_core/corrida_core.dart';
import 'package:corrida_ui/corrida_ui.dart' show cityCenter;
import 'package:flutter/foundation.dart';

import 'photo_source.dart';
import 'registration_data.dart';

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
    PhotoSource? photos,
    this.positionEvery = const Duration(seconds: 4),
  }) : sessionManager = session,
       photos = photos ?? ImagePickerPhotoSource() {
    _sessionSub = sessionManager.changes.listen(_onSessionChanged);
  }

  final AuthApi authApi;
  // o parâmetro chama-se `session` (o nome que o chamador usa) porque o getter público `session` já é
  // o valor atual da sessão, não o `SessionManager` que a guarda.
  final SessionManager sessionManager;
  final RiderApi api;
  final Uri realtimeBaseUrl;
  final WebSocketConnector? realtimeConnector;
  final PhotoSource photos;
  final Duration positionEvery;

  late final StreamSubscription<Session?> _sessionSub;
  final _eventsOut = StreamController<ServerEvent>.broadcast();
  RealtimeClient? _realtime;
  StreamSubscription<ServerEvent>? _realtimeEventsSub;
  StreamSubscription<void>? _realtimeResyncSub;

  var _starting = true;
  var _position = cityCenter;
  Timer? _positionTimer;

  /// A chave que o servidor deu a cada foto já enviada, junto com a foto (por identidade): se o cadastro
  /// falha no meio, o segundo toque não sobe de novo o que já subiu (o servidor limita os envios por hora).
  final _uploaded = <DocKind, ({Photo photo, String key})>{};
  RiderState? _state;

  bool get starting => _starting;
  Session? get session => sessionManager.current;
  RiderState? get state => _state;
  Stream<ServerEvent> get events => _eventsOut.stream;

  /// Onde o motoqueiro está no mapa de mentira (começa no centro da cidade).
  Place get position => _position;

  /// Muda a posição de mentira; ela vai para o servidor no próximo ciclo de envio.
  void moveTo(Place place) {
    _position = place;
    notifyListeners();
  }

  Future<void> start() async {
    final restored = await sessionManager.restore();
    if (restored != null) {
      _connectRealtime();
      // Sem internet ao abrir: o app termina de iniciar sem estado (a tela pede para tentar de novo) e o
      // tempo real traz o estado quando a rede voltar.
      await _quietRefresh();
    }
    _starting = false;
    notifyListeners();
  }

  Future<void> requestCode(String phone) => authApi.requestCode(phone);

  Future<void> verify({required String phone, required String code}) async {
    await sessionManager.signIn(phone: phone, code: code, role: 'rider');
    _connectRealtime();
    await _quietRefresh();
    notifyListeners(); // a tela sai do login mesmo que o estado ainda não tenha vindo
  }

  Future<void> signOut() async {
    await _disconnectRealtime();
    await sessionManager.signOut();
    _state = null;
    _stopPosition();
    notifyListeners();
  }

  Future<void> refreshState() async {
    _state = await api.state();
    _syncPosition();
    notifyListeners();
  }

  /// Enviar a posição (a cada [positionEvery]) só enquanto o motoqueiro está disponível ou numa corrida:
  /// parado e sem corrida ele não entra no mapa do servidor.
  void _syncPosition() {
    final state = _state;
    final shouldSend =
        sessionManager.current != null &&
        state != null &&
        (state.registration.online || state.ride != null);
    if (!shouldSend) {
      _stopPosition();
      return;
    }
    if (_positionTimer != null) return;
    unawaited(_sendPosition());
    _positionTimer = Timer.periodic(
      positionEvery,
      (_) => unawaited(_sendPosition()),
    );
  }

  void _stopPosition() {
    _positionTimer?.cancel();
    _positionTimer = null;
  }

  Future<void> _sendPosition() async {
    try {
      await api.sendPosition(_position.lat, _position.lng);
    } on Exception {
      // sem rede ou servidor fora do ar: o próximo ciclo tenta de novo (o 401 o ApiClient já trata)
    }
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
    // A ação já deu certo no servidor: se só a releitura falhar (rede ruim), não pode parecer que a ação
    // falhou. O próximo aviso do tempo real traz o estado.
    await _quietRefresh();
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

  /// O extrato de um dia (a rota tem o dia no formato AAAA-MM-DD).
  Future<RiderStatement> loadStatement(DateTime day) => api.statement(day: day);

  Future<Charge> entryCharge() => api.entryCharge();

  Future<Charge> debtCharge() => api.debtCharge();

  Future<Charge> loadCharge(String chargeId) => api.charge(chargeId);

  Future<Photo?> pickPhoto(DocKind kind) => photos.pick(kind);

  Future<String> _keyFor(DocKind kind, Photo photo) async {
    final known = _uploaded[kind];
    if (known != null && identical(known.photo, photo)) return known.key;
    final uploaded = await api.uploadDocument(
      kind,
      photo.bytes,
      contentType: photo.contentType,
    );
    _uploaded[kind] = (photo: photo, key: uploaded.key);
    return uploaded.key;
  }

  /// Envia as três fotos (selfie, CNH, documento da moto) e depois o cadastro.
  Future<void> registerRider(RegistrationData data) async {
    Photo photoOf(DocKind kind) =>
        data.photos[kind] ??
        (throw ArgumentError('falta a foto: ${kind.name}'));
    final selfieKey = await _keyFor(DocKind.selfie, photoOf(DocKind.selfie));
    final cnhKey = await _keyFor(DocKind.cnh, photoOf(DocKind.cnh));
    final crlvKey = await _keyFor(DocKind.crlv, photoOf(DocKind.crlv));
    await api.register(
      RiderRegistrationForm(
        name: data.name,
        cpf: data.cpf,
        cnhNumber: data.cnhNumber,
        plate: data.plate,
        motoModel: data.motoModel,
        selfieKey: selfieKey,
        cnhPhotoKey: cnhKey,
        crlvKey: crlvKey,
        cnhExpiresOn: data.cnhExpiresOn,
        crlvExpiresOn: data.crlvExpiresOn,
      ),
    );
    _uploaded.clear();
    await _quietRefresh();
  }

  /// Novas validades e, se houver, as fotos novas (só as dadas são enviadas).
  Future<void> renewDocuments({
    required DateTime cnhExpiresOn,
    required DateTime crlvExpiresOn,
    Photo? cnhPhoto,
    Photo? crlvPhoto,
  }) async {
    final cnhKey = cnhPhoto == null
        ? null
        : await _keyFor(DocKind.cnh, cnhPhoto);
    final crlvKey = crlvPhoto == null
        ? null
        : await _keyFor(DocKind.crlv, crlvPhoto);
    await api.renewDocuments(
      cnhExpiresOn: cnhExpiresOn,
      crlvExpiresOn: crlvExpiresOn,
      cnhPhotoKey: cnhKey,
      crlvKey: crlvKey,
    );
    _uploaded.clear();
    await _quietRefresh();
  }

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
      _stopPosition();
      notifyListeners();
    }
  }

  @override
  void dispose() {
    _stopPosition();
    unawaited(_sessionSub.cancel());
    unawaited(_disconnectRealtime());
    unawaited(_eventsOut.close());
    super.dispose();
  }
}
