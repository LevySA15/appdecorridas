import 'package:corrida_core/corrida_core.dart';
import 'package:corrida_ui/corrida_ui.dart';
import 'package:flutter/material.dart';

/// Ponto de entrada: pedir ou acompanhar a corrida, e os avisos que a pessoa precisa ver de cara
/// (bloqueio, pagamento pendente, taxa pendente) — tudo direto de `PassengerState`.
class HomeScreen extends StatefulWidget {
  const HomeScreen({
    required this.state,
    required this.onRequestRide,
    required this.onOpenRide,
    required this.onOpenWallet,
    required this.onOpenProfile,
    required this.onOpenHistory,
    required this.onPayPendingFee,
    required this.onShowPendingCash,
    required this.onShowCharge,
    super.key,
  });

  final PassengerState state;
  final VoidCallback onRequestRide;
  final VoidCallback onOpenRide;
  final VoidCallback onOpenWallet;
  final VoidCallback onOpenProfile;
  final VoidCallback onOpenHistory;
  final Future<PayFeeResult> Function() onPayPendingFee;
  final Future<Charge> Function(String chargeId) onShowPendingCash;
  final void Function(Charge) onShowCharge;

  @override
  State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen> {
  var _payingFee = false;
  var _loadingCash = false;

  String _messageOf(Object error) => switch (error) {
    ApiException(message: final message) => message,
    NetworkException(message: final message) => message,
    _ => 'Algo deu errado. Tente de novo.',
  };

  void _showError(Object error) {
    if (!mounted) return;
    ScaffoldMessenger.of(context)
        .showSnackBar(SnackBar(content: Text(_messageOf(error))));
  }

  Future<void> _showPendingCash(String chargeId) async {
    setState(() => _loadingCash = true);
    try {
      final charge = await widget.onShowPendingCash(chargeId);
      widget.onShowCharge(charge);
    } on Exception catch (error) {
      _showError(error);
    } finally {
      if (mounted) setState(() => _loadingCash = false);
    }
  }

  Future<void> _payPendingFee() async {
    setState(() => _payingFee = true);
    try {
      final result = await widget.onPayPendingFee();
      if (!result.paid) widget.onShowCharge(result.charge!);
    } on Exception catch (error) {
      _showError(error);
    } finally {
      if (mounted) setState(() => _payingFee = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final state = widget.state;
    final theme = Theme.of(context);
    final hasRide = state.ride != null;
    return Scaffold(
      body: Stack(
        children: [
          const Positioned.fill(child: FakeMapView(markers: [])),
          SafeArea(
            child: Padding(
              padding: const EdgeInsets.all(16),
              child: Align(
                alignment: Alignment.topLeft,
                child: Container(
                  padding: const EdgeInsets.symmetric(
                    horizontal: 14,
                    vertical: 10,
                  ),
                  decoration: BoxDecoration(
                    color: theme.colorScheme.surface,
                    borderRadius: BorderRadius.circular(99),
                    boxShadow: [
                      BoxShadow(
                        color: Colors.black.withValues(alpha: 0.12),
                        blurRadius: 12,
                      ),
                    ],
                  ),
                  child: Text(
                    'Recôncavo',
                    style: theme.textTheme.titleMedium?.copyWith(
                      fontWeight: FontWeight.w800,
                    ),
                  ),
                ),
              ),
            ),
          ),
          Align(
            alignment: Alignment.bottomCenter,
            child: ConstrainedBox(
              constraints: BoxConstraints(
                maxHeight: MediaQuery.sizeOf(context).height * 0.75,
              ),
              child: SheetCard(
                child: SingleChildScrollView(
                  child: Column(
                    mainAxisSize: MainAxisSize.min,
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: [
                      if (state.pendingPayment != null) ...[
                        NoticeCard(
                          title: brl(state.pendingPayment!.amountCents),
                          body: 'Corrida em dinheiro não paga',
                          // chargeId é nulo até o motoqueiro pedir o QR do fim da corrida; sem QR não há
                          // o que mostrar ainda.
                          action: state.pendingPayment!.chargeId == null
                              ? null
                              : FilledButton(
                                  onPressed: _loadingCash
                                      ? null
                                      : () => _showPendingCash(
                                          state.pendingPayment!.chargeId!,
                                        ),
                                  child: _loadingCash
                                      ? const SizedBox(
                                          width: 16,
                                          height: 16,
                                          child: CircularProgressIndicator(
                                            strokeWidth: 2,
                                          ),
                                        )
                                      : const Text('Ver Pix'),
                                ),
                        ),
                        const SizedBox(height: 12),
                      ],
                      if (state.pendingFee != null) ...[
                        NoticeCard(
                          title: brl(state.pendingFee!.amountCents),
                          body: 'Taxa de cancelamento pendente',
                          action: FilledButton(
                            onPressed: _payingFee ? null : _payPendingFee,
                            child: _payingFee
                                ? const SizedBox(
                                    width: 16,
                                    height: 16,
                                    child: CircularProgressIndicator(
                                      strokeWidth: 2,
                                    ),
                                  )
                                : const Text('Pagar'),
                          ),
                        ),
                        const SizedBox(height: 12),
                      ],
                      Text(
                        hasRide
                            ? 'Sua corrida está rolando'
                            : 'Pra onde vamos?',
                        style: theme.textTheme.headlineSmall,
                      ),
                      const SizedBox(height: 14),
                      if (hasRide)
                        ElevatedButton(
                          onPressed: widget.onOpenRide,
                          child: const Text('Acompanhar corrida'),
                        )
                      // com pagamento ou taxa pendente o cartão de cima já explica; repetir o bloqueio só assusta
                      else if (state.blockedReason != null &&
                          state.pendingFee == null &&
                          state.pendingPayment == null)
                        NoticeCard(
                          title: 'Pedido de corrida bloqueado',
                          body: state.blockedReason!,
                        )
                      else
                        ElevatedButton(
                          onPressed: widget.onRequestRide,
                          child: const Text('Pedir corrida'),
                        ),
                      const SizedBox(height: 14),
                      IntrinsicHeight(
                        child: Row(
                          crossAxisAlignment: CrossAxisAlignment.stretch,
                          children: [
                            Expanded(
                              child: _Shortcut(
                                icon: Icons.account_balance_wallet_outlined,
                                label: 'Carteira',
                                detail: brl(state.balanceCents),
                                onTap: widget.onOpenWallet,
                              ),
                            ),
                            const SizedBox(width: 10),
                            Expanded(
                              child: _Shortcut(
                                icon: Icons.history_rounded,
                                label: 'Minhas corridas',
                                onTap: widget.onOpenHistory,
                              ),
                            ),
                            const SizedBox(width: 10),
                            Expanded(
                              child: _Shortcut(
                                icon: Icons.person_outline_rounded,
                                label: 'Perfil',
                                detail: state.name,
                                onTap: widget.onOpenProfile,
                              ),
                            ),
                          ],
                        ),
                      ),
                    ],
                  ),
                ),
              ),
            ),
          ),
        ],
      ),
    );
  }
}

/// Atalho da folha de baixo: ícone, nome e (se tiver) um detalhe curto.
class _Shortcut extends StatelessWidget {
  const _Shortcut({
    required this.icon,
    required this.label,
    required this.onTap,
    this.detail,
  });

  final IconData icon;
  final String label;
  final String? detail;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return Material(
      color: scheme.surfaceContainer,
      borderRadius: BorderRadius.circular(16),
      child: InkWell(
        borderRadius: BorderRadius.circular(16),
        onTap: onTap,
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 12),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Icon(icon, size: 22),
              const SizedBox(height: 8),
              Text(
                label,
                maxLines: 2,
                style: const TextStyle(fontWeight: FontWeight.w700),
              ),
              Text(
                detail ?? ' ',
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: TextStyle(color: scheme.onSurfaceVariant, fontSize: 12),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
