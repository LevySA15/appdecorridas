import 'package:corrida_core/corrida_core.dart';
import 'package:corrida_ui/corrida_ui.dart';
import 'package:flutter/material.dart';

import '../format.dart';

String _statusText(RideState state) => switch (state) {
  RideState.searching => 'Procurando moto...',
  RideState.queued => 'Na fila...',
  RideState.accepted => 'A moto está a caminho',
  RideState.arrived => 'Sua moto chegou',
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
        'Avisamos a central. Se estiver em perigo, ligue ${result.emergencyNumber}. '
        '${result.contactNotified ? 'Seu contato de emergência foi avisado.' : 'Cadastre um contato de emergência no Perfil para avisarmos alguém.'}',
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
    final theme = Theme.of(context);
    final riderPosition = ride.riderPosition;
    final showPin =
        rider != null &&
        ride.pin.isNotEmpty &&
        (ride.state == RideState.accepted || ride.state == RideState.arrived);
    return Scaffold(
      appBar: AppBar(
        title: const Text('Sua corrida'),
        // sempre à vista: numa emergência ninguém vai rolar a tela atrás do botão
        actions: [
          // vermelho cheio e com folga da borda: é o botão que ninguém pode errar de achar
          FilledButton(
            onPressed: _sos,
            style: FilledButton.styleFrom(
              padding: const EdgeInsets.symmetric(horizontal: 18, vertical: 8),
              minimumSize: const Size(0, 36),
            ),
            child: const Text('SOS'),
          ),
          const SizedBox(width: 12),
        ],
      ),
      body: Stack(
        children: [
          Positioned.fill(
            child: CorridaMapView(
              bottomSpace: 380,
              route: ride.route,
              markers: [
                MapMarker(MarkerKind.pickup, ride.pickup),
                MapMarker(MarkerKind.destination, ride.destination),
                if (riderPosition != null)
                  MapMarker(
                    MarkerKind.me,
                    Place(lat: riderPosition.lat, lng: riderPosition.lng),
                  ),
              ],
            ),
          ),
          Align(
            alignment: Alignment.bottomCenter,
            child: ConstrainedBox(
              constraints: BoxConstraints(
                maxHeight: MediaQuery.sizeOf(context).height * 0.7,
              ),
              child: SheetCard(
                child: SingleChildScrollView(
                  child: Column(
                    mainAxisSize: MainAxisSize.min,
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: [
                      Text(
                        _statusText(ride.state),
                        style: theme.textTheme.headlineSmall,
                      ),
                      if (rider != null) ...[
                        const SizedBox(height: 16),
                        Row(
                          children: [
                            InitialsAvatar(name: rider.name),
                            const SizedBox(width: 12),
                            Expanded(
                              child: Column(
                                crossAxisAlignment: CrossAxisAlignment.start,
                                children: [
                                  Text(
                                    rider.name,
                                    style: theme.textTheme.titleMedium,
                                  ),
                                  Text(
                                    '${rider.plate} — ${rider.motoModel}',
                                    style: TextStyle(
                                      color: theme.colorScheme.onSurfaceVariant,
                                    ),
                                  ),
                                ],
                              ),
                            ),
                            if (rider.rating != null)
                              InfoPill(
                                icon: Icons.star_rounded,
                                text: rider.rating!
                                    .toStringAsFixed(1)
                                    .replaceAll('.', ','),
                              ),
                          ],
                        ),
                      ],
                      if (showPin) ...[
                        const SizedBox(height: 16),
                        Text(
                          'Diga este código ao motoqueiro',
                          style: TextStyle(
                            color: theme.colorScheme.onSurfaceVariant,
                          ),
                        ),
                        const SizedBox(height: 8),
                        Align(
                          alignment: Alignment.centerLeft,
                          child: PinDigits(pin: ride.pin),
                        ),
                      ],
                      const SizedBox(height: 16),
                      Wrap(
                        spacing: 8,
                        runSpacing: 8,
                        children: [
                          InfoPill(
                            icon: Icons.payments_outlined,
                            text: brl(ride.priceCents),
                          ),
                          InfoPill(
                            icon: Icons.route_outlined,
                            text: formatKm(ride.distanceM),
                          ),
                          if (ride.method.isNotEmpty)
                            InfoPill(
                              icon: Icons.credit_card_outlined,
                              text: ride.payWithBalance
                                  ? 'Saldo do app'
                                  : (ride.method == 'cash'
                                        ? 'Dinheiro'
                                        : 'Pix'),
                            ),
                        ],
                      ),
                      if (ride.pay != null) ...[
                        const SizedBox(height: 16),
                        ElevatedButton(
                          onPressed: () => _showCharge(ride.pay!.chargeId),
                          child: const Text('Ver Pix'),
                        ),
                      ],
                      // sem QR ainda (o motoqueiro não pediu) não há o que mostrar
                      if (endPayment != null &&
                          endPayment.chargeId != null) ...[
                        const SizedBox(height: 16),
                        ElevatedButton(
                          onPressed: () => _showCharge(endPayment.chargeId!),
                          child: const Text('Ver Pix'),
                        ),
                      ],
                      // durante a viagem não há o que cancelar: quem precisa de ajuda usa o SOS
                      if (ride.state != RideState.inProgress) ...[
                        const SizedBox(height: 16),
                        OutlinedButton(
                          onPressed: _cancel,
                          child: const Text('Cancelar'),
                        ),
                      ],
                    ],
                  ),
                ),
              ),
            ),
          ),
        ],
      ),
    );
  }
}
