import 'package:corrida_core/corrida_core.dart';
import 'package:flutter/material.dart';

/// Avaliar de 1 a 5 estrelas. O `ride_id` já saiu de `PassengerState` quando a corrida termina, então
/// quem monta esta tela (`app.dart`) é quem sabe qual corrida é — `onRate` já vem com isso resolvido.
class RateScreen extends StatefulWidget {
  const RateScreen({required this.onRate, required this.onSkip, super.key});

  final Future<void> Function(int stars) onRate;
  final VoidCallback onSkip;

  @override
  State<RateScreen> createState() => _RateScreenState();
}

class _RateScreenState extends State<RateScreen> {
  var _busy = false;

  String _messageOf(Object error) => switch (error) {
    ApiException(message: final message) => message,
    NetworkException(message: final message) => message,
    _ => 'Algo deu errado. Tente de novo.',
  };

  Future<void> _rate(int stars) async {
    setState(() => _busy = true);
    try {
      await widget.onRate(stars);
    } on Exception catch (error) {
      if (!mounted) return;
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(SnackBar(content: Text(_messageOf(error))));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Avaliar a corrida')),
      body: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            if (_busy)
              const CircularProgressIndicator()
            else
              Row(
                mainAxisAlignment: MainAxisAlignment.center,
                children: [
                  for (var n = 1; n <= 5; n++)
                    IconButton(
                      onPressed: () => _rate(n),
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
