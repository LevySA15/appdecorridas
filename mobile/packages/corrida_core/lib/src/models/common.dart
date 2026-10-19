/// Leitura tolerante do JSON do servidor: campo que falta vira padrão/`null`, campo novo é ignorado, tipo
/// inesperado não derruba o app. Dinheiro vem sempre como `int` (mesmo que o JSON traga `700.0`).
library;

typedef Json = Map<String, Object?>;

int? asIntOrNull(Object? value) =>
    value is num && value.isFinite ? value.round() : null;

int asInt(Object? value, [int fallback = 0]) => asIntOrNull(value) ?? fallback;

double? asDoubleOrNull(Object? value) =>
    value is num && value.isFinite ? value.toDouble() : null;

double asDouble(Object? value, [double fallback = 0]) =>
    asDoubleOrNull(value) ?? fallback;

String? asStringOrNull(Object? value) => value is String ? value : null;

String asString(Object? value, [String fallback = '']) =>
    asStringOrNull(value) ?? fallback;

bool asBool(Object? value, [bool fallback = false]) =>
    value is bool ? value : fallback;

Json? asMap(Object? value) {
  if (value is Json)
    return value; // o que `jsonDecode` devolve já é isto: sem copiar
  if (value is! Map) return null;
  return value.map((key, v) => MapEntry('$key', v));
}

List<Object?> asList(Object? value) => value is List ? value : const [];

List<String> asStringList(Object? value) =>
    asList(value).whereType<String>().toList();

List<T> mapList<T>(Object? value, T Function(Json) build) =>
    asList(value).map(asMap).whereType<Json>().map(build).toList();

T? mapOrNull<T>(Object? value, T Function(Json) build) {
  final map = asMap(value);
  return map == null ? null : build(map);
}

/// Um lugar no mapa: coordenadas e o texto que a pessoa vê.
class Place {
  const Place({required this.lat, required this.lng, this.text = ''});

  final double lat;
  final double lng;
  final String text;

  factory Place.fromJson(Json json) => Place(
    lat: asDouble(json['lat']),
    lng: asDouble(json['lng']),
    text: asString(json['text']),
  );

  Json toJson() => {'lat': lat, 'lng': lng, 'text': text};
}

/// Estado da corrida. Valor que o app não conhece vira [unknown] em vez de erro.
enum RideState {
  requested,
  searching,
  queued,
  accepted,
  arrived,
  inProgress,
  completed,
  cancelled,
  noRider,
  unknown;

  static RideState parse(String? value) => switch (value) {
    'requested' => requested,
    'searching' => searching,
    'queued' => queued,
    'accepted' => accepted,
    'arrived' => arrived,
    'in_progress' => inProgress,
    'completed' => completed,
    'cancelled' => cancelled,
    'no_rider' => noRider,
    _ => unknown,
  };
}

/// Cobrança Pix (`GET /v1/charges/{id}`, recarga, taxa, dívida). O app desenha o QR a partir de [brCode].
class Charge {
  const Charge({
    required this.chargeId,
    required this.amountCents,
    this.brCode = '',
    this.purpose,
    this.rideId,
    this.paid = false,
  });

  final String chargeId;
  final int amountCents;
  final String brCode;
  final String? purpose;
  final String? rideId;
  final bool paid;

  factory Charge.fromJson(Json json) => Charge(
    chargeId: asString(json['charge_id']),
    amountCents: asInt(json['amount_cents']),
    brCode: asString(json['br_code']),
    purpose: asStringOrNull(json['purpose']),
    rideId: asStringOrNull(json['ride_id']),
    paid: asBool(json['paid']),
  );
}

/// Pagamento do QR do fim de uma corrida em dinheiro.
class EndPayment {
  const EndPayment({
    this.chargeId,
    required this.amountCents,
    this.blocked = false,
  });

  final String? chargeId;
  final int amountCents;
  final bool blocked;

  factory EndPayment.fromJson(Json json) => EndPayment(
    chargeId: asStringOrNull(json['charge_id']),
    amountCents: asInt(json['amount_cents']),
    blocked: asBool(json['blocked']),
  );
}
