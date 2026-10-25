import 'package:flutter/material.dart';

import '../photo_source.dart';

/// Uma foto do cadastro: o nome do documento, o botão de tirar (ou trocar) e, se faltar, o aviso.
class DocumentPhotoField extends StatelessWidget {
  const DocumentPhotoField({
    required this.label,
    required this.photo,
    required this.onPick,
    this.errorText,
    super.key,
  });

  final String label;
  final Photo? photo;
  final VoidCallback onPick;
  final String? errorText;

  @override
  Widget build(BuildContext context) {
    final taken = photo != null;
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 8),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(label, style: Theme.of(context).textTheme.titleSmall),
          const SizedBox(height: 4),
          OutlinedButton(
            onPressed: onPick,
            child: Text(taken ? 'Foto tirada — trocar' : 'Tirar foto'),
          ),
          if (errorText != null)
            Padding(
              padding: const EdgeInsets.only(top: 4),
              child: Text(
                errorText!,
                style: TextStyle(color: Theme.of(context).colorScheme.error),
              ),
            ),
        ],
      ),
    );
  }
}
