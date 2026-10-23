import 'package:corrida_core/corrida_core.dart';
import 'package:flutter/material.dart';

/// Saldo, recarga, saque, contato de emergência e as taxas de cancelamento recentes (com recurso).
class WalletScreen extends StatefulWidget {
  const WalletScreen({
    required this.state,
    required this.onTopup,
    required this.onWithdraw,
    required this.onSetEmergencyContact,
    required this.onAppealFee,
    required this.onShowCharge,
    super.key,
  });

  final PassengerState state;
  final Future<Charge> Function(int amountCents) onTopup;
  final Future<Withdrawal> Function(int amountCents, String pixKey) onWithdraw;
  final Future<void> Function(String name, String phone) onSetEmergencyContact;
  final Future<void> Function(String rideId, String text) onAppealFee;
  final void Function(Charge) onShowCharge;

  @override
  State<WalletScreen> createState() => _WalletScreenState();
}

class _WalletScreenState extends State<WalletScreen> {
  late final _nameController = TextEditingController(
    text: widget.state.emergencyContact?.name ?? '',
  );
  late final _phoneController = TextEditingController(
    text: widget.state.emergencyContact?.phone ?? '',
  );

  @override
  void dispose() {
    _nameController.dispose();
    _phoneController.dispose();
    super.dispose();
  }

  String _messageOf(Object error) => switch (error) {
    ApiException(message: final message) => message,
    NetworkException(message: final message) => message,
    _ => 'Algo deu errado. Tente de novo.',
  };

  void _showMessage(String message) {
    if (!mounted) return;
    ScaffoldMessenger.of(
      context,
    ).showSnackBar(SnackBar(content: Text(message)));
  }

  int _centsFromReais(String text) =>
      ((double.tryParse(text.replaceAll(',', '.')) ?? 0) * 100).round();

  Future<void> _topup() async {
    final controller = TextEditingController();
    final confirmado = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Recarregar'),
        content: TextField(
          key: const Key('valor_recarga'),
          controller: controller,
          keyboardType: TextInputType.number,
          decoration: const InputDecoration(labelText: 'Valor (R\$)'),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(context).pop(true),
            child: const Text('Confirmar'),
          ),
        ],
      ),
    );
    if (confirmado != true) return;
    try {
      final charge = await widget.onTopup(_centsFromReais(controller.text));
      widget.onShowCharge(charge);
    } on Exception catch (error) {
      _showMessage(_messageOf(error));
    }
  }

  Future<void> _withdraw() async {
    final amountController = TextEditingController();
    final keyController = TextEditingController();
    while (true) {
      final confirmado = await showDialog<bool>(
        context: context,
        builder: (context) => AlertDialog(
          title: const Text('Sacar'),
          content: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              TextField(
                key: const Key('valor_saque'),
                controller: amountController,
                keyboardType: TextInputType.number,
                decoration: const InputDecoration(labelText: 'Valor (R\$)'),
              ),
              TextField(
                key: const Key('chave_pix'),
                controller: keyController,
                decoration: const InputDecoration(labelText: 'Chave Pix'),
              ),
            ],
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.of(context).pop(true),
              child: const Text('Confirmar'),
            ),
          ],
        ),
      );
      if (confirmado != true) return;
      try {
        final result = await widget.onWithdraw(
          _centsFromReais(amountController.text),
          keyController.text,
        );
        _showMessage('Saque feito: ${brl(result.amountCents)} para ${result.key}.');
        return;
      } on Exception catch (error) {
        _showMessage(_messageOf(error));
      }
    }
  }

  Future<void> _saveEmergencyContact() async {
    try {
      await widget.onSetEmergencyContact(
        _nameController.text,
        _phoneController.text,
      );
    } on Exception catch (error) {
      _showMessage(_messageOf(error));
    }
  }

  Future<void> _appealFee(RecentFee fee) async {
    final textController = TextEditingController();
    final confirmado = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Pedir recurso'),
        content: TextField(
          key: const Key('texto_recurso'),
          controller: textController,
          maxLines: 3,
          decoration: const InputDecoration(labelText: 'Por que você discorda'),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(context).pop(true),
            child: const Text('Enviar'),
          ),
        ],
      ),
    );
    if (confirmado != true) return;
    try {
      await widget.onAppealFee(fee.rideId, textController.text);
    } on Exception catch (error) {
      _showMessage(_messageOf(error));
    }
  }

  @override
  Widget build(BuildContext context) {
    final state = widget.state;
    return Scaffold(
      appBar: AppBar(title: const Text('Carteira')),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          Text(
            brl(state.balanceCents),
            style: Theme.of(context).textTheme.headlineMedium,
          ),
          const SizedBox(height: 16),
          Row(
            children: [
              if (state.topupEnabled)
                ElevatedButton(
                  onPressed: _topup,
                  child: const Text('Recarregar'),
                ),
              if (state.topupEnabled && state.withdrawEnabled)
                const SizedBox(width: 8),
              if (state.withdrawEnabled)
                ElevatedButton(onPressed: _withdraw, child: const Text('Sacar')),
            ],
          ),
          const Divider(height: 32),
          const Text('Contato de emergência'),
          TextField(
            key: const Key('contato_nome'),
            controller: _nameController,
            decoration: const InputDecoration(labelText: 'Nome'),
          ),
          TextField(
            key: const Key('contato_telefone'),
            controller: _phoneController,
            decoration: const InputDecoration(labelText: 'Telefone'),
          ),
          Align(
            alignment: Alignment.centerRight,
            child: TextButton(
              onPressed: _saveEmergencyContact,
              child: const Text('Salvar'),
            ),
          ),
          if (state.recentFees.isNotEmpty) ...[
            const Divider(height: 32),
            const Text('Taxas de cancelamento recentes'),
            for (final fee in state.recentFees)
              ListTile(
                title: Text(brl(fee.feeCents)),
                subtitle: Text(fee.appealState),
                trailing: fee.canAppeal
                    ? TextButton(
                        onPressed: () => _appealFee(fee),
                        child: const Text('Pedir recurso'),
                      )
                    : null,
              ),
          ],
        ],
      ),
    );
  }
}
