import 'package:corrida_core/corrida_core.dart';
import 'package:flutter/material.dart';

/// Ponto de entrada: pedir ou acompanhar a corrida, e os avisos que a pessoa precisa ver de cara
/// (bloqueio, pagamento pendente, taxa pendente) — tudo direto de `PassengerState`.
class HomeScreen extends StatefulWidget {
  const HomeScreen({
    required this.state,
    required this.onRequestRide,
    required this.onOpenRide,
    required this.onOpenWallet,
    required this.onSignOut,
    required this.onPayPendingFee,
    required this.onShowPendingCash,
    required this.onShowCharge,
    super.key,
  });

  final PassengerState state;
  final VoidCallback onRequestRide;
  final VoidCallback onOpenRide;
  final VoidCallback onOpenWallet;
  final VoidCallback onSignOut;
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
    ScaffoldMessenger.of(
      context,
    ).showSnackBar(SnackBar(content: Text(_messageOf(error))));
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
    return Scaffold(
      appBar: AppBar(title: const Text('Recôncavo')),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          if (state.ride != null)
            ElevatedButton(
              onPressed: widget.onOpenRide,
              child: const Text('Acompanhar corrida'),
            )
          else if (state.blockedReason != null)
            Text(state.blockedReason!)
          else
            ElevatedButton(
              onPressed: widget.onRequestRide,
              child: const Text('Pedir corrida'),
            ),
          if (state.pendingPayment != null) ...[
            const SizedBox(height: 16),
            Card(
              child: ListTile(
                title: Text(brl(state.pendingPayment!.amountCents)),
                subtitle: const Text('Corrida em dinheiro não paga'),
                // chargeId é nulo até o motoqueiro pedir o QR do fim da corrida; sem QR não há
                // o que mostrar ainda.
                trailing: state.pendingPayment!.chargeId == null
                    ? null
                    : FilledButton(
                        onPressed: _loadingCash
                            ? null
                            : () =>
                                  _showPendingCash(state.pendingPayment!.chargeId!),
                        child: _loadingCash
                            ? const SizedBox(
                                width: 16,
                                height: 16,
                                child: CircularProgressIndicator(strokeWidth: 2),
                              )
                            : const Text('Ver Pix'),
                      ),
              ),
            ),
          ],
          if (state.pendingFee != null) ...[
            const SizedBox(height: 16),
            Card(
              child: ListTile(
                title: Text(brl(state.pendingFee!.amountCents)),
                subtitle: const Text('Taxa de cancelamento pendente'),
                trailing: FilledButton(
                  onPressed: _payingFee ? null : _payPendingFee,
                  child: _payingFee
                      ? const SizedBox(
                          width: 16,
                          height: 16,
                          child: CircularProgressIndicator(strokeWidth: 2),
                        )
                      : const Text('Pagar'),
                ),
              ),
            ),
          ],
          const SizedBox(height: 24),
          ListTile(
            title: Text(brl(state.balanceCents)),
            subtitle: const Text('Saldo'),
            trailing: TextButton(
              onPressed: widget.onOpenWallet,
              child: const Text('Carteira'),
            ),
          ),
          TextButton(onPressed: widget.onSignOut, child: const Text('Sair')),
        ],
      ),
    );
  }
}
