import 'package:corrida_core/corrida_core.dart';
import 'package:corrida_ui/corrida_ui.dart';
import 'package:flutter/material.dart';

import '../dates.dart';
import '../photo_source.dart';
import 'document_photo_field.dart';

/// Novas validades da CNH e do documento da moto, com foto nova se a pessoa quiser mandar.
class RenewDocumentsScreen extends StatefulWidget {
  const RenewDocumentsScreen({
    required this.onPickPhoto,
    required this.onSubmit,
    super.key,
  });

  final Future<Photo?> Function(DocKind kind) onPickPhoto;
  final Future<void> Function(
    DateTime cnhExpiresOn,
    DateTime crlvExpiresOn,
    Photo? cnhPhoto,
    Photo? crlvPhoto,
  )
  onSubmit;

  @override
  State<RenewDocumentsScreen> createState() => _RenewDocumentsScreenState();
}

class _RenewDocumentsScreenState extends State<RenewDocumentsScreen> {
  final _cnh = TextEditingController();
  final _crlv = TextEditingController();
  Photo? _cnhPhoto;
  Photo? _crlvPhoto;
  String? _cnhError;
  String? _crlvError;
  var _busy = false;

  @override
  void dispose() {
    _cnh.dispose();
    _crlv.dispose();
    super.dispose();
  }

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
        if (kind == DocKind.cnh) {
          _cnhPhoto = photo;
        } else {
          _crlvPhoto = photo;
        }
      });
    } on Exception catch (error) {
      _showMessage(friendlyMessage(error));
    }
  }

  Future<void> _submit() async {
    final cnhError = dateFieldError(_cnh.text);
    final crlvError = dateFieldError(_crlv.text);
    setState(() {
      _cnhError = cnhError;
      _crlvError = crlvError;
    });
    if (cnhError != null || crlvError != null) return;

    setState(() => _busy = true);
    try {
      await widget.onSubmit(
        parseBrDate(_cnh.text)!,
        parseBrDate(_crlv.text)!,
        _cnhPhoto,
        _crlvPhoto,
      );
    } on Exception catch (error) {
      _showMessage(friendlyMessage(error));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Renovar documentos')),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          TextField(
            key: const Key('validade_cnh'),
            controller: _cnh,
            keyboardType: TextInputType.datetime,
            decoration: InputDecoration(
              labelText: 'Nova validade da CNH',
              hintText: 'dd/mm/aaaa',
              errorText: _cnhError,
            ),
          ),
          const SizedBox(height: 12),
          TextField(
            key: const Key('validade_crlv'),
            controller: _crlv,
            keyboardType: TextInputType.datetime,
            decoration: InputDecoration(
              labelText: 'Nova validade do documento da moto',
              hintText: 'dd/mm/aaaa',
              errorText: _crlvError,
            ),
          ),
          DocumentPhotoField(
            key: const Key('foto_cnh'),
            label: 'Foto nova da CNH (opcional)',
            photo: _cnhPhoto,
            onPick: () => _pick(DocKind.cnh),
          ),
          DocumentPhotoField(
            key: const Key('foto_crlv'),
            label: 'Foto nova do documento da moto (opcional)',
            photo: _crlvPhoto,
            onPick: () => _pick(DocKind.crlv),
          ),
          const SizedBox(height: 16),
          ElevatedButton(
            onPressed: _busy ? null : _submit,
            child: _busy
                ? const SizedBox(
                    width: 20,
                    height: 20,
                    child: CircularProgressIndicator(strokeWidth: 2),
                  )
                : const Text('Enviar'),
          ),
        ],
      ),
    );
  }
}
