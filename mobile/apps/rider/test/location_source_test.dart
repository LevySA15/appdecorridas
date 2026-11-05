import 'package:flutter_test/flutter_test.dart';
import 'package:geolocator/geolocator.dart' show LocationPermission;
import 'package:rider/location_source.dart';
import 'package:rider/screen_awake.dart';

void main() {
  group('accessFrom', () {
    test('serviço de localização desligado manda ligar o GPS', () {
      for (final permission in LocationPermission.values) {
        expect(
          accessFrom(serviceEnabled: false, permission: permission),
          LocationAccess.serviceOff,
        );
      }
    });

    test('permissão concedida (só com o app aberto ou sempre)', () {
      for (final permission in [
        LocationPermission.whileInUse,
        LocationPermission.always,
      ]) {
        expect(
          accessFrom(serviceEnabled: true, permission: permission),
          LocationAccess.granted,
        );
      }
    });

    test('negada agora ainda dá para perguntar de novo', () {
      for (final permission in [
        LocationPermission.denied,
        LocationPermission.unableToDetermine,
      ]) {
        expect(
          accessFrom(serviceEnabled: true, permission: permission),
          LocationAccess.denied,
        );
      }
    });

    test('negada para sempre só se resolve nas configurações', () {
      expect(
        accessFrom(
          serviceEnabled: true,
          permission: LocationPermission.deniedForever,
        ),
        LocationAccess.deniedForever,
      );
    });
  });

  group('useRealGps', () {
    test('a opção escolhida manda', () {
      expect(useRealGps(flag: 'real', isRelease: false), isTrue);
      expect(useRealGps(flag: 'fake', isRelease: true), isFalse);
    });

    test('sem opção: release usa o GPS de verdade, depuração o de mentira', () {
      expect(useRealGps(flag: '', isRelease: true), isTrue);
      expect(useRealGps(flag: '', isRelease: false), isFalse);
      expect(useRealGps(flag: 'qualquer', isRelease: true), isTrue);
    });
  });

  test('o GPS de mentira sempre tem permissão e não emite nada sozinho', () async {
    final fake = FakeLocationSource();
    expect(await fake.request(), LocationAccess.granted);
    expect(await fake.positions().isEmpty, isTrue);
  });

  test('sem tela acesa de verdade, manter ligado não faz nada nem quebra', () async {
    await NoScreenAwake().keepOn(true);
    await NoScreenAwake().keepOn(false);
  });
}
