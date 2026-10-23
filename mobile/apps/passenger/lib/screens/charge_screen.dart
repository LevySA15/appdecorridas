import 'package:corrida_core/corrida_core.dart';
import 'package:flutter/material.dart';

String _titulo(String purpose) => switch (purpose) {
  'ride' => 'Pix da corrida',
  'end' => 'Pix da corrida em dinheiro',
  'fee' => 'Pix da taxa de cancelamento',
  'topup' => 'Pix da recarga',
  _ => 'Pix a pagar',
};

/// Mostra um Pix a pagar (corrida, taxa, dinheiro do fim ou recarga). Quem mandou pagar decide o que
/// acontece depois (`onDone`); a tela em si não sabe se o Pix já foi pago — isso chega por `state`.
class ChargeScreen extends StatelessWidget {
  const ChargeScreen({required this.charge, this.onDone, super.key});

  final Charge charge;
  final VoidCallback? onDone;

  @override
  Widget build(BuildContext context) {
    final onDoneAtual = onDone;
    return Scaffold(
      appBar: AppBar(title: Text(_titulo(charge.purpose ?? ''))),
      body: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Text(
              brl(charge.amountCents),
              style: Theme.of(context).textTheme.headlineMedium,
              textAlign: TextAlign.center,
            ),
            const SizedBox(height: 24),
            const Text('Pix copia e cola'),
            const SizedBox(height: 8),
            Container(
              padding: const EdgeInsets.all(12),
              decoration: BoxDecoration(
                border: Border.all(color: Theme.of(context).dividerColor),
                borderRadius: BorderRadius.circular(8),
              ),
              child: SelectableText(charge.brCode),
            ),
            const SizedBox(height: 16),
            const Text('Depois de pagar, a tela atualiza sozinha.'),
            if (onDoneAtual != null) ...[
              const SizedBox(height: 24),
              ElevatedButton(onPressed: onDoneAtual, child: const Text('Fechar')),
            ],
          ],
        ),
      ),
    );
  }
}
