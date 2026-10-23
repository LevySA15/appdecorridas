import 'package:corrida_core/corrida_core.dart';
import 'package:flutter/material.dart';

/// Telefone + código: `onRequestCode`/`onVerify` são o `PassengerController`, sem a tela importar
/// `corrida_core` além do que precisa para mostrar o erro.
class LoginScreen extends StatefulWidget {
  const LoginScreen({
    required this.onRequestCode,
    required this.onVerify,
    super.key,
  });

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

  String _messageOf(Object error) => switch (error) {
    ApiException(message: final message) => message,
    NetworkException(message: final message) => message,
    _ => 'Algo deu errado. Tente de novo.',
  };

  Future<void> _run(Future<void> Function() action) async {
    setState(() => _busy = true);
    try {
      await action();
    } on Exception catch (error) {
      if (!mounted) return;
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(SnackBar(content: Text(_messageOf(error))));
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
    return Scaffold(
      appBar: AppBar(title: const Text('Entrar no app')),
      body: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            TextField(
              key: const Key('telefone'),
              controller: _phoneController,
              enabled: !_showCode,
              keyboardType: TextInputType.phone,
              decoration: const InputDecoration(labelText: 'Telefone'),
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
                decoration: const InputDecoration(labelText: 'Código'),
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
    );
  }
}
