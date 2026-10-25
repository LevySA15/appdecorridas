import 'package:corrida_core/corrida_core.dart';
import 'package:corrida_ui/corrida_ui.dart';
import 'package:flutter/material.dart';

/// Onde o motoqueiro espera quando o cadastro não está aprovado: em análise, recusado ou bloqueado.
class StatusScreen extends StatelessWidget {
  const StatusScreen({
    required this.registration,
    required this.onRefresh,
    required this.onSignOut,
    super.key,
  });

  final RiderRegistration registration;
  final Future<void> Function() onRefresh;
  final VoidCallback onSignOut;

  Future<void> _refresh(BuildContext context) async {
    try {
      await onRefresh();
    } on Exception catch (error) {
      if (!context.mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(friendlyMessage(error))));
    }
  }

  @override
  Widget build(BuildContext context) {
    final reason = registration.reason;
    final lines = switch (registration.status) {
      RegistrationStatus.pending => [
        'Cadastro em análise. Avisamos aqui quando for aprovado.',
      ],
      RegistrationStatus.rejected => [
        'Cadastro recusado',
        if (reason != null && reason.isNotEmpty) reason,
        'Fale com o suporte.',
      ],
      RegistrationStatus.blocked => [
        'Conta bloqueada',
        if (reason != null && reason.isNotEmpty) reason,
      ],
      _ => ['Não conseguimos ler o seu cadastro. Toque em atualizar.'],
    };
    return Scaffold(
      appBar: AppBar(title: const Text('Seu cadastro')),
      body: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            for (final line in lines)
              Padding(
                padding: const EdgeInsets.only(bottom: 8),
                child: Text(line, textAlign: TextAlign.center),
              ),
            const SizedBox(height: 16),
            ElevatedButton(
              onPressed: () => _refresh(context),
              child: const Text('Atualizar'),
            ),
            TextButton(onPressed: onSignOut, child: const Text('Sair')),
          ],
        ),
      ),
    );
  }
}
