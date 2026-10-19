/// Erro que o servidor respondeu de propósito. O app decide pelo [code] (estável); a [message] é uma frase em
/// português que pode ser mostrada à pessoa.
class ApiException implements Exception {
  ApiException({
    required this.status,
    required this.code,
    required this.message,
    this.field,
    this.fields = const [],
  });

  final int status;
  final String code;
  final String message;
  final String? field;
  final List<String> fields;

  @override
  String toString() => 'ApiException($status $code): $message';
}

/// Não deu para falar com o servidor (sem internet, tempo esgotado) ou a resposta não era a esperada.
class NetworkException implements Exception {
  NetworkException([
    this.message = 'Sem conexão com o servidor. Tente de novo.',
  ]);

  final String message;

  @override
  String toString() => 'NetworkException: $message';
}
