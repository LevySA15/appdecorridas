import 'package:corrida_core/corrida_core.dart';
import 'package:corrida_ui/corrida_ui.dart';
import 'package:flutter/material.dart';

import '../dates.dart';
import '../photo_source.dart';
import '../registration_data.dart';
import 'document_photo_field.dart';

/// O formulário de cadastro do motoqueiro: dados, validades e as três fotos. Os erros do servidor
/// (CPF repetido, CNH vencida...) aparecem numa `SnackBar` e o formulário fica como estava.
class RegistrationScreen extends StatefulWidget {
  const RegistrationScreen({
    required this.onPickPhoto,
    required this.onSubmit,
    required this.onSignOut,
    super.key,
  });

  final Future<Photo?> Function(DocKind kind) onPickPhoto;
  final Future<void> Function(RegistrationData data) onSubmit;
  final VoidCallback onSignOut;

  @override
  State<RegistrationScreen> createState() => _RegistrationScreenState();
}

class _RegistrationScreenState extends State<RegistrationScreen> {
  static const _textKeys = ['nome', 'cpf', 'cnh', 'placa', 'modelo'];
  static const _dateKeys = ['validade_cnh', 'validade_crlv'];

  final _controllers = {
    for (final key in [..._textKeys, ..._dateKeys])
      key: TextEditingController(),
  };
  final _photos = <DocKind, Photo>{};
  final _errors = <String, String>{};
  final _photoErrors = <DocKind>{};
  var _busy = false;

  @override
  void dispose() {
    for (final controller in _controllers.values) {
      controller.dispose();
    }
    super.dispose();
  }

  String _text(String key) => _controllers[key]!.text.trim();

  void _showMessage(String message) {
    if (!mounted) return;
    ScaffoldMessenger.of(context)
        .showSnackBar(SnackBar(content: Text(message)));
  }

  Future<void> _pick(DocKind kind) async {
    try {
      final photo = await widget.onPickPhoto(kind);
      if (photo == null || !mounted) return;
      setState(() {
        _photos[kind] = photo;
        _photoErrors.remove(kind);
      });
    } on Exception catch (error) {
      _showMessage(friendlyMessage(error));
    }
  }

  Future<void> _submit() async {
    final errors = <String, String>{};
    for (final key in _textKeys) {
      if (_text(key).isEmpty) errors[key] = 'Preencha este campo';
    }
    for (final key in _dateKeys) {
      final error = dateFieldError(_text(key));
      if (error != null) errors[key] = error;
    }
    final missing = {
      for (final kind in DocKind.values)
        if (!_photos.containsKey(kind)) kind,
    };
    setState(() {
      _errors
        ..clear()
        ..addAll(errors);
      _photoErrors
        ..clear()
        ..addAll(missing);
    });
    if (errors.isNotEmpty || missing.isNotEmpty) return;

    setState(() => _busy = true);
    try {
      await widget.onSubmit(
        RegistrationData(
          name: _text('nome'),
          cpf: _text('cpf'),
          cnhNumber: _text('cnh'),
          plate: _text('placa'),
          motoModel: _text('modelo'),
          cnhExpiresOn: parseBrDate(_text('validade_cnh'))!,
          crlvExpiresOn: parseBrDate(_text('validade_crlv'))!,
          photos: Map.of(_photos),
        ),
      );
    } on Exception catch (error) {
      _showMessage(friendlyMessage(error));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Widget _field(
    String key,
    String label, {
    TextInputType? keyboard,
    String? hint,
  }) => Padding(
    padding: const EdgeInsets.only(bottom: 12),
    child: TextField(
      key: Key(key),
      controller: _controllers[key],
      keyboardType: keyboard,
      decoration: InputDecoration(
        labelText: label,
        hintText: hint,
        errorText: _errors[key],
      ),
    ),
  );

  Widget _photoField(DocKind kind, String label) => DocumentPhotoField(
    key: Key('foto_${kind.name}'),
    label: label,
    photo: _photos[kind],
    errorText: _photoErrors.contains(kind) ? 'Falta a foto' : null,
    onPick: () => _pick(kind),
  );

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Seu cadastro')),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          const Text('Preencha seus dados para pedir a aprovação.'),
          const SizedBox(height: 16),
          _field('nome', 'Nome completo'),
          _field('cpf', 'CPF', keyboard: TextInputType.number),
          _field('cnh', 'Número da CNH', keyboard: TextInputType.number),
          _field('placa', 'Placa da moto'),
          _field('modelo', 'Modelo da moto'),
          _field(
            'validade_cnh',
            'Validade da CNH',
            keyboard: TextInputType.datetime,
            hint: 'dd/mm/aaaa',
          ),
          _field(
            'validade_crlv',
            'Validade do documento da moto',
            keyboard: TextInputType.datetime,
            hint: 'dd/mm/aaaa',
          ),
          _photoField(DocKind.selfie, 'Selfie'),
          _photoField(DocKind.cnh, 'CNH'),
          _photoField(DocKind.crlv, 'Documento da moto'),
          const SizedBox(height: 16),
          ElevatedButton(
            onPressed: _busy ? null : _submit,
            child: _busy
                ? const SizedBox(
                    width: 20,
                    height: 20,
                    child: CircularProgressIndicator(strokeWidth: 2),
                  )
                : const Text('Enviar cadastro'),
          ),
          TextButton(onPressed: widget.onSignOut, child: const Text('Sair')),
        ],
      ),
    );
  }
}
