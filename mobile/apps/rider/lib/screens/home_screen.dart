import 'package:corrida_core/corrida_core.dart';
import 'package:corrida_ui/corrida_ui.dart';
import 'package:flutter/material.dart';

import '../dates.dart';
import '../location_source.dart';
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
    this.locationProblem,
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

  /// Aviso do GPS (sem permissão, sem sinal) enquanto o motoqueiro roda; `null` quando está tudo bem.
  final String? locationProblem;

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
      final message = error is LocationUnavailable
          ? error.message
          : friendlyMessage(error);
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(message)));
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
          _StatusHero(
            online: registration.online,
            busy: _busy,
            onChanged: (on) =>
                _run(on ? widget.onGoOnline : widget.onGoOffline),
          ),
          const SizedBox(height: 12),
          if (widget.locationProblem case final problem?)
            Card(
              color: Theme.of(context).colorScheme.errorContainer,
              child: ListTile(
                leading: const Icon(Icons.location_off),
                title: Text(problem),
              ),
            ),
          if (account?.blockedReason == 'entry_pending')
            NoticeCard(
              title:
                  'Você fez as ${account!.trialRides} corridas de teste. '
                  'Pague a entrada de ${brl(account.entryFeeCents)} para continuar.',
              action: FilledButton(
                onPressed: _busy ? null : () => _showCharge(widget.onPayEntry),
                child: const Text('Pagar entrada'),
              ),
            ),
          if (account?.blockedReason == 'debt_pending')
            NoticeCard(
              title: 'Taxa a pagar: ${brl(account!.debtToPayCents)}',
              action: FilledButton(
                onPressed: _busy ? null : () => _showCharge(widget.onPayDebt),
                child: const Text('Pagar taxa'),
              ),
            ),
          if (warnings.isNotEmpty)
            NoticeCard(
              children: [
                for (final line in warnings)
                  Text(
                    line,
                    style: const TextStyle(fontWeight: FontWeight.w700),
                  ),
              ],
              action: FilledButton(
                onPressed: widget.onRenewDocuments,
                child: const Text('Enviar novo'),
              ),
            ),
          // sem estar rodando a oferta pendente já não vale (aceitar dá 409): não aparece
          if (offer != null && registration.online)
            OfferCard(
              key: ValueKey(offer.rideId),
              offer: offer,
              clock: widget.clock,
              onAccept: () => widget.onAcceptOffer(offer.rideId),
              onDecline: () => widget.onDeclineOffer(offer.rideId),
            ),
          if (state.ride != null)
            NoticeCard(
              title: 'Corrida em andamento',
              action: FilledButton(
                onPressed: widget.onOpenRide,
                child: const Text('Abrir corrida'),
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
          Wrap(
            spacing: 8,
            runSpacing: 8,
            children: [
              if (account != null && !account.entryPaid)
                InfoPill(
                  icon: Icons.flag_outlined,
                  text:
                      'Corridas de teste: ${account.completedRides} de ${account.trialRides}',
                ),
              if (rating != null)
                InfoPill(
                  icon: Icons.star_rounded,
                  text:
                      '${rating.toStringAsFixed(1).replaceAll('.', ',')} '
                      '(${registration.ratingCount} avaliações)',
                ),
              if (account != null && account.cashDebtCents > 0)
                InfoPill(
                  icon: Icons.receipt_long_outlined,
                  text: 'Taxas devidas: ${brl(account.cashDebtCents)}',
                ),
            ],
          ),
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

/// O cartão grande do alto: liga e desliga o "estou rodando". Ligado, fica com o vermelho do app.
class _StatusHero extends StatelessWidget {
  const _StatusHero({
    required this.online,
    required this.busy,
    required this.onChanged,
  });

  final bool online;
  final bool busy;
  final ValueChanged<bool> onChanged;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final fg = online ? corridaOnAccent : scheme.onSurface;
    return Container(
      padding: const EdgeInsets.fromLTRB(20, 16, 12, 16),
      decoration: BoxDecoration(
        color: online ? corridaAccent : scheme.surfaceContainer,
        borderRadius: BorderRadius.circular(22),
      ),
      child: Row(
        children: [
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  'Estou rodando',
                  style: TextStyle(
                    color: fg,
                    fontSize: 22,
                    fontWeight: FontWeight.w800,
                    letterSpacing: -0.3,
                  ),
                ),
                const SizedBox(height: 2),
                Text(
                  online
                      ? 'Esperando pedidos perto de você'
                      : 'Ligue para receber corridas',
                  style: TextStyle(
                    color: online
                        ? corridaOnAccent.withValues(alpha: 0.85)
                        : scheme.onSurfaceVariant,
                  ),
                ),
              ],
            ),
          ),
          Switch(
            value: online,
            onChanged: busy ? null : onChanged,
            activeThumbColor: corridaAccent,
            activeTrackColor: corridaOnAccent,
          ),
        ],
      ),
    );
  }
}
