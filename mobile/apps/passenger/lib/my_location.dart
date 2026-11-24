import 'dart:async';

import 'package:corrida_core/corrida_core.dart';
import 'package:geolocator/geolocator.dart';

/// Por que não deu para saber onde a pessoa está. [message] já diz o que fazer.
class MyLocationUnavailable implements Exception {
  const MyLocationUnavailable(this.message);

  final String message;

  @override
  String toString() => message;
}

/// "Estou aqui": a posição do celular, uma vez só (o passageiro não precisa de rastreamento: só do ponto de embarque).
/// Mesmo molde do `PhotoSource` e do `LocationSource` do motoqueiro: a tela nunca fala com o plugin.
abstract class MyLocation {
  /// Pergunta a permissão se preciso e devolve a posição. Falha com [MyLocationUnavailable].
  Future<Place> current();
}

/// Traduz o que o Android diz para a frase certa (sem plugin: dá para testar).
MyLocationUnavailable? problemOf({
  required bool serviceEnabled,
  required LocationPermission permission,
}) {
  if (!serviceEnabled) {
    return const MyLocationUnavailable(
      'Ligue o GPS do celular para usar a sua localização, ou marque o ponto no mapa.',
    );
  }
  return switch (permission) {
    LocationPermission.whileInUse || LocationPermission.always => null,
    LocationPermission.deniedForever => const MyLocationUnavailable(
      'A localização está bloqueada para o app. Libere nas configurações do celular, ou marque o ponto no mapa.',
    ),
    LocationPermission.denied ||
    LocationPermission.unableToDetermine => const MyLocationUnavailable(
      'Sem a permissão de localização não dá para usar a sua posição. Marque o ponto no mapa.',
    ),
  };
}

/// O GPS do celular (e a localização do navegador na versão web de conferência).
class GeolocatorMyLocation implements MyLocation {
  const GeolocatorMyLocation();

  @override
  Future<Place> current() async {
    final serviceEnabled = await Geolocator.isLocationServiceEnabled();
    var permission = await Geolocator.checkPermission();
    if (serviceEnabled && permission == LocationPermission.denied) {
      permission = await Geolocator.requestPermission();
    }
    final problem = problemOf(
      serviceEnabled: serviceEnabled,
      permission: permission,
    );
    if (problem != null) throw problem;
    try {
      final position = await Geolocator.getCurrentPosition(
        locationSettings: const LocationSettings(
          accuracy: LocationAccuracy.high,
          timeLimit: Duration(seconds: 15),
        ),
      );
      return Place(lat: position.latitude, lng: position.longitude);
    } on TimeoutException {
      throw const MyLocationUnavailable(
        'Não consegui achar a sua posição agora. Tente de novo ao ar livre, ou marque o ponto no mapa.',
      );
    }
  }
}
