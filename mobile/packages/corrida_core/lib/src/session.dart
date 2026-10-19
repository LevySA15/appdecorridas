/// Quem está usando o app: o token da sessão (180 dias no servidor) e quem é a pessoa.
class Session {
  Session({required this.token, required this.userId, required this.role, this.name});

  final String token;
  final String userId;
  final String role; // passenger | rider | admin
  final String? name;

  Map<String, Object?> toJson() => {'token': token, 'user_id': userId, 'role': role, 'name': name};

  /// Lê o que foi guardado. Dado estragado levanta [FormatException] (o app trata como "sem sessão").
  factory Session.fromJson(Map<String, Object?> json) {
    final token = json['token'];
    final userId = json['user_id'];
    final role = json['role'];
    if (token is! String || userId is! String || role is! String) {
      throw const FormatException('sessão guardada incompleta');
    }
    final name = json['name'];
    return Session(token: token, userId: userId, role: role, name: name is String ? name : null);
  }
}

/// Onde a sessão fica guardada. No celular será o armazenamento seguro; nos testes, a memória.
abstract class SessionStore {
  Future<Session?> load();
  Future<void> save(Session session);
  Future<void> clear();
}

class MemorySessionStore implements SessionStore {
  Session? _session;

  @override
  Future<Session?> load() async => _session;

  @override
  Future<void> save(Session session) async => _session = session;

  @override
  Future<void> clear() async => _session = null;
}
