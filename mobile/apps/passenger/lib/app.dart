import 'dart:async';

import 'package:corrida_core/corrida_core.dart';
import 'package:corrida_ui/corrida_ui.dart';
import 'package:flutter/material.dart';

import 'passenger_controller.dart';
import 'screens/home_screen.dart';
import 'screens/request_ride_screen.dart';
import 'screens/ride_screen.dart';
import 'screens/wallet_screen.dart';

/// A raiz do app: enquanto `controller.starting`, uma tela de espera; sem sessão, o login; com
/// sessão, [SignedInShell]. Reage sozinho a qualquer mudança do [PassengerController].
class PassengerApp extends StatelessWidget {
  const PassengerApp({required this.controller, super.key});

  final PassengerController controller;

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      home: ListenableBuilder(
        listenable: controller,
        builder: (context, _) {
          if (controller.starting) {
            return const Scaffold(
              body: Center(child: CircularProgressIndicator()),
            );
          }
          final session = controller.session;
          if (session == null) {
            return LoginScreen(
              onRequestCode: controller.requestCode,
              onVerify: (phone, code) =>
                  controller.verify(phone: phone, code: code),
            );
          }
          return SignedInShell(
            controller: controller,
            key: ValueKey(session.userId),
          );
        },
      ),
    );
  }
}

/// A navegação de quem já entrou: uma pilha própria que começa na tela inicial e reage à corrida
/// terminando do outro lado (`state.ride` virando `null`) e a `trip_completed` (abre avaliar).
class SignedInShell extends StatefulWidget {
  const SignedInShell({required this.controller, super.key});

  final PassengerController controller;

  @override
  State<SignedInShell> createState() => _SignedInShellState();
}

class _SignedInShellState extends State<SignedInShell> {
  final _navigatorKey = GlobalKey<NavigatorState>();
  StreamSubscription<ServerEvent>? _eventsSub;

  /// Só a rota de acompanhar (empurrada por [_openRide]) deve ser desfeita quando a corrida some
  /// do estado — qualquer outra rota (carteira, pedir corrida, avaliar) não tem nada a ver com
  /// `state.ride`, que é `null` na maior parte do tempo.
  var _rideRouteOpen = false;

  @override
  void initState() {
    super.initState();
    widget.controller.addListener(_onControllerChanged);
    _eventsSub = widget.controller.events.listen(_onEvent);
  }

  @override
  void dispose() {
    widget.controller.removeListener(_onControllerChanged);
    unawaited(_eventsSub?.cancel());
    super.dispose();
  }

  void _onControllerChanged() {
    if (_rideRouteOpen && widget.controller.state?.ride == null) {
      _rideRouteOpen = false;
      _navigatorKey.currentState?.popUntil((route) => route.isFirst);
    }
  }

  void _onEvent(ServerEvent event) {
    if (event.type != 'trip_completed') return;
    final rideId = asString(event.data['ride_id']);
    // A corrida terminada sai do `state` (é terminal) assim que o próximo `refreshState` chegar;
    // tira a tela de acompanhar da pilha e desarma o `_onControllerChanged` agora, para essa
    // releitura (que corre em paralelo com este aviso) não derrubar a tela de avaliar que vamos
    // empurrar a seguir.
    _rideRouteOpen = false;
    _navigatorKey.currentState?.popUntil((route) => route.isFirst);
    _navigatorKey.currentState?.push(
      MaterialPageRoute(
        builder: (_) => RateScreen(
          onRate: (stars) async {
            await widget.controller.rate(rideId: rideId, stars: stars);
            final navigator = _navigatorKey.currentState;
            if (navigator != null && navigator.canPop()) navigator.pop();
          },
          onSkip: () => _navigatorKey.currentState!.pop(),
        ),
      ),
    );
  }

  void _showCharge(Charge charge) {
    _navigatorKey.currentState!.push(
      MaterialPageRoute(
        builder: (_) => ChargeScreen(
          charge: charge,
          onDone: () => _navigatorKey.currentState!.pop(),
        ),
      ),
    );
  }

  void _openRequestRide() {
    _navigatorKey.currentState!.push(
      MaterialPageRoute(
        builder: (_) => RequestRideScreen(
          onQuote: widget.controller.quote,
          onConfirm: (quoteId, method) async {
            await widget.controller.requestRide(
              quoteId: quoteId,
              method: method,
            );
            _navigatorKey.currentState!.pop();
          },
        ),
      ),
    );
  }

  void _openRide() {
    _rideRouteOpen = true;
    _navigatorKey.currentState!
        .push(
          MaterialPageRoute(
            builder: (_) => ListenableBuilder(
              listenable: widget.controller,
              builder: (context, _) {
                final ride = widget.controller.state?.ride;
                if (ride == null) return const SizedBox.shrink();
                return RideScreen(
                  ride: ride,
                  onLoadCharge: widget.controller.loadCharge,
                  onShowCharge: _showCharge,
                  onCancel: () => widget.controller.cancelRide(ride.rideId),
                  onSos: () => widget.controller.sos(ride.rideId),
                  onSafetyOk: (alertId) =>
                      widget.controller.safetyOk(ride.rideId, alertId),
                );
              },
            ),
          ),
        )
        .then((_) => _rideRouteOpen = false);
  }

  void _openWallet() {
    _navigatorKey.currentState!.push(
      MaterialPageRoute(
        builder: (_) => ListenableBuilder(
          listenable: widget.controller,
          builder: (context, _) => WalletScreen(
            state: widget.controller.state!,
            onTopup: widget.controller.topup,
            onWithdraw: (amountCents, pixKey) => widget.controller.withdraw(
              amountCents: amountCents,
              pixKey: pixKey,
            ),
            onSetEmergencyContact: (name, phone) => widget.controller
                .setEmergencyContact(name: name, phone: phone),
            onAppealFee: widget.controller.appealFee,
            onShowCharge: _showCharge,
          ),
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Navigator(
      key: _navigatorKey,
      onGenerateRoute: (settings) => MaterialPageRoute(
        builder: (_) => ListenableBuilder(
          listenable: widget.controller,
          builder: (context, _) => HomeScreen(
            state: widget.controller.state!,
            onRequestRide: _openRequestRide,
            onOpenRide: _openRide,
            onOpenWallet: _openWallet,
            onSignOut: widget.controller.signOut,
            onPayPendingFee: widget.controller.payPendingFee,
            onShowPendingCash: widget.controller.loadCharge,
            onShowCharge: _showCharge,
          ),
        ),
      ),
    );
  }
}
