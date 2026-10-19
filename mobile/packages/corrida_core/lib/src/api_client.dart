import 'dart:async';
import 'dart:convert';

import 'package:http/http.dart' as http;

import 'errors.dart';

/// Cliente HTTP do servidor (`docs/api-v1.md`). Devolve o JSON decodificado (`null` em 204).
class ApiClient {
  ApiClient({
    required this.baseUrl,
    http.Client? httpClient,
    this.timeout = const Duration(seconds: 15),
    this.onUnauthorized,
  }) : _http = httpClient ?? http.Client(),
       _ownsClient = httpClient == null;

  final Uri baseUrl;
  final http.Client _http;
  final bool _ownsClient;

  /// Quanto esperar por cada resposta.
  final Duration timeout;

  /// Chamado uma vez quando o servidor recusa o token (sessão vencida); o token é limpo antes.
  void Function()? onUnauthorized;

  String? token;

  Future<Object?> get(String path, {Map<String, String>? query}) =>
      _send('GET', path, query: query);

  Future<Object?> post(String path, {Object? body}) =>
      _send('POST', path, body: body);

  Future<Object?> put(String path, {Object? body}) =>
      _send('PUT', path, body: body);

  /// Envia bytes crus (foto de documento). O tempo padrão é bem maior que o das outras chamadas: uma foto de
  /// câmera em rede fraca leva dezenas de segundos só para subir.
  Future<Object?> putBytes(
    String path,
    List<int> bytes, {
    required String contentType,
    Duration timeout = const Duration(seconds: 120),
  }) => _send(
    'PUT',
    path,
    bytes: bytes,
    contentType: contentType,
    timeout: timeout,
  );

  void close() {
    if (_ownsClient) _http.close();
  }

  Uri _uri(String path, Map<String, String>? query) {
    final base = baseUrl.path.endsWith('/')
        ? baseUrl.path.substring(0, baseUrl.path.length - 1)
        : baseUrl.path;
    return baseUrl.replace(
      path: '$base$path',
      queryParameters: (query == null || query.isEmpty) ? null : query,
    );
  }

  Future<Object?> _send(
    String method,
    String path, {
    Map<String, String>? query,
    Object? body,
    List<int>? bytes,
    String? contentType,
    Duration? timeout,
  }) async {
    final limit = timeout ?? this.timeout;
    final request = http.Request(method, _uri(path, query));
    final currentToken = token;
    if (currentToken != null)
      request.headers['authorization'] = 'Bearer $currentToken';
    if (bytes != null) {
      request.headers['content-type'] =
          contentType ?? 'application/octet-stream';
      request.bodyBytes = bytes;
    } else if (body != null) {
      request.headers['content-type'] = 'application/json; charset=utf-8';
      request.bodyBytes = utf8.encode(jsonEncode(body));
    }

    final http.Response response;
    try {
      final streamed = await _http.send(request).timeout(limit);
      response = await http.Response.fromStream(streamed).timeout(limit);
    } on TimeoutException {
      throw NetworkException(
        'O servidor demorou para responder. Tente de novo.',
      );
    } on Exception {
      throw NetworkException();
    }

    final text = utf8.decode(response.bodyBytes, allowMalformed: true);
    if (response.statusCode >= 200 && response.statusCode < 300) {
      if (response.statusCode == 204 || text.trim().isEmpty) return null;
      try {
        return jsonDecode(text);
      } on FormatException {
        throw NetworkException(
          'Resposta inesperada do servidor. Tente de novo.',
        );
      }
    }
    throw _errorFrom(response.statusCode, text, sentToken: currentToken);
  }

  ApiException _errorFrom(
    int status,
    String text, {
    required String? sentToken,
  }) {
    Object? decoded;
    try {
      decoded = jsonDecode(text);
    } on FormatException {
      decoded = null;
    }
    var code = 'http_$status';
    var message = 'Algo deu errado. Tente de novo.';
    String? field;
    var fields = <String>[];
    if (decoded is Map && decoded['error'] is Map) {
      final error = decoded['error'] as Map;
      if (error['code'] is String) code = error['code'] as String;
      if (error['message'] is String) message = error['message'] as String;
      if (error['field'] is String) field = error['field'] as String;
      if (error['fields'] is List)
        fields = (error['fields'] as List).whereType<String>().toList();
    }
    // Só vale se o token que falhou ainda é o de agora: um 401 atrasado de uma sessão antiga não derruba a nova.
    if (status == 401 &&
        code == 'unauthorized' &&
        sentToken != null &&
        token == sentToken) {
      token = null;
      onUnauthorized?.call();
    }
    return ApiException(
      status: status,
      code: code,
      message: message,
      field: field,
      fields: fields,
    );
  }
}
