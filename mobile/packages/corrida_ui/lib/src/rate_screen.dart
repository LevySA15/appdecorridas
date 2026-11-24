import 'package:flutter/material.dart';

import 'messages.dart';
import 'theme.dart';

/// Avaliar de 1 a 5 estrelas. O `ride_id` já saiu de `PassengerState` quando a corrida termina, então
/// quem monta esta tela (`app.dart`) é quem sabe qual corrida é — `onRate` já vem com isso resolvido.
class RateScreen extends StatefulWidget {
  const RateScreen({
    required this.onRate,
    required this.onSkip,
    this.prompt = 'Como foi? Sua nota ajuda a manter a corrida segura.',
    super.key,
  });

  /// Frase embaixo do título (cada app diz quem está sendo avaliado).
  final String prompt;

  final Future<void> Function(int stars) onRate;
  final VoidCallback onSkip;

  @override
  State<RateScreen> createState() => _RateScreenState();
}

class _RateScreenState extends State<RateScreen> {
  var _busy = false;

  Future<void> _rate(int stars) async {
    setState(() => _busy = true);
    try {
      await widget.onRate(stars);
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
    final theme = Theme.of(context);
    return Scaffold(
      appBar: AppBar(title: const Text('Avaliar a corrida')),
      body: Padding(
        padding: const EdgeInsets.all(24),
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Container(
              width: 72,
              height: 72,
              decoration: const BoxDecoration(
                color: corridaAccent,
                shape: BoxShape.circle,
              ),
              child: const Icon(
                Icons.check_rounded,
                color: corridaOnAccent,
                size: 44,
              ),
            ),
            const SizedBox(height: 20),
            Text('Corrida finalizada', style: theme.textTheme.headlineSmall),
            const SizedBox(height: 6),
            Text(
              widget.prompt,
              textAlign: TextAlign.center,
              style: TextStyle(color: theme.colorScheme.onSurfaceVariant),
            ),
            const SizedBox(height: 24),
            if (_busy)
              const CircularProgressIndicator()
            else
              Row(
                mainAxisAlignment: MainAxisAlignment.center,
                children: [
                  for (var n = 1; n <= 5; n++)
                    IconButton(
                      tooltip: n == 1 ? '1 estrela' : '$n estrelas',
                      onPressed: () => _rate(n),
                      iconSize: 44,
                      color: corridaAccent,
                      icon: const Icon(Icons.star),
                    ),
                ],
              ),
            const SizedBox(height: 24),
            TextButton(
              onPressed: _busy ? null : widget.onSkip,
              child: const Text('Agora não'),
            ),
          ],
        ),
      ),
    );
  }
}
