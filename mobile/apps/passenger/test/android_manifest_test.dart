import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

void main() {
  test(
    'o manifesto principal pede permissao de internet (o de release precisa)',
    () {
      // O `flutter create` só põe INTERNET nos manifestos de debug e profile; sem ela no principal, o APK
      // de release instalado no celular não consegue falar com o servidor.
      final manifest = File('android/app/src/main/AndroidManifest.xml')
          .readAsStringSync();

      expect(
        manifest,
        contains('<uses-permission android:name="android.permission.INTERNET"'),
      );
    },
  );

  test('o backup do Android fica desligado (restaurar sem as chaves do Keystore estraga o login guardado)', () {
    final manifest = File(
      'android/app/src/main/AndroidManifest.xml',
    ).readAsStringSync();

    expect(manifest, contains('android:allowBackup="false"'));
  });
}
