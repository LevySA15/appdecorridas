import 'package:corrida_core/corrida_core.dart';
import 'package:geolocator/geolocator.dart';

/// O que o celular deixa o app fazer com a localização.
enum LocationAccess {
  /// Pode usar o GPS.
  granted,

  /// Negada agora; dá para perguntar de novo.
  denied,

  /// Negada para sempre; só nas configurações do celular.
  deniedForever,

  /// O GPS do celular está desligado.
  serviceOff,
}

/// O motoqueiro não pode ficar disponível sem GPS. A mensagem já diz o que fazer.
class LocationUnavailable implements Exception {
  const LocationUnavailable(this.message);

  final String message;

  @override
  String toString() => message;
}

/// De onde vem a posição do motoqueiro. Um GPS de verdade em produção; um de mentira (toque no mapa) para
/// testar em casa. Mesmo molde do `PhotoSource`: as telas e o controlador nunca falam com o plugin.
abstract class LocationSource {
  /// Pergunta à pessoa, se preciso, e diz como ficou.
  Future<LocationAccess> request();

  /// Liga o GPS enquanto alguém escuta e desliga quando cancela. Erro do GPS sai como erro do stream.
  Stream<Place> positions();
}

/// O modo "toque no mapa": a posição vem do `moveTo` do controlador, então o stream nunca emite.
class FakeLocationSource implements LocationSource {
  @override
  Future<LocationAccess> request() async => LocationAccess.granted;

  @override
  Stream<Place> positions() => const Stream<Place>.empty();
}

/// Junta o que o Android diz (serviço ligado? permissão?) numa resposta só.
LocationAccess accessFrom({
  required bool serviceEnabled,
  required LocationPermission permission,
}) {
  if (!serviceEnabled) return LocationAccess.serviceOff;
  return switch (permission) {
    LocationPermission.whileInUse ||
    LocationPermission.always => LocationAccess.granted,
    LocationPermission.deniedForever => LocationAccess.deniedForever,
    LocationPermission.denied ||
    LocationPermission.unableToDetermine => LocationAccess.denied,
  };
}

/// `--dart-define=GPS=real|fake` escolhe; sem a opção, o app de release usa o GPS de verdade e o de
/// depuração (`flutter run`) o de mentira.
bool useRealGps({required String flag, required bool isRelease}) =>
    switch (flag) {
      'real' => true,
      'fake' => false,
      _ => isRelease,
    };

/// O GPS do celular, com um serviço em primeiro plano (a notificação fixa) para a posição continuar
/// chegando com o app em segundo plano ou a tela apagada.
class GeolocatorLocationSource implements LocationSource {
  @override
  Future<LocationAccess> request() async {
    final serviceEnabled = await Geolocator.isLocationServiceEnabled();
    var permission = await Geolocator.checkPermission();
    if (serviceEnabled && permission == LocationPermission.denied) {
      permission = await Geolocator.requestPermission();
    }
    return accessFrom(serviceEnabled: serviceEnabled, permission: permission);
  }

  @override
  Stream<Place> positions() => Geolocator.getPositionStream(
    locationSettings: AndroidSettings(
      accuracy: LocationAccuracy.high,
      distanceFilter: 10,
      intervalDuration: const Duration(seconds: 4),
      foregroundNotificationConfig: const ForegroundNotificationConfig(
        notificationTitle: 'Recôncavo Motoqueiro',
        notificationText: 'Está usando o GPS enquanto você roda.',
        enableWakeLock: true,
        setOngoing: true,
      ),
    ),
  ).map((p) => Place(lat: p.latitude, lng: p.longitude));
}
