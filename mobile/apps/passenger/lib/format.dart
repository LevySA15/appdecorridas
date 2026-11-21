import 'package:corrida_core/corrida_core.dart';

/// `dd/mm/aaaa HH:mm` na hora do aparelho, a partir de segundos desde 1970 (como o servidor manda).
String formatRideDate(double epochSeconds) {
  final date = DateTime.fromMillisecondsSinceEpoch(
    (epochSeconds * 1000).round(),
  );
  String two(int n) => n.toString().padLeft(2, '0');
  return '${two(date.day)}/${two(date.month)}/${date.year} '
      '${two(date.hour)}:${two(date.minute)}';
}

/// Como a corrida terminou.
String rideStateLabel(RideState state) => switch (state) {
  RideState.completed => 'Concluída',
  RideState.cancelled => 'Cancelada',
  RideState.noRider => 'Sem moto',
  _ => 'Encerrada',
};

/// Quilômetros com uma casa, sem passar por número de ponto flutuante (1950 m → `1,9 km`).
String formatKm(int meters) {
  final tenths = meters ~/ 100;
  return '${tenths ~/ 10},${tenths % 10} km';
}

/// `pix`, `cash` ou `balance` em português.
String paymentLabel(String method) => switch (method) {
  'pix' => 'Pix',
  'cash' => 'Dinheiro',
  'balance' => 'Saldo do app',
  _ => method,
};
