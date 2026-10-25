import 'package:corrida_core/corrida_core.dart';

/// A frase que a pessoa vê para um erro: a do servidor ou da rede (já em português), ou uma genérica.
String friendlyMessage(Object error) => switch (error) {
  ApiException(message: final message) => message,
  NetworkException(message: final message) => message,
  _ => 'Algo deu errado. Tente de novo.',
};
