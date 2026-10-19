import 'dart:async';

import 'api_client.dart';
import 'errors.dart';
import 'session.dart';

class Me {
  Me({
    required this.userId,
    required this.phone,
    required this.name,
    required this.role,
  });

  final String userId;
  final String phone;
  final String? name;
  final String role;

  factory Me.fromJson(Object? json) {
    final map = json is Map ? json : const {};
    return Me(
      userId: '${map['user_id'] ?? ''}',
      phone: '${map['phone'] ?? ''}',
      name: map['name'] is String ? map['name'] as String : null,
      role: '${map['role'] ?? ''}',
    );
  }
}

class VerifyResult {
  VerifyResult({required this.session, required this.isNewUser});

  final Session session;
  final bool isNewUser;
}

/// Entrar e conta (`/v1/auth/*`, `/v1/me`).
class AuthApi {
  AuthApi(this.client);

  final ApiClient client;

  Future<void> requestCode(String phone) async {
    await client.post('/v1/auth/code', body: {'phone': phone});
  }

  /// Confere o código e já deixa o token no cliente.
  Future<VerifyResult> verify({
    required String phone,
    required String code,
    required String role,
    String? device,
  }) async {
    final body = <String, Object?>{'phone': phone, 'code': code, 'role': role};
    if (device != null) body['device'] = device;
    final reply = await client.post('/v1/auth/verify', body: body);
    final map = reply is Map ? reply : const {};
    final token = map['token'];
    final userId = map['user_id'];
    if (token is! String || userId is! String) {
      throw NetworkException('Resposta inesperada do servidor. Tente de novo.');
    }
    final session = Session(
      token: token,
      userId: userId,
      role: map['role'] is String ? map['role'] as String : role,
      name: map['name'] is String ? map['name'] as String : null,
    );
    client.token = token;
    return VerifyResult(
      session: session,
      isNewUser: map['is_new_user'] == true,
    );
  }

  /// Sai no servidor; o token do cliente é limpo de qualquer jeito.
  Future<void> logout() async {
    try {
      await client.post('/v1/auth/logout');
    } finally {
      client.token = null;
    }
  }

  Future<Me> me() async => Me.fromJson(await client.get('/v1/me'));

  Future<Me> updateName(String name) async =>
      Me.fromJson(await client.put('/v1/me', body: {'name': name}));
}

/// Guarda a sessão entre aberturas do app e reage à sessão vencida.
class SessionManager {
  SessionManager(this._auth, this._store, this._client) {
    _client.onUnauthorized = _expired;
  }

  final AuthApi _auth;
  final SessionStore _store;
  final ApiClient _client;
  final StreamController<Session?> _changes =
      StreamController<Session?>.broadcast();
  Session? _current;

  Session? get current => _current;

  /// Mudanças da sessão: a nova sessão ao entrar, `null` ao sair ou ao vencer.
  Stream<Session?> get changes => _changes.stream;

  Future<Session?> restore() async {
    Session? saved;
    try {
      saved = await _store.load();
    } on FormatException {
      await _store.clear();
    }
    _current = saved;
    _client.token = saved?.token;
    return saved;
  }

  Future<VerifyResult> signIn({
    required String phone,
    required String code,
    required String role,
    String? device,
  }) async {
    final result = await _auth.verify(
      phone: phone,
      code: code,
      role: role,
      device: device,
    );
    await _store.save(result.session);
    _current = result.session;
    _changes.add(result.session);
    return result;
  }

  Future<void> signOut() async {
    try {
      if (_client.token != null) await _auth.logout();
    } on Exception {
      // sem rede ou sessão já vencida: sair vale do mesmo jeito
    } finally {
      _client.token = null;
      await _forget();
    }
  }

  void _expired() {
    unawaited(_forget());
  }

  Future<void> _forget() async {
    final had = _current != null;
    _current = null;
    await _store.clear();
    if (had) _changes.add(null);
  }
}
