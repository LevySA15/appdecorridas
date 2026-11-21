import 'package:corrida_ui/corrida_ui.dart' show friendlyMessage;
import 'package:flutter/material.dart';

import '../name_rules.dart';

/// Porta de entrada de quem ainda não disse o nome: o motoqueiro e a central precisam saber quem é o
/// passageiro. Só depois de salvar a pessoa chega à tela inicial.
class NameScreen extends StatefulWidget {
  const NameScreen({required this.onSave, required this.onSignOut, super.key});

  final Future<void> Function(String name) onSave;
  final VoidCallback onSignOut;

  @override
  State<NameScreen> createState() => _NameScreenState();
}

class _NameScreenState extends State<NameScreen> {
  final _controller = TextEditingController();
  String? _error;
  var _saving = false;

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  Future<void> _save() async {
    final problem = nameError(_controller.text);
    if (problem != null) {
      setState(() => _error = problem);
      return;
    }
    setState(() {
      _error = null;
      _saving = true;
    });
    try {
      await widget.onSave(_controller.text.trim());
    } on Exception catch (error) {
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(friendlyMessage(error))));
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: SafeArea(
        child: ListView(
          padding: const EdgeInsets.all(24),
          children: [
            const SizedBox(height: 48),
            Text(
              'Como podemos te chamar?',
              style: Theme.of(context).textTheme.headlineSmall,
            ),
            const SizedBox(height: 8),
            const Text('É o nome que o motoqueiro vê quando vai te buscar.'),
            const SizedBox(height: 24),
            TextField(
              key: const Key('nome'),
              controller: _controller,
              textCapitalization: TextCapitalization.words,
              textInputAction: TextInputAction.done,
              onSubmitted: (_) => _saving ? null : _save(),
              decoration: InputDecoration(
                labelText: 'Seu nome',
                errorText: _error,
              ),
            ),
            const SizedBox(height: 24),
            FilledButton(
              onPressed: _saving ? null : _save,
              child: _saving
                  ? const SizedBox(
                      width: 16,
                      height: 16,
                      child: CircularProgressIndicator(strokeWidth: 2),
                    )
                  : const Text('Continuar'),
            ),
            const SizedBox(height: 8),
            TextButton(onPressed: widget.onSignOut, child: const Text('Sair')),
          ],
        ),
      ),
    );
  }
}
