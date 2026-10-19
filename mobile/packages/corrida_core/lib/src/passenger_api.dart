import 'api_client.dart';
import 'models/common.dart';
import 'models/passenger.dart';

/// Resposta de `POST /v1/passenger/fees/pay`: o saldo cobriu tudo, ou há um Pix a pagar.
class PayFeeResult {
  const PayFeeResult({required this.paid, this.charge});

  final bool paid;
  final Charge? charge;
}

/// As rotas do passageiro (`docs/api-v1.md`, seção "Passageiro").
class PassengerApi {
  PassengerApi(this.client);

  final ApiClient client;

  static String _id(String value) => Uri.encodeComponent(value);

  Json _map(Object? reply) => asMap(reply) ?? const {};

  Future<PassengerState> state() async =>
      PassengerState.fromJson(_map(await client.get('/v1/passenger/state')));

  Future<Quote> quote(Place pickup, Place destination) async => Quote.fromJson(
    _map(
      await client.post(
        '/v1/passenger/quotes',
        body: {'pickup': pickup.toJson(), 'destination': destination.toJson()},
      ),
    ),
  );

  /// [method]: `pix`, `cash` ou `balance` (corrida Pix paga com o saldo, só se a cotação ofereceu).
  Future<PassengerRide> requestRide({
    required String quoteId,
    required String method,
  }) async => PassengerRide.fromJson(
    _map(
      await client.post(
        '/v1/passenger/rides',
        body: {'quote_id': quoteId, 'method': method},
      ),
    ),
  );

  Future<CancelResult> cancel(String rideId) async => CancelResult.fromJson(
    _map(await client.post('/v1/passenger/rides/${_id(rideId)}/cancel')),
  );

  Future<PayFeeResult> payFee() async {
    final reply = _map(await client.post('/v1/passenger/fees/pay'));
    if (reply['paid'] == true) return const PayFeeResult(paid: true);
    return PayFeeResult(paid: false, charge: Charge.fromJson(reply));
  }

  Future<void> appealFee(String rideId, String text) async {
    await client.post(
      '/v1/passenger/rides/${_id(rideId)}/fee/appeal',
      body: {'text': text},
    );
  }

  Future<Charge> topup(int amountCents) async => Charge.fromJson(
    _map(
      await client.post(
        '/v1/passenger/balance/topup',
        body: {'amount_cents': amountCents},
      ),
    ),
  );

  Future<Withdrawal> withdraw({
    required int amountCents,
    required String pixKey,
  }) async => Withdrawal.fromJson(
    _map(
      await client.post(
        '/v1/passenger/balance/withdraw',
        body: {'amount_cents': amountCents, 'pix_key': pixKey},
      ),
    ),
  );

  Future<void> setEmergencyContact({
    required String name,
    required String phone,
  }) async {
    await client.put(
      '/v1/passenger/emergency-contact',
      body: {'name': name, 'phone': phone},
    );
  }

  /// Vale para os dois lados, depois que a corrida acabou.
  Future<void> rate(String rideId, int stars) async {
    await client.post(
      '/v1/rides/${_id(rideId)}/rating',
      body: {'stars': stars},
    );
  }

  Future<SosResult> sos(String rideId) async => SosResult.fromJson(
    _map(await client.post('/v1/rides/${_id(rideId)}/sos')),
  );

  /// "Está tudo bem" ao aviso automático de segurança.
  Future<void> safetyOk(String rideId, int alertId) async {
    await client.post('/v1/rides/${_id(rideId)}/safety/$alertId/ok');
  }

  Future<Charge> charge(String chargeId) async =>
      Charge.fromJson(_map(await client.get('/v1/charges/${_id(chargeId)}')));
}
