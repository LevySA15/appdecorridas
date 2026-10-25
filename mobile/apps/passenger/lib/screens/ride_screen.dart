import 'package:corrida_core/corrida_core.dart';
import 'package:flutter/material.dart';

String _statusText(RideState state) => switch (state) {
  RideState.searching => 'Procurando moto...',
  RideState.queued => 'Na fila...',
  RideState.accepted || RideState.arrived => 'A moto está a caminho',
  RideState.inProgress => 'Em viagem',
  _ => '',
};

/// Acompanhar a corrida: estado, motoqueiro, PIN, Pix a pagar, cancelar, SOS e o alerta de segurança.
class RideScreen extends StatefulWidget {
  const RideScreen({
    required this.ride,
    required this.onLoadCharge,
    required this.onShowCharge,
    required this.onCancel,
    required this.onSos,
    required this.onSafetyOk,
    super.key,
  });

  final PassengerRide ride;
  final Future<Charge> Function(String chargeId) onLoadCharge;
  final void Function(Charge) onShowCharge;
  final Future<CancelResult> Function() onCancel;
  final Future<SosResult> Function() onSos;
  final Future<void> Function(int alertId) onSafetyOk;

  @override
  State<RideScreen> createState() => _RideScreenState();
}

class _RideScreenState extends State<RideScreen> {
  int? _safetyDialogShownFor;

  String _messageOf(Object error) => switch (error) {
    ApiException(message: final message) => message,
    NetworkException(message: final message) => message,
    _ => 'Algo deu errado. Tente de novo.',
  };

  void _showMessage(String message) {
    if (!mounted) return;
    ScaffoldMessenger.of(context)
        .showSnackBar(SnackBar(content: Text(message)));
  }

  Future<void> _showCharge(String chargeId) async {
    try {
      final charge = await widget.onLoadCharge(chargeId);
      widget.onShowCharge(charge);
    } on Exception catch (error) {
      _showMessage(_messageOf(error));
    }
  }

  Future<void> _cancel() async {
    try {
      final result = await widget.onCancel();
      final message = result.feeCents > 0
          ? 'Cancelado com taxa de ${brl(result.feeCents)}.'
          : 'Cancelado sem taxa.';
      _showMessage(message);
    } on Exception catch (error) {
      _showMessage(_messageOf(error));
    }
  }

  Future<void> _sos() async {
    try {
      final result = await widget.onSos();
      _showMessage(
        'Emergência: ${result.emergencyNumber}. '
        '${result.contactNotified ? 'Contato avisado.' : 'Contato não avisado.'}',
      );
    } on Exception catch (error) {
      _showMessage(_messageOf(error));
    }
  }

  Future<void> _showSafetyDialogIfNeeded() async {
    final alert = widget.ride.safetyAlert;
    if (alert == null) {
      _safetyDialogShownFor = null;
      return;
    }
    if (_safetyDialogShownFor == alert.alertId) return;
    _safetyDialogShownFor = alert.alertId;
    await showDialog<void>(
      context: context,
      barrierDismissible: false,
      builder: (context) => AlertDialog(
        title: const Text('Está tudo bem?'),
        actions: [
          TextButton(
            onPressed: () async {
              Navigator.of(context).pop();
              await widget.onSafetyOk(alert.alertId);
            },
            child: const Text('Sim'),
          ),
        ],
      ),
    );
  }

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback(
      (_) => _showSafetyDialogIfNeeded(),
    );
  }

  @override
  void didUpdateWidget(RideScreen oldWidget) {
    super.didUpdateWidget(oldWidget);
    WidgetsBinding.instance.addPostFrameCallback(
      (_) => _showSafetyDialogIfNeeded(),
    );
  }

  @override
  Widget build(BuildContext context) {
    final ride = widget.ride;
    final rider = ride.rider;
    final endPayment = ride.endPayment;
    return Scaffold(
      appBar: AppBar(title: const Text('Sua corrida')),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          Text(
            _statusText(ride.state),
            style: Theme.of(context).textTheme.headlineSmall,
          ),
          if (rider != null) ...[
            const SizedBox(height: 16),
            Text('PIN: ${ride.pin}'),
            Text(rider.name),
            Text('${rider.plate} — ${rider.motoModel}'),
          ],
          if (ride.pay != null) ...[
            const SizedBox(height: 16),
            ElevatedButton(
              onPressed: () => _showCharge(ride.pay!.chargeId),
              child: const Text('Ver Pix'),
            ),
          ],
          // sem QR ainda (o motoqueiro não pediu) não há o que mostrar
          if (endPayment != null && endPayment.chargeId != null) ...[
            const SizedBox(height: 16),
            ElevatedButton(
              onPressed: () => _showCharge(endPayment.chargeId!),
              child: const Text('Ver Pix'),
            ),
          ],
          const SizedBox(height: 24),
          OutlinedButton(onPressed: _cancel, child: const Text('Cancelar')),
          const SizedBox(height: 8),
          OutlinedButton(onPressed: _sos, child: const Text('SOS')),
        ],
      ),
    );
  }
}
