import 'dart:convert';

import 'package:corrida_core/corrida_core.dart';
import 'package:flutter/services.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';

/// Guarda a sessão no armazenamento seguro do celular (Keystore no Android), para o login sobreviver a o
/// Android fechar o app. O token nunca vai para as preferências comuns nem para o log.
class SecureSessionStore implements SessionStore {
  SecureSessionStore({FlutterSecureStorage? storage})
    : _storage = storage ?? const FlutterSecureStorage();

  static const _key = 'session';

  final FlutterSecureStorage _storage;

  @override
  Future<Session?> load() async {
    final String? raw;
    try {
      raw = await _storage.read(key: _key);
    } on PlatformException {
      // O Keystore às vezes perde as chaves (restauração de backup, troca de tela de bloqueio): o valor guardado
      // não abre mais. Esquece e pede o login de novo, em vez de travar o app.
      try {
        await clear();
      } on PlatformException {
        // nem apagar o Keystore deixa: segue sem sessão e pede o login (o app não pode travar aqui)
      }
      return null;
    }
    if (raw == null) return null;
    final decoded = jsonDecode(
      raw,
    ); // valor estragado: FormatException, e o SessionManager esquece
    if (decoded is! Map)
      throw const FormatException('sessão guardada inválida');
    return Session.fromJson(decoded.map((k, v) => MapEntry('$k', v)));
  }

  @override
  Future<void> save(Session session) =>
      _storage.write(key: _key, value: jsonEncode(session.toJson()));

  @override
  Future<void> clear() => _storage.delete(key: _key);
}
