import 'package:corrida_core/corrida_core.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:qr_flutter/qr_flutter.dart';

String _titulo(String purpose) => switch (purpose) {
  'ride' => 'Pix da corrida',
  'end' => 'Pix da corrida em dinheiro',
  'fee' => 'Pix da taxa de cancelamento',
  'topup' => 'Pix da recarga',
  'entry' => 'Pix da entrada',
  'debt' => 'Pix da dívida',
  _ => 'Pix a pagar',
};

/// Mostra um Pix a pagar (corrida, taxa, dinheiro do fim ou recarga): o QR para o outro celular ler (a tela do motoqueiro
/// na corrida em dinheiro) e o "copia e cola" com botão para copiar. Quem mandou pagar decide o que acontece depois
/// (`onDone`); a tela em si não sabe se o Pix já foi pago — isso chega por `state`.
class ChargeScreen extends StatelessWidget {
  const ChargeScreen({required this.charge, this.onDone, super.key});

  final Charge charge;
  final VoidCallback? onDone;

  Future<void> _copy(BuildContext context) async {
    await Clipboard.setData(ClipboardData(text: charge.brCode));
    if (!context.mounted) return;
    ScaffoldMessenger.of(context)
      ..hideCurrentSnackBar()
      ..showSnackBar(const SnackBar(content: Text('Código copiado.')));
  }

  @override
  Widget build(BuildContext context) {
    final onDoneAtual = onDone;
    final theme = Theme.of(context);
    final hasCode = charge.brCode.isNotEmpty;
    return Scaffold(
      appBar: AppBar(title: Text(_titulo(charge.purpose ?? ''))),
      body: SingleChildScrollView(
        padding: const EdgeInsets.all(20),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Text(
              brl(charge.amountCents),
              style: theme.textTheme.headlineMedium?.copyWith(fontSize: 40),
              textAlign: TextAlign.center,
            ),
            if (hasCode) ...[
              const SizedBox(height: 20),
              Center(
                child: Container(
                  padding: const EdgeInsets.all(14),
                  decoration: BoxDecoration(
                    color: Colors.white, // o QR precisa de fundo branco para o leitor do banco, até no tema escuro
                    borderRadius: BorderRadius.circular(20),
                  ),
                  child: Semantics(
                    label: 'QR code do Pix',
                    child: QrImageView(
                      data: charge.brCode,
                      size: 220,
                      padding: EdgeInsets.zero,
                      errorCorrectionLevel: QrErrorCorrectLevel.M,
                      backgroundColor: Colors.white,
                    ),
                  ),
                ),
              ),
              const SizedBox(height: 20),
              Text('Pix copia e cola', style: theme.textTheme.titleMedium),
              const SizedBox(height: 8),
              Container(
                padding: const EdgeInsets.all(12),
                decoration: BoxDecoration(
                  color: theme.colorScheme.surfaceContainer,
                  borderRadius: BorderRadius.circular(14),
                ),
                child: SelectableText(
                  charge.brCode,
                  maxLines: 4,
                  style: const TextStyle(fontFamily: 'monospace', fontSize: 13),
                ),
              ),
              const SizedBox(height: 12),
              OutlinedButton.icon(
                onPressed: () => _copy(context),
                icon: const Icon(Icons.copy_rounded),
                label: const Text('Copiar código'),
              ),
            ],
            const SizedBox(height: 16),
            Text(
              'No app do seu banco, leia o QR ou use Pix Copia e Cola.',
              style: TextStyle(color: theme.colorScheme.onSurfaceVariant),
            ),
            const SizedBox(height: 4),
            Text(
              'Depois de pagar, pode fechar esta tela.',
              style: TextStyle(color: theme.colorScheme.onSurfaceVariant),
            ),
          ],
        ),
      ),
      // o "Fechar" fica sempre à vista, embaixo, mesmo com o QR e o código ocupando a tela
      bottomNavigationBar: onDoneAtual == null
          ? null
          : SafeArea(
              child: Padding(
                padding: const EdgeInsets.fromLTRB(20, 8, 20, 12),
                child: ElevatedButton(
                  onPressed: onDoneAtual,
                  child: const Text('Fechar'),
                ),
              ),
            ),
    );
  }
}
