import 'package:corrida_core/corrida_core.dart';
import 'package:corrida_ui/corrida_ui.dart';
import 'package:flutter/material.dart';

import '../dates.dart';
import 'offer_card.dart';

/// Tela inicial do motoqueiro aprovado: ficar disponível, oferta, corrida, cobrança em dinheiro, avisos de
/// entrada/dívida/documento e o resumo da conta — tudo direto de `RiderState`.
class HomeScreen extends StatefulWidget {
  const HomeScreen({
    required this.state,
    required this.onGoOnline,
    required this.onGoOffline,
    required this.onAcceptOffer,
    required this.onDeclineOffer,
    required this.onOpenRide,
    required this.onPayEntry,
    required this.onPayDebt,
    required this.onLoadCharge,
    required this.onShowCharge,
    required this.onCashReceived,
    required this.onRenewDocuments,
    required this.onOpenStatement,
    required this.onSignOut,
    this.clock,
    super.key,
  });

  final RiderState state;
  final Future<void> Function() onGoOnline;
  final Future<void> Function() onGoOffline;
  final Future<void> Function(String rideId) onAcceptOffer;
  final Future<void> Function(String rideId) onDeclineOffer;
  final VoidCallback onOpenRide;
  final Future<Charge> Function() onPayEntry;
  final Future<Charge> Function() onPayDebt;
  final Future<Charge> Function(String chargeId) onLoadCharge;
  final void Function(Charge) onShowCharge;
  final Future<void> Function(String rideId) onCashReceived;
  final VoidCallback onRenewDocuments;
  final VoidCallback onOpenStatement;
  final VoidCallback onSignOut;

  /// Só para teste.
  final DateTime Function()? clock;

  @override
  State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen> {
  var _busy = false;

  Future<void> _run(Future<void> Function() action) async {
    setState(() => _busy = true);
    try {
      await action();
    } on Exception catch (error) {
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(friendlyMessage(error))));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _showCharge(Future<Charge> Function() load) =>
      _run(() async => widget.onShowCharge(await load()));

  /// Os documentos vencidos ou que vencem em até 30 dias.
  List<String> _documentWarnings(RiderRegistration registration) {
    final today = (widget.clock ?? DateTime.now)();
    final start = DateTime(today.year, today.month, today.day);
    final lines = <String>[];
    void check(String name, DateTime? expiresOn) {
      if (expiresOn == null) return;
      final days = expiresOn.difference(start).inDays;
      if (days < 0) {
        lines.add('$name venceu em ${formatBrDate(expiresOn)}');
      } else if (days <= 30) {
        lines.add('$name vence em ${formatBrDate(expiresOn)}');
      }
    }

    check('A CNH', registration.cnhExpiresOn);
    check('O documento da moto', registration.crlvExpiresOn);
    return lines;
  }

  @override
  Widget build(BuildContext context) {
    final state = widget.state;
    final registration = state.registration;
    final account = state.account;
    final offer = state.offer;
    final awaiting = state.awaitingPayment;
    final warnings = _documentWarnings(registration);
    final rating = registration.rating;
    return Scaffold(
      appBar: AppBar(title: const Text('Recôncavo Motoqueiro')),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          SwitchListTile(
            title: const Text('Estou rodando'),
            value: registration.online,
            onChanged: _busy
                ? null
                : (on) => _run(on ? widget.onGoOnline : widget.onGoOffline),
          ),
          if (account?.blockedReason == 'entry_pending')
            Card(
              child: ListTile(
                title: Text(
                  'Você fez as ${account!.trialRides} corridas de teste. '
                  'Pague a entrada de ${brl(account.entryFeeCents)} para continuar.',
                ),
                trailing: FilledButton(
                  onPressed: _busy
                      ? null
                      : () => _showCharge(widget.onPayEntry),
                  child: const Text('Pagar entrada'),
                ),
              ),
            ),
          if (account?.blockedReason == 'debt_pending')
            Card(
              child: ListTile(
                title: Text('Taxa a pagar: ${brl(account!.debtToPayCents)}'),
                trailing: FilledButton(
                  onPressed: _busy ? null : () => _showCharge(widget.onPayDebt),
                  child: const Text('Pagar taxa'),
                ),
              ),
            ),
          if (warnings.isNotEmpty)
            Card(
              child: ListTile(
                title: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [for (final line in warnings) Text(line)],
                ),
                trailing: FilledButton(
                  onPressed: widget.onRenewDocuments,
                  child: const Text('Enviar novo'),
                ),
              ),
            ),
          if (offer != null)
            OfferCard(
              key: ValueKey(offer.rideId),
              offer: offer,
              clock: widget.clock,
              onAccept: () => widget.onAcceptOffer(offer.rideId),
              onDecline: () => widget.onDeclineOffer(offer.rideId),
            ),
          if (state.ride != null)
            Card(
              child: ListTile(
                title: const Text('Corrida em andamento'),
                trailing: FilledButton(
                  onPressed: widget.onOpenRide,
                  child: const Text('Abrir corrida'),
                ),
              ),
            ),
          if (state.queuedRide != null)
            Card(
              child: ListTile(
                title: Text(
                  'Próxima na fila: ${state.queuedRide!.passengerName}',
                ),
              ),
            ),
          if (awaiting != null)
            Card(
              child: Padding(
                padding: const EdgeInsets.all(16),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    Text(
                      'Cobrar ${brl(awaiting.endPayment?.amountCents ?? awaiting.priceCents)} em dinheiro',
                    ),
                    if (awaiting.endPayment?.blocked ?? false)
                      const Text(
                        'O passageiro foi bloqueado até pagar; você recebe quando ele pagar.',
                      ),
                    if (awaiting.endPayment?.chargeId != null)
                      OutlinedButton(
                        onPressed: _busy
                            ? null
                            : () => _showCharge(
                                () => widget.onLoadCharge(
                                  awaiting.endPayment!.chargeId!,
                                ),
                              ),
                        child: const Text('Ver Pix'),
                      ),
                    ElevatedButton(
                      onPressed: _busy
                          ? null
                          : () => _run(
                              () => widget.onCashReceived(awaiting.rideId),
                            ),
                      child: const Text('Recebi o dinheiro'),
                    ),
                  ],
                ),
              ),
            ),
          const SizedBox(height: 16),
          if (account != null && !account.entryPaid)
            Text(
              'Corridas de teste: ${account.completedRides} de ${account.trialRides}',
            ),
          if (rating != null)
            Text(
              '${rating.toStringAsFixed(1).replaceAll('.', ',')} '
              '(${registration.ratingCount} avaliações)',
            ),
          if (account != null && account.cashDebtCents > 0)
            Text('Taxas devidas: ${brl(account.cashDebtCents)}'),
          TextButton(
            onPressed: widget.onOpenStatement,
            child: const Text('Extrato do dia'),
          ),
          TextButton(onPressed: widget.onSignOut, child: const Text('Sair')),
        ],
      ),
    );
  }
}
