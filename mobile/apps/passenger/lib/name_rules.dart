/// A regra do nome (a mesma do servidor, em `AuthService.set_name`): de 2 a 120 letras, sem contar os
/// espaços das pontas.
const nameLengthError = 'Digite seu nome (de 2 a 120 letras).';

/// A frase do problema com [raw], ou `null` se o nome serve.
String? nameError(String raw) {
  final length = raw.trim().length;
  return length < 2 || length > 120 ? nameLengthError : null;
}
