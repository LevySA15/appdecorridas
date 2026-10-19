import 'api_client.dart';
import 'models/common.dart';
import 'models/rider.dart';

/// As rotas do motoqueiro (`docs/api-v1.md`, seção "Motoqueiro").
class RiderApi {
  RiderApi(this.client);

  final ApiClient client;

  static String _id(String value) => Uri.encodeComponent(value);

  Json _map(Object? reply) => asMap(reply) ?? const {};

  Future<RiderState> state() async =>
      RiderState.fromJson(_map(await client.get('/v1/rider/state')));

  /// Fica disponível. Recusado com 409 e um destes códigos: not_approved, blocked, documents_expired,
  /// entry_pending, debt_pending.
  Future<void> goOnline() async {
    await client.post('/v1/rider/online');
  }

  Future<void> goOffline() async {
    await client.post('/v1/rider/offline');
  }

  /// A cada ~4 segundos enquanto disponível e durante a corrida.
  Future<void> sendPosition(double lat, double lng) async {
    await client.post('/v1/rider/position', body: {'lat': lat, 'lng': lng});
  }

  Future<RiderRide> accept(String rideId) async => RiderRide.fromJson(
    _map(await client.post('/v1/rider/offers/${_id(rideId)}/accept')),
  );

  Future<void> decline(String rideId) async {
    await client.post('/v1/rider/offers/${_id(rideId)}/decline');
  }

  Future<RiderRide> _step(String rideId, String step, {Object? body}) async =>
      RiderRide.fromJson(
        _map(
          await client.post('/v1/rider/rides/${_id(rideId)}/$step', body: body),
        ),
      );

  Future<RiderRide> arrive(String rideId) => _step(rideId, 'arrive');

  Future<RiderRide> confirmHelmet(String rideId) => _step(rideId, 'helmet');

  /// Começa a corrida com o código de 4 dígitos que o passageiro diz. Código errado: 422 `wrong_pin`.
  Future<RiderRide> start(String rideId, String pin) =>
      _step(rideId, 'start', body: {'pin': pin});

  Future<RiderRide> complete(String rideId) => _step(rideId, 'complete');

  /// "Recebi o dinheiro na mão."
  Future<void> cashReceived(String rideId) async {
    await client.post('/v1/rider/rides/${_id(rideId)}/cash-received');
  }

  /// Avalia o passageiro depois que a corrida acabou (mesma rota que o passageiro usa para avaliar o motoqueiro).
  Future<void> rate(String rideId, int stars) async {
    await client.post(
      '/v1/rides/${_id(rideId)}/rating',
      body: {'stars': stars},
    );
  }

  Future<Charge> entryCharge() async =>
      Charge.fromJson(_map(await client.post('/v1/rider/entry-charge')));

  Future<Charge> debtCharge() async =>
      Charge.fromJson(_map(await client.post('/v1/rider/debt-charge')));

  /// Envia a foto crua (JPEG, PNG ou WebP, até 8 MB; maior que isso o servidor responde 413 `file_too_large`).
  Future<UploadedDocument> uploadDocument(
    DocKind kind,
    List<int> bytes, {
    required String contentType,
    Duration? timeout,
  }) async => UploadedDocument.fromJson(
    _map(
      timeout == null
          ? await client.putBytes(
              '/v1/rider/documents/${kind.name}',
              bytes,
              contentType: contentType,
            )
          : await client.putBytes(
              '/v1/rider/documents/${kind.name}',
              bytes,
              contentType: contentType,
              timeout: timeout,
            ),
    ),
  );

  Future<void> register(RiderRegistrationForm form) async {
    await client.post('/v1/rider/register', body: form.toJson());
  }

  Future<void> renewDocuments({
    required DateTime cnhExpiresOn,
    required DateTime crlvExpiresOn,
    String? cnhPhotoKey,
    String? crlvKey,
  }) async {
    final body = <String, Object?>{
      'cnh_expires_on': formatDay(cnhExpiresOn),
      'crlv_expires_on': formatDay(crlvExpiresOn),
    };
    if (cnhPhotoKey != null) body['cnh_photo_key'] = cnhPhotoKey;
    if (crlvKey != null) body['crlv_key'] = crlvKey;
    await client.post('/v1/rider/documents/renew', body: body);
  }
}
