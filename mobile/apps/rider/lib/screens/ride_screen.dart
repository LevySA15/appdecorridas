import 'package:corrida_core/corrida_core.dart';
import 'package:corrida_ui/corrida_ui.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import 'offer_card.dart';

/// A corrida do ponto de vista do motoqueiro: buscar → cheguei → capacete e código → levar → finalizar.
/// Enquanto não há GPS, o mapa de mentira é tocável (e há atalhos) para "andar" até o embarque e o destino.
class RideScreen extends StatefulWidget {
  const RideScreen({
    required this.ride,
    required this.position,
    required this.onMove,
    required this.onArrive,
    required this.onConfirmHelmet,
    required this.onStart,
    required this.onComplete,
    required this.onAcceptOffer,
    required this.onDeclineOffer,
    this.offer,
    super.key,
  });

  final RiderRide ride;
  final Place position;
  final void Function(Place) onMove;
  final Future<void> Function() onArrive;
  final Future<void> Function() onConfirmHelmet;
  final Future<void> Function(String pin) onStart;
  final Future<void> Function() onComplete;

  /// Oferta que chegou durante a corrida (vai para a fila).
  final Offer? offer;
  final Future<void> Function(String rideId) onAcceptOffer;
  final Future<void> Function(String rideId) onDeclineOffer;

  @override
  State<RideScreen> createState() => _RideScreenState();
}

class _RideScreenState extends State<RideScreen> {
  final _pin = TextEditingController();
  var _busy = false;

  @override
  void dispose() {
    _pin.dispose();
    super.dispose();
  }

  Future<void> _run(Future<void> Function() action) async {
    setState(() => _busy = true);
    try {
      await action();
    } on ApiException catch (error) {
      if (error.code == 'wrong_pin') _pin.clear();
      _showMessage(friendlyMessage(error));
    } on Exception catch (error) {
      _showMessage(friendlyMessage(error));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  void _showMessage(String message) {
    if (!mounted) return;
    ScaffoldMessenger.of(context)
        .showSnackBar(SnackBar(content: Text(message)));
  }

  Widget _map(RiderRide ride) => SizedBox(
    height: 240,
    child: FakeMapView(
      markers: [
        MapMarker(MarkerKind.pickup, ride.pickup),
        MapMarker(MarkerKind.destination, ride.destination),
        MapMarker(MarkerKind.me, widget.position),
      ],
      onTap: widget.onMove,
    ),
  );

  List<Widget> _accepted(RiderRide ride) => [
    Text(
      ride.passengerName.isEmpty
          ? 'Vá buscar o passageiro'
          : 'Vá buscar ${ride.passengerName}',
      style: Theme.of(context).textTheme.titleLarge,
    ),
    if (ride.pickup.text.isNotEmpty) Text('Embarque: ${ride.pickup.text}'),
    const SizedBox(height: 8),
    _map(ride),
    OutlinedButton(
      onPressed: () => widget.onMove(ride.pickup),
      child: const Text('Ir até o ponto de embarque'),
    ),
    ElevatedButton(
      onPressed: _busy ? null : () => _run(widget.onArrive),
      child: const Text('Cheguei'),
    ),
  ];

  List<Widget> _arrived(RiderRide ride) {
    final waitingPix = ride.method != 'cash' && !ride.pixPaid;
    final canStart =
        ride.helmetConfirmed && !waitingPix && _pin.text.length == 4 && !_busy;
    return [
      Text(
        'Peça o código de 4 dígitos ao passageiro',
        style: Theme.of(context).textTheme.titleLarge,
      ),
      const SizedBox(height: 8),
      ElevatedButton(
        onPressed: ride.helmetConfirmed || _busy
            ? null
            : () => _run(widget.onConfirmHelmet),
        child: Text(
          ride.helmetConfirmed
              ? 'Capacete confirmado'
              : 'Confirmei o capacete extra',
        ),
      ),
      if (waitingPix) const Text('Aguardando o Pix do passageiro…'),
      TextField(
        key: const Key('codigo'),
        controller: _pin,
        keyboardType: TextInputType.number,
        inputFormatters: [
          FilteringTextInputFormatter.digitsOnly,
          LengthLimitingTextInputFormatter(4),
        ],
        onChanged: (_) => setState(() {}),
        decoration: const InputDecoration(
          labelText: 'Código do passageiro',
          counterText: '',
        ),
      ),
      ElevatedButton(
        onPressed: canStart
            ? () => _run(() => widget.onStart(_pin.text))
            : null,
        child: const Text('Começar corrida'),
      ),
    ];
  }

  List<Widget> _inProgress(RiderRide ride) => [
    Text(
      ride.passengerName.isEmpty
          ? 'Levando o passageiro'
          : 'Levando ${ride.passengerName}',
      style: Theme.of(context).textTheme.titleLarge,
    ),
    if (ride.destination.text.isNotEmpty)
      Text('Destino: ${ride.destination.text}'),
    const SizedBox(height: 8),
    _map(ride),
    OutlinedButton(
      onPressed: () => widget.onMove(ride.destination),
      child: const Text('Ir até o destino'),
    ),
    ElevatedButton(
      onPressed: _busy ? null : () => _run(widget.onComplete),
      child: const Text('Finalizar corrida'),
    ),
  ];

  @override
  Widget build(BuildContext context) {
    final ride = widget.ride;
    final offer = widget.offer;
    final body = switch (ride.state) {
      RideState.accepted => _accepted(ride),
      RideState.arrived => _arrived(ride),
      RideState.inProgress => _inProgress(ride),
      _ => null,
    };
    // Qualquer outro estado (terminada, cancelada...): não há o que mostrar; o `app.dart` fecha a rota.
    if (body == null) return const SizedBox.shrink();
    return Scaffold(
      appBar: AppBar(title: const Text('Corrida')),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          if (offer != null)
            OfferCard(
              key: ValueKey(offer.rideId),
              offer: offer,
              onAccept: () => widget.onAcceptOffer(offer.rideId),
              onDecline: () => widget.onDeclineOffer(offer.rideId),
            ),
          Text(
            '${brl(ride.priceCents)} · ${ride.method == 'cash' ? 'Dinheiro' : 'Pix'}',
          ),
          const SizedBox(height: 8),
          ...body,
        ],
      ),
    );
  }
}
