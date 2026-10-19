import 'common.dart';

class GeoPoint {
  const GeoPoint({required this.lat, required this.lng});

  final double lat;
  final double lng;

  factory GeoPoint.fromJson(Json json) =>
      GeoPoint(lat: asDouble(json['lat']), lng: asDouble(json['lng']));
}

/// O preço mostrado antes de pedir (`POST /v1/passenger/quotes`).
class Quote {
  const Quote({
    required this.quoteId,
    required this.priceCents,
    required this.distanceM,
    required this.durationS,
    required this.reason,
    required this.expiresAt,
    required this.pickup,
    required this.destination,
    required this.etaSeconds,
    required this.nearbyRiders,
    required this.paymentMethods,
  });

  final String quoteId;
  final int priceCents;
  final int distanceM;
  final int durationS;
  final String reason;
  final double expiresAt;
  final Place pickup;
  final Place destination;
  final int? etaSeconds; // null sem moto livre por perto
  final int nearbyRiders;
  final List<String> paymentMethods; // pix, cash e, se o saldo cobre, balance

  bool get canPayWithBalance => paymentMethods.contains('balance');

  factory Quote.fromJson(Json json) => Quote(
    quoteId: asString(json['quote_id']),
    priceCents: asInt(json['price_cents']),
    distanceM: asInt(json['distance_m']),
    durationS: asInt(json['duration_s']),
    reason: asString(json['reason']),
    expiresAt: asDouble(json['expires_at']),
    pickup: Place.fromJson(asMap(json['pickup']) ?? const {}),
    destination: Place.fromJson(asMap(json['destination']) ?? const {}),
    etaSeconds: asIntOrNull(json['eta_seconds']),
    nearbyRiders: asInt(json['nearby_riders']),
    paymentMethods: asStringList(json['payment_methods']),
  );
}

/// A ficha do motoqueiro que o passageiro vê.
class RiderCard {
  const RiderCard({
    required this.riderId,
    required this.name,
    required this.plate,
    required this.motoModel,
    required this.rating,
    required this.ratingCount,
    required this.photoUrl,
  });

  final String riderId;
  final String name;
  final String plate;
  final String motoModel;
  final double? rating;
  final int ratingCount;
  final String?
  photoUrl; // rota com login: GET /v1/riders/{id}/documents/selfie

  factory RiderCard.fromJson(Json json) => RiderCard(
    riderId: asString(json['rider_id']),
    name: asString(json['name']),
    plate: asString(json['plate']),
    motoModel: asString(json['moto_model']),
    rating: asDoubleOrNull(json['rating']),
    ratingCount: asInt(json['rating_count']),
    photoUrl: asStringOrNull(json['photo_url']),
  );
}

/// Pix de antes da corrida que ainda não foi pago.
class PixToPay {
  const PixToPay({
    required this.chargeId,
    required this.amountCents,
    required this.expiresAt,
  });

  final String chargeId;
  final int amountCents;
  final double expiresAt;

  factory PixToPay.fromJson(Json json) => PixToPay(
    chargeId: asString(json['charge_id']),
    amountCents: asInt(json['amount_cents']),
    expiresAt: asDouble(json['expires_at']),
  );
}

/// Até quando cancelar é grátis e quanto custaria cancelar agora.
class CancelInfo {
  const CancelInfo({required this.freeUntil, required this.feeCentsNow});

  final double freeUntil;
  final int feeCentsNow;

  factory CancelInfo.fromJson(Json json) => CancelInfo(
    freeUntil: asDouble(json['free_until']),
    feeCentsNow: asInt(json['fee_cents_now']),
  );
}

class QueueInfo {
  const QueueInfo({required this.finishingAt, required this.etaSeconds});

  final String finishingAt; // onde a moto termina a corrida de agora (texto)
  final int? etaSeconds;

  factory QueueInfo.fromJson(Json json) => QueueInfo(
    finishingAt: asString(json['finishing_at']),
    etaSeconds: asIntOrNull(json['eta_seconds']),
  );
}

/// Aviso automático de segurança que o passageiro ainda não respondeu.
class SafetyAlertRef {
  const SafetyAlertRef({required this.alertId, required this.kind});

  final int alertId;
  final String kind; // stopped | off_route | no_signal

  factory SafetyAlertRef.fromJson(Json json) => SafetyAlertRef(
    alertId: asInt(json['alert_id']),
    kind: asString(json['kind']),
  );
}

/// A corrida vista pelo passageiro.
class PassengerRide {
  const PassengerRide({
    required this.rideId,
    required this.state,
    this.queued = false,
    this.priceCents = 0,
    this.priceReason = '',
    this.method = '',
    this.pin = '',
    this.helmetConfirmed = false,
    this.pixPaid = false,
    this.payWithBalance = false,
    this.pickup = const Place(lat: 0, lng: 0),
    this.destination = const Place(lat: 0, lng: 0),
    this.distanceM = 0,
    this.rider,
    this.riderPosition,
    this.queue,
    this.safetyAlert,
    this.pay,
    this.endPayment,
    this.cancel,
  });

  final String rideId;
  final RideState state;
  final bool queued;
  final int priceCents;
  final String priceReason;
  final String
  method; // pix | cash (corrida paga com saldo também aparece como pix)
  final String pin; // os 4 dígitos que o passageiro diz ao motoqueiro
  final bool helmetConfirmed;
  final bool pixPaid;
  final bool payWithBalance;
  final Place pickup;
  final Place destination;
  final int distanceM;
  final RiderCard? rider;
  final GeoPoint? riderPosition;
  final QueueInfo? queue;
  final SafetyAlertRef? safetyAlert;
  final PixToPay? pay;
  final EndPayment? endPayment;
  final CancelInfo? cancel;

  factory PassengerRide.fromJson(Json json) => PassengerRide(
    rideId: asString(json['ride_id']),
    state: RideState.parse(asStringOrNull(json['state'])),
    queued: asBool(json['queued']),
    priceCents: asInt(json['price_cents']),
    priceReason: asString(json['price_reason']),
    method: asString(json['method']),
    pin: asString(json['pin']),
    helmetConfirmed: asBool(json['helmet_confirmed']),
    pixPaid: asBool(json['pix_paid']),
    payWithBalance: asBool(json['pay_with_balance']),
    pickup: Place.fromJson(asMap(json['pickup']) ?? const {}),
    destination: Place.fromJson(asMap(json['destination']) ?? const {}),
    distanceM: asInt(json['distance_m']),
    rider: mapOrNull(json['rider'], RiderCard.fromJson),
    riderPosition: mapOrNull(json['rider_position'], GeoPoint.fromJson),
    queue: mapOrNull(json['queue'], QueueInfo.fromJson),
    safetyAlert: mapOrNull(json['safety_alert'], SafetyAlertRef.fromJson),
    pay: mapOrNull(json['pay'], PixToPay.fromJson),
    endPayment: mapOrNull(json['end_payment'], EndPayment.fromJson),
    cancel: mapOrNull(json['cancel'], CancelInfo.fromJson),
  );
}

/// Corrida em dinheiro terminada e ainda sem pagamento.
class PendingPayment {
  const PendingPayment({
    required this.rideId,
    required this.amountCents,
    this.chargeId,
    this.blocked = false,
  });

  final String rideId;
  final int amountCents;
  final String? chargeId;
  final bool
  blocked; // com true o passageiro não pede outra corrida até pagar o QR

  factory PendingPayment.fromJson(Json json) => PendingPayment(
    rideId: asString(json['ride_id']),
    amountCents: asInt(json['amount_cents']),
    chargeId: asStringOrNull(json['charge_id']),
    blocked: asBool(json['blocked']),
  );
}

class FeeAppeal {
  const FeeAppeal({
    required this.state,
    this.text,
    this.appealedAt,
    this.decidedAt,
    this.note,
  });

  final String state; // open | accepted | rejected
  final String? text;
  final double? appealedAt;
  final double? decidedAt;
  final String? note;

  factory FeeAppeal.fromJson(Json json) => FeeAppeal(
    state: asString(json['state']),
    text: asStringOrNull(json['text']),
    appealedAt: asDoubleOrNull(json['appealed_at']),
    decidedAt: asDoubleOrNull(json['decided_at']),
    note: asStringOrNull(json['note']),
  );
}

/// Taxa de cancelamento tardio que ainda falta pagar.
class PendingFee {
  const PendingFee({
    required this.rideId,
    required this.amountCents,
    this.chargeId,
    this.appeal,
  });

  final String rideId;
  final int amountCents;
  final String? chargeId; // quando já existe um Pix aberto para pagar
  final FeeAppeal? appeal;

  factory PendingFee.fromJson(Json json) => PendingFee(
    rideId: asString(json['ride_id']),
    amountCents: asInt(json['amount_cents']),
    chargeId: asStringOrNull(json['charge_id']),
    appeal: mapOrNull(json['appeal'], FeeAppeal.fromJson),
  );
}

class RecentFee {
  const RecentFee({
    required this.rideId,
    required this.feeCents,
    required this.createdAt,
    required this.fromBalanceCents,
    required this.retainedCents,
    required this.pendingCents,
    required this.appealState,
    required this.canAppeal,
  });

  final String rideId;
  final int feeCents;
  final double createdAt;
  final int fromBalanceCents;
  final int retainedCents;
  final int pendingCents;
  final String appealState; // none | open | accepted | rejected
  final bool canAppeal;

  factory RecentFee.fromJson(Json json) => RecentFee(
    rideId: asString(json['ride_id']),
    feeCents: asInt(json['fee_cents']),
    createdAt: asDouble(json['created_at']),
    fromBalanceCents: asInt(json['from_balance_cents']),
    retainedCents: asInt(json['retained_cents']),
    pendingCents: asInt(json['pending_cents']),
    appealState: asString(json['appeal_state'], 'none'),
    canAppeal: asBool(json['can_appeal']),
  );
}

class EmergencyContact {
  const EmergencyContact({required this.name, required this.phone});

  final String name;
  final String phone;

  factory EmergencyContact.fromJson(Json json) => EmergencyContact(
    name: asString(json['name']),
    phone: asString(json['phone']),
  );
}

/// Tudo o que o app do passageiro precisa para desenhar a tela: `GET /v1/passenger/state`.
class PassengerState {
  const PassengerState({
    this.ride,
    this.pendingPayment,
    this.blockedReason,
    this.unpaidCents = 0,
    this.balanceCents = 0,
    this.topupEnabled = false,
    this.payWithBalanceEnabled = false,
    this.withdrawEnabled = false,
    this.withdrawMinCents = 0,
    this.withdrawMaxCents = 0,
    this.pendingFee,
    this.recentFees = const [],
    this.emergencyContact,
    this.paymentMethods = const [],
  });

  final PassengerRide? ride;
  final PendingPayment? pendingPayment;
  final String?
  blockedReason; // frase pronta para mostrar quando ele não pode pedir corrida
  final int unpaidCents;
  final int balanceCents;
  final bool topupEnabled;
  final bool payWithBalanceEnabled;
  final bool withdrawEnabled;
  final int withdrawMinCents;
  final int withdrawMaxCents;
  final PendingFee? pendingFee;
  final List<RecentFee> recentFees;
  final EmergencyContact? emergencyContact;
  final List<String> paymentMethods;

  factory PassengerState.fromJson(Json json) => PassengerState(
    ride: mapOrNull(json['ride'], PassengerRide.fromJson),
    pendingPayment: mapOrNull(json['pending_payment'], PendingPayment.fromJson),
    blockedReason: asStringOrNull(json['blocked_reason']),
    unpaidCents: asInt(json['unpaid_cents']),
    balanceCents: asInt(json['balance_cents']),
    topupEnabled: asBool(json['topup_enabled']),
    payWithBalanceEnabled: asBool(json['pay_with_balance_enabled']),
    withdrawEnabled: asBool(json['withdraw_enabled']),
    withdrawMinCents: asInt(json['withdraw_min_cents']),
    withdrawMaxCents: asInt(json['withdraw_max_cents']),
    pendingFee: mapOrNull(json['pending_fee'], PendingFee.fromJson),
    recentFees: mapList(json['recent_fees'], RecentFee.fromJson),
    emergencyContact: mapOrNull(
      json['emergency_contact'],
      EmergencyContact.fromJson,
    ),
    paymentMethods: asStringList(json['payment_methods']),
  );
}

/// De onde saiu a taxa de cancelamento.
class FeeBreakdown {
  const FeeBreakdown({
    required this.fromBalanceCents,
    required this.retainedCents,
    required this.pendingCents,
  });

  final int fromBalanceCents;
  final int retainedCents; // retido da devolução do Pix
  final int pendingCents; // ficou pendente e bloqueia novos pedidos

  factory FeeBreakdown.fromJson(Json json) => FeeBreakdown(
    fromBalanceCents: asInt(json['from_balance_cents']),
    retainedCents: asInt(json['retained_cents']),
    pendingCents: asInt(json['pending_cents']),
  );
}

/// Resposta de `POST /v1/passenger/rides/{id}/cancel`.
class CancelResult {
  const CancelResult({
    required this.refund,
    required this.feeCents,
    required this.fee,
    required this.refundTo,
    required this.balanceCents,
  });

  final bool refund; // havia Pix pago para devolver
  final int feeCents;
  final FeeBreakdown? fee;
  final String? refundTo; // pix | balance | null
  final int balanceCents;

  factory CancelResult.fromJson(Json json) => CancelResult(
    refund: asBool(json['refund']),
    feeCents: asInt(json['fee_cents']),
    fee: mapOrNull(json['fee'], FeeBreakdown.fromJson),
    refundTo: asStringOrNull(json['refund_to']),
    balanceCents: asInt(json['balance_cents']),
  );
}

/// Resposta de `POST /v1/passenger/balance/withdraw`.
class Withdrawal {
  const Withdrawal({
    required this.withdrawalId,
    required this.amountCents,
    required this.balanceCents,
    required this.key,
  });

  final String withdrawalId;
  final int amountCents;
  final int balanceCents;
  final String key; // só o final da chave, ex.: "final 4725"

  factory Withdrawal.fromJson(Json json) => Withdrawal(
    withdrawalId: asString(json['withdrawal_id']),
    amountCents: asInt(json['amount_cents']),
    balanceCents: asInt(json['balance_cents']),
    key: asString(json['key']),
  );
}

/// Resposta do botão de SOS.
class SosResult {
  const SosResult({
    required this.alertId,
    required this.contactRegistered,
    required this.contactNotified,
    required this.repeated,
    required this.emergencyNumber,
  });

  final int alertId;
  final bool contactRegistered;
  final bool contactNotified;
  final bool repeated;
  final String emergencyNumber;

  factory SosResult.fromJson(Json json) => SosResult(
    alertId: asInt(json['alert_id']),
    contactRegistered: asBool(json['contact_registered']),
    contactNotified: asBool(json['contact_notified']),
    repeated: asBool(json['repeated']),
    emergencyNumber: asString(json['emergency_number'], '190'),
  );
}
