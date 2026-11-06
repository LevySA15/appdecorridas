/// Endereço do servidor que o app usa, vindo de `--dart-define=API_URL=...`.
///
/// Sem a opção vale o `localhost` do `adb reverse` (celular ligado por USB ao computador). O Android de release
/// bloqueia HTTP sem criptografia, então um endereço `http://` num build de release é recusado já na partida,
/// em vez de parecer funcionar e travar no primeiro pedido.
library;

final Uri _padrao = Uri.parse('http://localhost:8000');

Uri serverUrlFrom(String define, {bool isRelease = false}) {
  final texto = define.trim();
  if (texto.isEmpty) return _padrao;
  final url = Uri.tryParse(texto);
  final esquemaOk = url != null && (url.scheme == 'http' || url.scheme == 'https');
  if (!esquemaOk || url.host.isEmpty) {
    throw FormatException('API_URL inválida: "$texto". Use o endereço completo, por exemplo https://corrida.exemplo.com.br');
  }
  if (isRelease && url.scheme == 'http') {
    throw FormatException(
      'API_URL inválida: "$texto". O app de release só fala com o servidor por HTTPS (o Android bloqueia HTTP sem criptografia).',
    );
  }
  final caminho = url.path.endsWith('/') ? url.path.substring(0, url.path.length - 1) : url.path;
  return url.replace(path: caminho);
}
