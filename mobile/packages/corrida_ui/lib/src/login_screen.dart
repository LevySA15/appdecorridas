import 'package:flutter/material.dart';

import 'messages.dart';
import 'theme.dart';

/// Telefone + código: `onRequestCode`/`onVerify` são o `PassengerController`, sem a tela importar
/// `corrida_core` além do que precisa para mostrar o erro.
class LoginScreen extends StatefulWidget {
  const LoginScreen({
    required this.onRequestCode,
    required this.onVerify,
    this.title = 'Entrar no app',
    this.subtitle = 'Digite seu celular para receber o código.',
    super.key,
  });

  /// Frase grande no alto da tela (cada app põe a sua voz: "Pra onde vamos?", "Bora rodar?").
  final String title;
  final String subtitle;

  final Future<void> Function(String phone) onRequestCode;
  final Future<void> Function(String phone, String code) onVerify;

  @override
  State<LoginScreen> createState() => _LoginScreenState();
}

class _LoginScreenState extends State<LoginScreen> {
  final _phoneController = TextEditingController();
  final _codeController = TextEditingController();
  var _showCode = false;
  var _busy = false;

  @override
  void dispose() {
    _phoneController.dispose();
    _codeController.dispose();
    super.dispose();
  }

  Future<void> _run(Future<void> Function() action) async {
    setState(() => _busy = true);
    try {
      await action();
    } on Exception catch (error) {
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(friendlyMessage(error))));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _sendCode() => _run(() async {
    await widget.onRequestCode(_phoneController.text);
    if (mounted) setState(() => _showCode = true);
  });

  Future<void> _verify() =>
      _run(() => widget.onVerify(_phoneController.text, _codeController.text));

  void _changeNumber() {
    setState(() {
      _showCode = false;
      _codeController.clear();
    });
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Scaffold(
      body: SafeArea(
        child: Center(
          child: SingleChildScrollView(
            padding: const EdgeInsets.fromLTRB(24, 24, 24, 24),
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 420),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  Align(
                    alignment: Alignment.centerLeft,
                    child: Container(
                      width: 56,
                      height: 56,
                      alignment: Alignment.center,
                      decoration: BoxDecoration(
                        color: corridaAccent,
                        borderRadius: BorderRadius.circular(18),
                      ),
                      child: const Icon(
                        Icons.two_wheeler_rounded,
                        color: corridaOnAccent,
                        size: 32,
                      ),
                    ),
                  ),
                  const SizedBox(height: 28),
                  Text(widget.title, style: theme.textTheme.headlineMedium),
                  const SizedBox(height: 8),
                  Text(
                    _showCode
                        ? 'Mandamos um código para ${_phoneController.text}.'
                        : widget.subtitle,
                    style: theme.textTheme.bodyLarge?.copyWith(
                      color: theme.colorScheme.onSurfaceVariant,
                    ),
                  ),
                  const SizedBox(height: 28),
                  TextField(
                    key: const Key('telefone'),
                    controller: _phoneController,
                    enabled: !_showCode,
                    keyboardType: TextInputType.phone,
                    decoration: const InputDecoration(
                      labelText: 'Telefone',
                      hintText: '(75) 99999-0000',
                    ),
                  ),
                  const SizedBox(height: 16),
                  if (!_showCode)
                    ElevatedButton(
                      onPressed: _busy ? null : _sendCode,
                      child: _busy
                          ? const SizedBox(
                              width: 20,
                              height: 20,
                              child: CircularProgressIndicator(strokeWidth: 2),
                            )
                          : const Text('Enviar código'),
                    ),
                  if (_showCode) ...[
                    TextField(
                      key: const Key('codigo'),
                      controller: _codeController,
                      keyboardType: TextInputType.number,
                      maxLength: 6,
                      decoration: const InputDecoration(
                        labelText: 'Código',
                        counterText: '',
                      ),
                    ),
                    const SizedBox(height: 16),
                    ElevatedButton(
                      onPressed: _busy ? null : _verify,
                      child: _busy
                          ? const SizedBox(
                              width: 20,
                              height: 20,
                              child: CircularProgressIndicator(strokeWidth: 2),
                            )
                          : const Text('Entrar'),
                    ),
                    TextButton(
                      onPressed: _busy ? null : _changeNumber,
                      child: const Text('Trocar número'),
                    ),
                  ],
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}
