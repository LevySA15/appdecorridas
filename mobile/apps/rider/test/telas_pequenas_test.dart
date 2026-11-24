// Telas do motoqueiro em celular pequeno (320x568) e com letra grande (1,5x): nada pode estourar a tela.
import 'package:corrida_core/corrida_core.dart';
import 'package:corrida_ui/corrida_ui.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:rider/screens/home_screen.dart';
import 'package:rider/screens/ride_screen.dart';

Widget _app(Widget home, Brightness brightness) => MaterialApp(
  theme: corridaTheme(brightness),
  locale: corridaLocale,
  supportedLocales: corridaSupportedLocales,
  localizationsDelegates: corridaLocalizationsDelegates,
  builder: (context, child) => MediaQuery(
    data: MediaQuery.of(context).copyWith(textScaler: const TextScaler.linear(1.5)),
    child: child!,
  ),
  home: home,
);

void _pequeno(WidgetTester tester) {
  tester.view.devicePixelRatio = 2;
  tester.view.physicalSize = const Size(640, 1136);
  addTearDown(tester.view.reset);
}

RiderState _estado({RiderAccount? account, Offer? offer, RiderRide? awaiting, bool online = true}) => RiderState(
  registration: RiderRegistration(
    status: RegistrationStatus.approved,
    online: online,
    cnhExpiresOn: DateTime(2026, 11, 10),
    crlvExpiresOn: DateTime(2026, 10, 1),
    rating: 4.87,
    ratingCount: 123,
  ),
  account: account,
  offer: offer,
  awaitingPayment: awaiting,
);

HomeScreen _home(RiderState state) => HomeScreen(
  state: state,
  onGoOnline: () async {},
  onGoOffline: () async {},
  onAcceptOffer: (_) async {},
  onDeclineOffer: (_) async {},
  onOpenRide: () {},
  onPayEntry: () async => const Charge(chargeId: 'e', amountCents: 5000),
  onPayDebt: () async => const Charge(chargeId: 'd', amountCents: 70),
  onLoadCharge: (id) async => Charge(chargeId: id, amountCents: 700),
  onShowCharge: (_) {},
  onCashReceived: (_) async {},
  onRenewDocuments: () {},
  onOpenStatement: () {},
  onSignOut: () {},
  locationProblem: 'Sem sinal de GPS: vá para um lugar aberto.',
  clock: () => DateTime(2026, 10, 25),
);

RideScreen _ride(RideState state) => RideScreen(
  ride: RiderRide(
    rideId: 'r',
    state: state,
    priceCents: 1850,
    method: 'pix',
    pixPaid: true,
    helmetConfirmed: true,
    passengerName: 'Maria Aparecida de Souza',
    pickup: const Place(lat: -12.96, lng: -39.26, text: 'Rua Conselheiro Franco, 1234, Centro'),
    destination: const Place(lat: -12.97, lng: -39.25, text: 'Avenida Senhor dos Passos, 99, Irmã Dulce'),
  ),
  position: const Place(lat: -12.964, lng: -39.259),
  onMove: (_) {},
  onArrive: () async {},
  onConfirmHelmet: () async {},
  onStart: (_) async {},
  onComplete: () async {},
  onAcceptOffer: (_) async {},
  onDeclineOffer: (_) async {},
  onSos: () async => const RiderSosResult(alertId: 1, repeated: false, emergencyNumber: '190'),
);

void main() {
  for (final brightness in Brightness.values) {
    final modo = brightness == Brightness.dark ? 'escuro' : 'claro';

    testWidgets('início com oferta, avisos e dívida ($modo)', (tester) async {
      _pequeno(tester);
      await tester.pumpWidget(
        _app(
          _home(
            _estado(
              account: const RiderAccount(
                completedRides: 3,
                trialRides: 10,
                entryPaid: false,
                entryFeeCents: 5000,
                needsEntry: false,
                blockedReason: 'debt_pending',
                cashDebtCents: 100,
                cashDebtLimitCents: 70,
                debtToPayCents: 100,
              ),
              offer: const Offer(
                rideId: 'o',
                priceCents: 1850,
                paymentMethod: 'cash',
                distanceM: 12500,
                secondsToPickup: 600,
                willQueue: true,
                expiresAt: 9999999999,
                pickup: Place(lat: 0, lng: 0, text: 'Rua Conselheiro Franco, 1234, Centro'),
                destination: Place(lat: 0, lng: 0, text: 'Avenida Senhor dos Passos, 99'),
              ),
            ),
          ),
          brightness,
        ),
      );
      await tester.pump();
      expect(tester.takeException(), isNull);
    });

    for (final state in [RideState.accepted, RideState.arrived, RideState.inProgress]) {
      testWidgets('corrida ${state.name} ($modo)', (tester) async {
        _pequeno(tester);
        await tester.pumpWidget(_app(_ride(state), brightness));
        await tester.pump();
        expect(tester.takeException(), isNull);
      });
    }
  }
}
