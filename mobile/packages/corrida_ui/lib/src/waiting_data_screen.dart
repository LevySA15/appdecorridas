import 'package:flutter/material.dart';

import 'messages.dart';

/// A tela de quem já tem login mas ainda não conseguiu carregar os dados (abriu o app sem internet, por
/// exemplo). Sem ela o app ficaria num carregando infinito. Quando a internet volta, o tempo real traz os dados
/// sozinho; "Tentar de novo" é para quem não quer esperar.
class WaitingDataScreen extends StatefulWidget {
  const WaitingDataScreen({
    required this.onRetry,
    required this.onSignOut,
    super.key,
  });

  final Future<void> Function() onRetry;
  final VoidCallback onSignOut;

  @override
  State<WaitingDataScreen> createState() => _WaitingDataScreenState();
}

class _WaitingDataScreenState extends State<WaitingDataScreen> {
  var _busy = false;

  Future<void> _retry() async {
    setState(() => _busy = true);
    try {
      await widget.onRetry();
    } on Exception catch (error) {
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(friendlyMessage(error))));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            const Text('Carregando seus dados…', textAlign: TextAlign.center),
            const SizedBox(height: 8),
            const Text(
              'Se demorar, confira a internet.',
              textAlign: TextAlign.center,
            ),
            const SizedBox(height: 24),
            ElevatedButton(
              onPressed: _busy ? null : _retry,
              child: _busy
                  ? const SizedBox(
                      width: 20,
                      height: 20,
                      child: CircularProgressIndicator(strokeWidth: 2),
                    )
                  : const Text('Tentar de novo'),
            ),
            TextButton(onPressed: widget.onSignOut, child: const Text('Sair')),
          ],
        ),
      ),
    );
  }
}
