// Telas em celular pequeno (320x568) e com letra grande (1,5x): nada pode estourar a tela nem ficar escondido.
// Um "RenderFlex overflowed" vira exceção no teste.
import 'package:corrida_core/corrida_core.dart';
import 'package:corrida_ui/corrida_ui.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:passenger/screens/home_screen.dart';
import 'package:passenger/screens/profile_screen.dart';
import 'package:passenger/screens/request_ride_screen.dart';
import 'package:passenger/screens/ride_screen.dart';

const _rider = RiderCard(
  riderId: 'r',
  name: 'João Carlos da Silva Santos',
  plate: 'ABC1D23',
  motoModel: 'Honda CG 160 Titan Start',
  rating: 4.8,
  ratingCount: 30,
  photoUrl: null,
);

Widget _app(Widget home, {required Brightness brightness, double text = 1.5}) {
  return MaterialApp(
    theme: corridaTheme(brightness),
    locale: corridaLocale,
    supportedLocales: corridaSupportedLocales,
    localizationsDelegates: corridaLocalizationsDelegates,
    builder: (context, child) => MediaQuery(
      data: MediaQuery.of(context).copyWith(textScaler: TextScaler.linear(text)),
      child: child!,
    ),
    home: home,
  );
}

Future<void> _pequeno(WidgetTester tester) async {
  tester.view.devicePixelRatio = 2;
  tester.view.physicalSize = const Size(640, 1136); // 320x568 pontos
  addTearDown(tester.view.reset);
}

HomeScreen _home(PassengerState state) => HomeScreen(
  state: state,
  onRequestRide: () {},
  onOpenRide: () {},
  onOpenWallet: () {},
  onOpenProfile: () {},
  onOpenHistory: () {},
  onPayPendingFee: () async => const PayFeeResult(paid: true),
  onShowPendingCash: (_) async => const Charge(chargeId: 'c', amountCents: 1),
  onShowCharge: (_) {},
);

RideScreen _ride(PassengerRide ride) => RideScreen(
  ride: ride,
  onLoadCharge: (_) async => const Charge(chargeId: 'c', amountCents: 1),
  onShowCharge: (_) {},
  onCancel: () async => const CancelResult(
    refund: false,
    feeCents: 0,
    fee: null,
    refundTo: null,
    balanceCents: 0,
  ),
  onSos: () async => const SosResult(
    alertId: 1,
    contactRegistered: true,
    contactNotified: true,
    repeated: false,
    emergencyNumber: '190',
  ),
  onSafetyOk: (_) async {},
);

void main() {
  for (final brightness in Brightness.values) {
    final modo = brightness == Brightness.dark ? 'escuro' : 'claro';

    testWidgets('início sem pendência ($modo)', (tester) async {
      await _pequeno(tester);
      await tester.pumpWidget(
        _app(
          _home(const PassengerState(name: 'Maria Aparecida de Souza', balanceCents: 123456)),
          brightness: brightness,
        ),
      );
      await tester.pumpAndSettle();
      expect(tester.takeException(), isNull);
    });

    testWidgets('início com pagamento e taxa pendentes ($modo)', (tester) async {
      await _pequeno(tester);
      await tester.pumpWidget(
        _app(
          _home(
            const PassengerState(
              name: 'Maria',
              pendingPayment: PendingPayment(rideId: 'r', amountCents: 1250, chargeId: 'c'),
              pendingFee: PendingFee(rideId: 'r2', amountCents: 500),
              blockedReason: 'Falta pagar a taxa do cancelamento. Pague para pedir outra moto.',
            ),
          ),
          brightness: brightness,
        ),
      );
      await tester.pumpAndSettle();
      expect(tester.takeException(), isNull);
    });

    testWidgets('acompanhar com motoqueiro, código e Pix ($modo)', (tester) async {
      await _pequeno(tester);
      await tester.pumpWidget(
        _app(
          _ride(
            const PassengerRide(
              rideId: 'r',
              state: RideState.accepted,
              pin: '4821',
              method: 'pix',
              priceCents: 1850,
              distanceM: 12500,
              rider: _rider,
              pay: PixToPay(chargeId: 'c', amountCents: 1850, expiresAt: 9999999999),
            ),
          ),
          brightness: brightness,
        ),
      );
      await tester.pumpAndSettle();
      expect(tester.takeException(), isNull);
    });

    testWidgets('perfil ($modo)', (tester) async {
      await _pequeno(tester);
      await tester.pumpWidget(
        _app(
          ProfileScreen(
            state: const PassengerState(name: 'Maria Aparecida de Souza', phone: '+5575999990001'),
            onSaveName: (_) async {},
            onSetEmergencyContact: (_, _) async {},
            onSignOut: () {},
          ),
          brightness: brightness,
        ),
      );
      await tester.pumpAndSettle();
      expect(tester.takeException(), isNull);
    });

    testWidgets('pedir corrida: cotação ($modo)', (tester) async {
      await _pequeno(tester);
      await tester.pumpWidget(
        _app(
          RequestRideScreen(
            onQuote: (a, b) async => const Quote(
              quoteId: 'q',
              priceCents: 1850,
              distanceM: 12500,
              durationS: 900,
              reason: 'normal',
              expiresAt: 9999999999,
              pickup: Place(lat: -12.96, lng: -39.26),
              destination: Place(lat: -12.97, lng: -39.27),
              etaSeconds: 600,
              nearbyRiders: 3,
              paymentMethods: ['pix', 'cash', 'balance'],
            ),
            onConfirm: (_, _) async {},
          ),
          brightness: brightness,
        ),
      );
      final rect = tester.getRect(find.byType(FakeMapPicker));
      await tester.tapAt(rect.topLeft + const Offset(40, 40));
      await tester.pump();
      await tester.tapAt(rect.bottomRight - const Offset(40, 160));
      await tester.pumpAndSettle();
      expect(find.text('Pedir corrida'), findsOneWidget);
      expect(tester.takeException(), isNull);
    });
  }
}
