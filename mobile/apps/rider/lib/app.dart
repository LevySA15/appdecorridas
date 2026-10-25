import 'dart:async';

import 'package:corrida_core/corrida_core.dart';
import 'package:corrida_ui/corrida_ui.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import 'rider_controller.dart';
import 'screens/home_screen.dart';
import 'screens/registration_screen.dart';
import 'screens/renew_documents_screen.dart';
import 'screens/ride_screen.dart';
import 'screens/statement_screen.dart';
import 'screens/status_screen.dart';

/// A raiz do app: enquanto `controller.starting`, uma tela de espera; sem sessão, o login; com sessão,
/// [SignedInShell]. Reage sozinho a qualquer mudança do [RiderController].
class RiderApp extends StatelessWidget {
  const RiderApp({required this.controller, super.key});

  final RiderController controller;

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

/// A navegação de quem já entrou: uma pilha própria; a tela raiz muda sozinha conforme o cadastro
/// (cadastrar, esperar, home) e as outras telas são empilhadas por cima. Reage aos avisos do tempo real.
class SignedInShell extends StatefulWidget {
  const SignedInShell({required this.controller, super.key});

  final RiderController controller;

  @override
  State<SignedInShell> createState() => _SignedInShellState();
}

class _SignedInShellState extends State<SignedInShell> {
  final _navigatorKey = GlobalKey<NavigatorState>();
  StreamSubscription<ServerEvent>? _eventsSub;

  /// Só a rota da corrida (empurrada por [_openRide]) deve ser desfeita quando a corrida some do estado;
  /// qualquer outra rota (Pix, avaliar, renovar) não tem nada a ver com `state.ride`.
  var _rideRouteOpen = false;

  RiderController get _controller => widget.controller;

  @override
  void initState() {
    super.initState();
    _controller.addListener(_onControllerChanged);
    _eventsSub = _controller.events.listen(_onEvent);
  }

  @override
  void dispose() {
    _controller.removeListener(_onControllerChanged);
    unawaited(_eventsSub?.cancel());
    super.dispose();
  }

  void _onControllerChanged() {
    if (_rideRouteOpen && _controller.state?.ride == null) {
      _closeRideRoute();
    }
  }

  void _closeRideRoute() {
    _rideRouteOpen = false;
    _navigatorKey.currentState?.popUntil((route) => route.isFirst);
  }

  void _toast(String message) {
    final context = _navigatorKey.currentContext;
    if (context == null) return;
    ScaffoldMessenger.of(context)
        .showSnackBar(SnackBar(content: Text(message)));
  }

  void _onEvent(ServerEvent event) {
    switch (event.type) {
      case 'offer':
        unawaited(HapticFeedback.heavyImpact());
        unawaited(SystemSound.play(SystemSoundType.alert));
      case 'trip_completed':
        _onTripCompleted(asString(event.data['ride_id']));
      case 'ride_cancelled':
        _onRideCancelled(event.data);
      case 'passenger_blocked':
        _toast(
          'O passageiro foi bloqueado por falta de pagamento. Você está livre.',
        );
      case 'next_ride':
        _toast('Sua corrida da fila começou. Toque em abrir corrida.');
      case 'rider_approved':
        _toast('Seu cadastro foi aprovado!');
      case 'rider_unblocked':
        _toast('Sua conta foi liberada.');
      case 'rider_rejected':
        _toast('Seu cadastro foi recusado. Veja o motivo e envie de novo.');
      case 'rider_blocked':
        _toast('Sua conta foi bloqueada.');
      case 'documents_expired':
        _toast(
          'Um documento seu venceu. Envie o novo para voltar a receber corridas.',
        );
      case 'entry_required':
        _toast('Você precisa pagar a entrada para continuar.');
      case 'debt_required':
        _toast('Você tem uma taxa a pagar para voltar a receber corridas.');
    }
  }

  void _onTripCompleted(String rideId) {
    // A corrida terminada sai do `state` assim que a próxima releitura chegar; fecha a tela da corrida e
    // desarma o `_onControllerChanged` agora, para essa releitura (que corre em paralelo com este aviso)
    // não derrubar a tela de avaliar que vamos empurrar a seguir.
    _closeRideRoute();
    _navigatorKey.currentState?.push(
      MaterialPageRoute(
        builder: (_) => RateScreen(
          onRate: (stars) async {
            await _controller.rate(rideId: rideId, stars: stars);
            final navigator = _navigatorKey.currentState;
            if (navigator != null && navigator.canPop()) navigator.pop();
          },
          onSkip: () => _navigatorKey.currentState!.pop(),
        ),
      ),
    );
  }

  void _onRideCancelled(Json data) {
    final cancelledId = asString(data['ride_id']);
    final isCurrent = cancelledId == _controller.state?.ride?.rideId;
    if (!isCurrent) {
      // a corrida da fila: a atual segue
      _toast('O passageiro da próxima corrida cancelou.');
      return;
    }
    _closeRideRoute();
    final fee = asInt(data['fee_cents']);
    final reason = asStringOrNull(data['reason']);
    if (asStringOrNull(data['by']) == 'passenger') {
      _toast(
        'O passageiro cancelou a corrida.'
        '${fee > 0 ? ' Taxa de cancelamento: ${brl(fee)}.' : ''}',
      );
    } else if (reason == 'pix_expired') {
      _toast('O passageiro não pagou o Pix a tempo.');
    } else if (reason == 'arrival_wait') {
      _toast('Passou o tempo de espera no ponto de embarque.');
    } else {
      _toast('A corrida foi cancelada.');
    }
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

  Future<void> _accept(String rideId) async {
    await _controller.accept(rideId);
    _openRide();
  }

  void _openRide() {
    // aceitar uma oferta da fila de dentro da tela da corrida não empilha outra tela
    if (_rideRouteOpen || _controller.state?.ride == null) return;
    _rideRouteOpen = true;
    _navigatorKey.currentState!
        .push(
          MaterialPageRoute(
            builder: (_) => ListenableBuilder(
              listenable: _controller,
              builder: (context, _) {
                final state = _controller.state;
                final ride = state?.ride;
                if (ride == null) return const SizedBox.shrink();
                return RideScreen(
                  ride: ride,
                  position: _controller.position,
                  offer: state?.offer,
                  onMove: _controller.moveTo,
                  onArrive: () => _controller.arrive(ride.rideId),
                  onConfirmHelmet: () => _controller.confirmHelmet(ride.rideId),
                  onStart: (pin) => _controller.startTrip(ride.rideId, pin),
                  onComplete: () => _controller.completeTrip(ride.rideId),
                  onAcceptOffer: _accept,
                  onDeclineOffer: _controller.decline,
                );
              },
            ),
          ),
        )
        .then((_) => _rideRouteOpen = false);
  }

  void _openStatement() {
    _navigatorKey.currentState!.push(
      MaterialPageRoute(
        builder: (_) => StatementScreen(onLoad: _controller.loadStatement),
      ),
    );
  }

  void _openRenew() {
    _navigatorKey.currentState!.push(
      MaterialPageRoute(
        builder: (_) => RenewDocumentsScreen(
          onPickPhoto: _controller.pickPhoto,
          onSubmit: (cnh, crlv, cnhPhoto, crlvPhoto) async {
            await _controller.renewDocuments(
              cnhExpiresOn: cnh,
              crlvExpiresOn: crlv,
              cnhPhoto: cnhPhoto,
              crlvPhoto: crlvPhoto,
            );
            final navigator = _navigatorKey.currentState;
            if (navigator != null && navigator.canPop()) navigator.pop();
          },
        ),
      ),
    );
  }

  Widget _root(RiderState? state) {
    if (state == null) {
      return const Scaffold(body: Center(child: CircularProgressIndicator()));
    }
    switch (state.registration.status) {
      case RegistrationStatus.notRegistered || RegistrationStatus.rejected:
        return RegistrationScreen(
          onPickPhoto: _controller.pickPhoto,
          onSubmit: _controller.registerRider,
          onSignOut: _controller.signOut,
          rejectionReason:
              state.registration.status == RegistrationStatus.rejected
              ? (state.registration.reason ?? '')
              : null,
        );
      case RegistrationStatus.approved:
        return HomeScreen(
          state: state,
          onGoOnline: _controller.goOnline,
          onGoOffline: _controller.goOffline,
          onAcceptOffer: _accept,
          onDeclineOffer: _controller.decline,
          onOpenRide: _openRide,
          onPayEntry: _controller.entryCharge,
          onPayDebt: _controller.debtCharge,
          onLoadCharge: _controller.loadCharge,
          onShowCharge: _showCharge,
          onCashReceived: _controller.cashReceived,
          onRenewDocuments: _openRenew,
          onOpenStatement: _openStatement,
          onSignOut: _controller.signOut,
        );
      case RegistrationStatus.pending ||
          RegistrationStatus.blocked ||
          RegistrationStatus.unknown:
        return StatusScreen(
          registration: state.registration,
          onRefresh: _controller.refreshState,
          onSignOut: _controller.signOut,
          onRenewDocuments: _openRenew,
        );
    }
  }

  @override
  Widget build(BuildContext context) {
    return Navigator(
      key: _navigatorKey,
      onGenerateRoute: (settings) => MaterialPageRoute(
        builder: (_) => ListenableBuilder(
          listenable: _controller,
          builder: (context, _) => _root(_controller.state),
        ),
      ),
    );
  }
}
