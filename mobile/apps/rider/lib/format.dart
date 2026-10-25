/// Distância para a pessoa ler: metros abaixo de 1000, senão quilômetros com uma casa e vírgula.
String km(int meters) {
  if (meters < 1000) return '$meters m';
  return '${(meters / 1000).toStringAsFixed(1).replaceAll('.', ',')} km';
}
