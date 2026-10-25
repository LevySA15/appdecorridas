import 'common.dart';

enum RegistrationStatus {
  notRegistered,
  pending,
  approved,
  rejected,
  blocked,
  unknown;

  static RegistrationStatus parse(String? value) => switch (value) {
        'not_registered' => notRegistered,
        'pending' => pending,
        'approved' => approved,
        'rejected' => rejected,
        'blocked' => blocked,
        _ => unknown,
      };
}

DateTime? _date(Object? value) => value is String ? DateTime.tryParse(value) : null;

String _day(DateTime date) =>
    '${date.year.toString().padLeft(4, '0')}-${date.month.toString().padLeft(2, '0')}-${date.day.toString().padLeft(2, '0')}';

/// O cadastro do motoqueiro e se ele está disponível.
class RiderRegistration {
  const RiderRegistration({
    required this.status,
    this.online = false,
    this.reason,
    this.rating,
    this.ratingCount = 0,
    this.cnhExpiresOn,
    this.crlvExpiresOn,
  });

  final RegistrationStatus status;
  final bool online;
  final String? reason; // motivo da recusa ou do bloqueio, para mostrar
  final double? rating;
  final int ratingCount;
  final DateTime? cnhExpiresOn;
  final DateTime? crlvExpiresOn;

  factory RiderRegistration.fromJson(Json json) => RiderRegistration(
        status: RegistrationStatus.parse(asStringOrNull(json['status'])),
        online: asBool(json['online']),
        reason: asStringOrNull(json['reason']),
        rating: asDoubleOrNull(json['rating']),
        ratingCount: asInt(json['rating_count']),
        cnhExpiresOn: _date(json['cnh_expires_on']),
        crlvExpiresOn: _date(json['crlv_expires_on']),
      );
}

/// A conta do motoqueiro: teste, entrada, taxa devida e o que o bloqueia.
class RiderAccount {
  const RiderAccount({
    required this.completedRides,
    required this.trialRides,
    required this.entryPaid,
    required this.entryFeeCents,
    required this.needsEntry,
    required this.blockedReason,
    required this.cashDebtCents,
    required this.cashDebtLimitCents,
    required this.debtToPayCents,
  });

  final int completedRides;
  final int trialRides;
  final bool entryPaid;
  final int entryFeeCents;
  final bool needsEntry;
  final String? blockedReason; // entry_pending | debt_pending | null
  final int cashDebtCents;
  final int cashDebtLimitCents;
  final int debtToPayCents;

  factory RiderAccount.fromJson(Json json) => RiderAccount(
        completedRides: asInt(json['completed_rides']),
        trialRides: asInt(json['trial_rides']),
        entryPaid: asBool(json['entry_paid']),
        entryFeeCents: asInt(json['entry_fee_cents']),
        needsEntry: asBool(json['needs_entry']),
        blockedReason: asStringOrNull(json['blocked_reason']),
        cashDebtCents: asInt(json['cash_debt_cents']),
        cashDebtLimitCents: asInt(json['cash_debt_limit_cents']),
        debtToPayCents: asInt(json['debt_to_pay_cents']),
      );
}

/// Oferta de corrida (estado do motoqueiro e aviso `offer` do tempo real têm o mesmo formato).
class Offer {
  const Offer({
    required this.rideId,
    this.priceCents = 0,
    this.paymentMethod = '',
    this.pickup = const Place(lat: 0, lng: 0),
    this.destination = const Place(lat: 0, lng: 0),
    this.distanceM = 0,
    this.secondsToPickup,
    this.willQueue = false,
    this.expiresAt = 0,
  });

  final String rideId;
  final int priceCents;
  final String paymentMethod;
  final Place pickup;
  final Place destination;
  final int distanceM;
  final int? secondsToPickup;
  final bool willQueue; // a corrida espera na fila até ele terminar a de agora
  final double expiresAt;

  factory Offer.fromJson(Json json) => Offer(
        rideId: asString(json['ride_id']),
        priceCents: asInt(json['price_cents']),
        paymentMethod: asString(json['payment_method']),
        pickup: Place.fromJson(asMap(json['pickup']) ?? const {}),
        destination: Place.fromJson(asMap(json['destination']) ?? const {}),
        distanceM: asInt(json['distance_m']),
        secondsToPickup: asIntOrNull(json['seconds_to_pickup']),
        willQueue: asBool(json['will_queue']),
        expiresAt: asDouble(json['expires_at']),
      );
}

/// A corrida vista pelo motoqueiro (o passageiro aparece só pelo primeiro nome; o código fica com o passageiro).
class RiderRide {
  const RiderRide({
    required this.rideId,
    required this.state,
    this.queued = false,
    this.priceCents = 0,
    this.feeCents,
    this.method = '',
    this.pixPaid = false,
    this.helmetConfirmed = false,
    this.passengerName = '',
    this.pickup = const Place(lat: 0, lng: 0),
    this.destination = const Place(lat: 0, lng: 0),
    this.distanceM = 0,
    this.endPayment,
  });

  final String rideId;
  final RideState state;
  final bool queued;
  final int priceCents;
  final int? feeCents;
  final String method;
  final bool pixPaid;
  final bool helmetConfirmed;
  final String passengerName;
  final Place pickup;
  final Place destination;
  final int distanceM;
  final EndPayment? endPayment;

  factory RiderRide.fromJson(Json json) => RiderRide(
        rideId: asString(json['ride_id']),
        state: RideState.parse(asStringOrNull(json['state'])),
        queued: asBool(json['queued']),
        priceCents: asInt(json['price_cents']),
        feeCents: asIntOrNull(json['fee_cents']),
        method: asString(json['method']),
        pixPaid: asBool(json['pix_paid']),
        helmetConfirmed: asBool(json['helmet_confirmed']),
        passengerName: asString(asMap(json['passenger'])?['name']),
        pickup: Place.fromJson(asMap(json['pickup']) ?? const {}),
        destination: Place.fromJson(asMap(json['destination']) ?? const {}),
        distanceM: asInt(json['distance_m']),
        endPayment: mapOrNull(json['end_payment'], EndPayment.fromJson),
      );
}

/// `GET /v1/rider/state`: tudo o que o app do motoqueiro precisa para desenhar a tela.
class RiderState {
  const RiderState({
    required this.registration,
    this.account,
    this.offer,
    this.ride,
    this.queuedRide,
    this.awaitingPayment,
  });

  final RiderRegistration registration;
  final RiderAccount? account; // null enquanto não se cadastrou
  final Offer? offer;
  final RiderRide? ride;
  final RiderRide? queuedRide;
  final RiderRide? awaitingPayment; // corrida em dinheiro que terminou e espera o pagamento

  factory RiderState.fromJson(Json json) => RiderState(
        registration: RiderRegistration.fromJson(asMap(json['registration']) ?? const {}),
        account: mapOrNull(json['account'], RiderAccount.fromJson),
        offer: mapOrNull(json['offer'], Offer.fromJson),
        ride: mapOrNull(json['ride'], RiderRide.fromJson),
        queuedRide: mapOrNull(json['queued_ride'], RiderRide.fromJson),
        awaitingPayment: mapOrNull(json['awaiting_payment'], RiderRide.fromJson),
      );
}

/// As três fotos do cadastro.
enum DocKind {
  selfie,
  cnh,
  crlv;
}

class UploadedDocument {
  const UploadedDocument({required this.key, required this.bytes});

  final String key;
  final int bytes;

  factory UploadedDocument.fromJson(Json json) =>
      UploadedDocument(key: asString(json['key']), bytes: asInt(json['bytes']));
}

/// O que o motoqueiro preenche para pedir aprovação (`POST /v1/rider/register`).
class RiderRegistrationForm {
  const RiderRegistrationForm({
    required this.name,
    required this.cpf,
    required this.cnhNumber,
    required this.plate,
    required this.motoModel,
    required this.selfieKey,
    required this.cnhPhotoKey,
    required this.crlvKey,
    required this.cnhExpiresOn,
    required this.crlvExpiresOn,
  });

  final String name;
  final String cpf;
  final String cnhNumber;
  final String plate;
  final String motoModel;
  final String selfieKey; // chaves devolvidas pelo envio das fotos
  final String cnhPhotoKey;
  final String crlvKey;
  final DateTime cnhExpiresOn;
  final DateTime crlvExpiresOn;

  Json toJson() => {
        'name': name,
        'cpf': cpf,
        'cnh_number': cnhNumber,
        'plate': plate,
        'moto_model': motoModel,
        'selfie_key': selfieKey,
        'cnh_photo_key': cnhPhotoKey,
        'crlv_key': crlvKey,
        'cnh_expires_on': _day(cnhExpiresOn),
        'crlv_expires_on': _day(crlvExpiresOn),
      };
}

/// Formato `AAAA-MM-DD` que o servidor espera nas validades.
String formatDay(DateTime date) => _day(date);

/// Uma corrida terminada no extrato do dia.
class StatementRide {
  const StatementRide({
    required this.rideId,
    required this.completedAt,
    required this.priceCents,
    required this.feeCents,
    required this.netCents,
    required this.method,
    required this.distanceM,
  });

  final String rideId;
  final double completedAt; // segundos desde 1970
  final int priceCents;
  final int feeCents; // a taxa do app, gravada no aceite
  final int netCents; // o que ficou com o motoqueiro: preço menos a taxa
  final String method; // pix | cash
  final int distanceM;

  factory StatementRide.fromJson(Json json) => StatementRide(
    rideId: asString(json['ride_id']),
    completedAt: asDouble(json['completed_at']),
    priceCents: asInt(json['price_cents']),
    feeCents: asInt(json['fee_cents']),
    netCents: asInt(json['net_cents']),
    method: asString(json['method']),
    distanceM: asInt(json['distance_m']),
  );
}

/// `GET /v1/rider/statement`: o extrato de um dia (hoje, se não pedir outro).
class RiderStatement {
  const RiderStatement({
    required this.date,
    this.completedCount = 0,
    this.grossCents = 0,
    this.feeCents = 0,
    this.netCents = 0,
    this.cashCents = 0,
    this.pixCents = 0,
    this.rides = const [],
    this.nextRideNumber,
    this.nextFeeCents,
    this.cashDebtCents = 0,
  });

  final String date; // AAAA-MM-DD
  final int completedCount;
  final int grossCents;
  final int feeCents;
  final int netCents;
  final int cashCents;
  final int pixCents;
  final List<StatementRide> rides;

  /// A próxima faixa de taxa (só para o dia de hoje; em outro dia vêm nulos).
  final int? nextRideNumber;
  final int? nextFeeCents;
  final int cashDebtCents;

  factory RiderStatement.fromJson(Json json) => RiderStatement(
    date: asString(json['date']),
    completedCount: asInt(json['completed_count']),
    grossCents: asInt(json['gross_cents']),
    feeCents: asInt(json['fee_cents']),
    netCents: asInt(json['net_cents']),
    cashCents: asInt(json['cash_cents']),
    pixCents: asInt(json['pix_cents']),
    rides: mapList(json['rides'], StatementRide.fromJson),
    nextRideNumber: asIntOrNull(json['next_ride_number']),
    nextFeeCents: asIntOrNull(json['next_fee_cents']),
    cashDebtCents: asInt(json['cash_debt_cents']),
  );
}

