/// Dinheiro sempre em centavos inteiros; texto só na hora de mostrar.
String brl(int cents) {
  final negative = cents < 0;
  final absolute = cents.abs();
  final reais = (absolute ~/ 100).toString();
  final centavos = (absolute % 100).toString().padLeft(2, '0');
  final grouped = StringBuffer();
  for (var i = 0; i < reais.length; i++) {
    if (i > 0 && (reais.length - i) % 3 == 0) grouped.write('.');
    grouped.write(reais[i]);
  }
  return '${negative ? '-' : ''}R\$ $grouped,$centavos';
}
