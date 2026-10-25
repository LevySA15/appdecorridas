import 'package:corrida_core/corrida_core.dart';
import 'package:corrida_ui/corrida_ui.dart';
import 'package:flutter/material.dart';

/// Onde o motoqueiro espera quando o cadastro não está aprovado: em análise ou bloqueado. (O recusado volta
/// ao formulário de cadastro, que ele pode corrigir e reenviar.)
class StatusScreen extends StatelessWidget {
  const StatusScreen({
    required this.registration,
    required this.onRefresh,
    required this.onSignOut,
    this.onRenewDocuments,
    super.key,
  });

  final RiderRegistration registration;
  final Future<void> Function() onRefresh;
  final VoidCallback onSignOut;

  /// Só aparece para a conta bloqueada: o bloqueio por documento vencido só sai com o documento novo.
  final VoidCallback? onRenewDocuments;

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
      RegistrationStatus.blocked => [
        'Conta bloqueada',
        if (reason != null && reason.isNotEmpty) reason,
        if (onRenewDocuments != null) 'Se o bloqueio foi por documento vencido, envie o documento novo, com a foto, e a conta é liberada na hora.',
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
            if (registration.status == RegistrationStatus.blocked &&
                onRenewDocuments != null)
              OutlinedButton(
                onPressed: onRenewDocuments,
                child: const Text('Enviar documento novo'),
              ),
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
