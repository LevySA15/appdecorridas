import 'package:corrida_core/corrida_core.dart';
import 'package:flutter/material.dart';

import '../format.dart';

/// O recibo de uma corrida encerrada. Só a concluída tem "Total"; a cancelada mostra a taxa, se houve.
class ReceiptScreen extends StatelessWidget {
  const ReceiptScreen({required this.ride, super.key});

  final RideHistoryItem ride;

  @override
  Widget build(BuildContext context) {
    final rider = ride.rider;
    final completed = ride.state == RideState.completed;
    return Scaffold(
      appBar: AppBar(title: const Text('Recibo')),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          _Line('Data', formatRideDate(ride.createdAt)),
          _Line('Situação', rideStateLabel(ride.state)),
          // sem endereço (mapa de mentira) a linha só ficaria em branco
          if (ride.pickupText.trim().isNotEmpty)
            _Line('Origem', ride.pickupText),
          if (ride.destinationText.trim().isNotEmpty)
            _Line('Destino', ride.destinationText),
          _Line('Distância', formatKm(ride.distanceM)),
          if (rider != null)
            _Line(
              'Motoqueiro',
              '${rider.name} · ${rider.plate} · ${rider.motoModel}',
            ),
          _Line('Forma de pagar', paymentLabel(ride.method)),
          if (ride.myStars != null) _Line('Sua nota', '${ride.myStars} de 5'),
          if (completed) ...[
            const Divider(height: 32),
            _Line('Total', brl(ride.priceCents), strong: true),
            if (ride.paymentPending) const _Line('', 'Pagamento pendente'),
          ],
          if (ride.feeCents > 0) ...[
            const Divider(height: 32),
            _Line(
              'Taxa de cancelamento',
              ride.feeRefunded
                  ? '${brl(ride.feeCents)} (devolvida)'
                  : brl(ride.feeCents),
            ),
          ],
        ],
      ),
    );
  }
}

class _Line extends StatelessWidget {
  const _Line(this.label, this.value, {this.strong = false});

  final String label;
  final String value;
  final bool strong;

  @override
  Widget build(BuildContext context) {
    final style = strong ? Theme.of(context).textTheme.titleMedium : null;
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 6),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SizedBox(width: 130, child: Text(label, style: style)),
          Expanded(child: Text(value, style: style)),
        ],
      ),
    );
  }
}
