import 'package:corrida_core/corrida_core.dart';
import 'package:corrida_ui/corrida_ui.dart' show friendlyMessage;
import 'package:flutter/material.dart';

import '../name_rules.dart';

/// O perfil: nome (editável), telefone (só leitura), contato de emergência e sair.
class ProfileScreen extends StatefulWidget {
  const ProfileScreen({
    required this.state,
    required this.onSaveName,
    required this.onSetEmergencyContact,
    required this.onSignOut,
    super.key,
  });

  final PassengerState state;
  final Future<void> Function(String name) onSaveName;
  final Future<void> Function(String name, String phone) onSetEmergencyContact;
  final VoidCallback onSignOut;

  @override
  State<ProfileScreen> createState() => _ProfileScreenState();
}

class _ProfileScreenState extends State<ProfileScreen> {
  late final _nameController = TextEditingController(text: widget.state.name);
  late final _contactNameController = TextEditingController(
    text: widget.state.emergencyContact?.name ?? '',
  );
  late final _contactPhoneController = TextEditingController(
    text: widget.state.emergencyContact?.phone ?? '',
  );
  String? _nameProblem;

  @override
  void dispose() {
    _nameController.dispose();
    _contactNameController.dispose();
    _contactPhoneController.dispose();
    super.dispose();
  }

  void _showMessage(String message) {
    if (!mounted) return;
    ScaffoldMessenger.of(context)
        .showSnackBar(SnackBar(content: Text(message)));
  }

  Future<void> _saveName() async {
    final problem = nameError(_nameController.text);
    setState(() => _nameProblem = problem);
    if (problem != null) return;
    try {
      await widget.onSaveName(_nameController.text.trim());
      _showMessage('Nome salvo.');
    } on Exception catch (error) {
      _showMessage(friendlyMessage(error));
    }
  }

  Future<void> _saveContact() async {
    try {
      await widget.onSetEmergencyContact(
        _contactNameController.text,
        _contactPhoneController.text,
      );
    } on Exception catch (error) {
      _showMessage(friendlyMessage(error));
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Perfil')),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          ListTile(
            contentPadding: EdgeInsets.zero,
            title: Text(widget.state.phone, key: const Key('perfil_telefone')),
            subtitle: const Text('Telefone'),
          ),
          TextField(
            key: const Key('perfil_nome'),
            controller: _nameController,
            textCapitalization: TextCapitalization.words,
            decoration: InputDecoration(
              labelText: 'Nome',
              errorText: _nameProblem,
            ),
          ),
          Align(
            alignment: Alignment.centerRight,
            child: FilledButton.tonal(
              onPressed: _saveName,
              child: const Text('Salvar nome'),
            ),
          ),
          const Divider(height: 32),
          Text(
            'Contato de emergência',
            style: Theme.of(context).textTheme.titleMedium,
          ),
          const SizedBox(height: 4),
          Text(
            'Avisamos essa pessoa se você pedir socorro numa corrida.',
            style: TextStyle(
              color: Theme.of(context).colorScheme.onSurfaceVariant,
            ),
          ),
          const SizedBox(height: 12),
          TextField(
            key: const Key('contato_nome'),
            controller: _contactNameController,
            decoration: const InputDecoration(labelText: 'Nome'),
          ),
          const SizedBox(height: 12),
          TextField(
            key: const Key('contato_telefone'),
            controller: _contactPhoneController,
            keyboardType: TextInputType.phone,
            decoration: const InputDecoration(labelText: 'Telefone'),
          ),
          Align(
            alignment: Alignment.centerRight,
            child: FilledButton.tonal(
              onPressed: _saveContact,
              child: const Text('Salvar'),
            ),
          ),
          const Divider(height: 32),
          TextButton(onPressed: widget.onSignOut, child: const Text('Sair')),
        ],
      ),
    );
  }
}
