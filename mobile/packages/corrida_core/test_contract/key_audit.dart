// Auditoria de campos do contrato: os modelos do pacote são tolerantes de propósito (campo que falta vira padrão),
// então um campo renomeado no servidor passaria despercebido. Aqui as respostas de verdade são lidas pelos modelos
// por um mapa que anota cada chave lida, e depois se compara o que o servidor mandou com o que o pacote leu.
import 'dart:collection';
import 'dart:convert';

import 'package:http/http.dart' as http;

String _join(String prefix, String key) =>
    prefix.isEmpty ? key : '$prefix.$key';

Object? _wrap(Object? value, String prefix, Set<String> read) {
  if (value is Map<String, Object?>) return RecordingMap(value, prefix, read);
  if (value is List)
    return [for (final e in value) _wrap(e, '$prefix[]', read)];
  return value;
}

/// Mapa só de leitura que anota o caminho de cada chave que o modelo pediu.
class RecordingMap extends MapBase<String, Object?> {
  RecordingMap(this._inner, this._prefix, this._read);

  final Map<String, Object?> _inner;
  final String _prefix;
  final Set<String> _read;

  @override
  Object? operator [](Object? key) {
    if (key is! String || !_inner.containsKey(key)) return null;
    final path = _join(_prefix, key);
    _read.add(path);
    return _wrap(_inner[key], path, _read);
  }

  @override
  void operator []=(String key, Object? value) =>
      throw UnsupportedError('somente leitura');

  @override
  void clear() => throw UnsupportedError('somente leitura');

  @override
  Iterable<String> get keys => _inner.keys;

  @override
  Object? remove(Object? key) => throw UnsupportedError('somente leitura');
}

/// Todos os caminhos de chave de uma resposta (`ride`, `ride.rider`, `ride.rider.name`, `recent_fees[].fee_cents`...).
Set<String> allPaths(Object? value, [String prefix = '']) {
  final paths = <String>{};
  if (value is Map) {
    for (final entry in value.entries) {
      final path = _join(prefix, '${entry.key}');
      paths
        ..add(path)
        ..addAll(allPaths(entry.value, path));
    }
  } else if (value is List) {
    for (final e in value) {
      paths.addAll(allPaths(e, '$prefix[]'));
    }
  }
  return paths;
}

/// Passa a resposta pelo modelo e devolve os caminhos que ele leu.
Set<String> pathsRead(Object? raw, void Function(Map<String, Object?>) parse) {
  final read = <String>{};
  final wrapped = _wrap(raw, '', read);
  if (wrapped is Map<String, Object?>) parse(wrapped);
  return read;
}

final _idSegment = RegExp(r'^(ride|ch|bal|wd|fee)-[\w-]+$|^\d+$');

String normalizePath(String path) =>
    path.split('/').map((s) => _idSegment.hasMatch(s) ? '{id}' : s).join('/');

/// Cliente HTTP que guarda as respostas JSON de sucesso, por rota.
class RecordingClient extends http.BaseClient {
  RecordingClient(this._inner);

  final http.Client _inner;
  final responses = <String, List<Object?>>{};

  @override
  Future<http.StreamedResponse> send(http.BaseRequest request) async {
    final streamed = await _inner.send(request);
    final bytes = await streamed.stream.toBytes();
    if (streamed.statusCode >= 200 &&
        streamed.statusCode < 300 &&
        bytes.isNotEmpty) {
      try {
        responses
            .putIfAbsent(
              '${request.method} ${normalizePath(request.url.path)}',
              () => [],
            )
            .add(jsonDecode(utf8.decode(bytes)));
      } on FormatException {
        // não era JSON
      }
    }
    return http.StreamedResponse(
      Stream.value(bytes),
      streamed.statusCode,
      contentLength: bytes.length,
      request: request,
      headers: streamed.headers,
      reasonPhrase: streamed.reasonPhrase,
    );
  }
}
