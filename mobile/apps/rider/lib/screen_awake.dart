import 'package:wakelock_plus/wakelock_plus.dart';

/// Manter a tela acesa enquanto o motoqueiro roda (a posição e as ofertas dependem do app à vista).
abstract class ScreenAwake {
  Future<void> keepOn(bool on);
}

/// Segura a tela acesa de verdade (`wakelock_plus`).
class WakelockScreenAwake implements ScreenAwake {
  @override
  Future<void> keepOn(bool on) => WakelockPlus.toggle(enable: on);
}

/// Não faz nada: testes e o modo de mentira.
class NoScreenAwake implements ScreenAwake {
  @override
  Future<void> keepOn(bool on) async {}
}
