import 'dart:async';

import 'package:corrida_core/corrida_core.dart';
import 'package:corrida_ui/corrida_ui.dart';
import 'package:flutter/material.dart';

import '../format.dart';

/// Uma oferta de corrida com o contador. O contador é só para mostrar: quem decide se a oferta ainda vale é
/// o servidor (`409 offer_gone`), então "Aceitar" e "Recusar" ficam ligados mesmo com o tempo esgotado.
/// Nada aqui aceita ou recusa sozinho.
/// Só desenha o trajeto quando a oferta traz os dois pontos de verdade (a oferta vazia vem com 0, 0).
bool _hasRoute(Offer offer) =>
    (offer.pickup.lat != 0 || offer.pickup.lng != 0) &&
    (offer.destination.lat != 0 || offer.destination.lng != 0);

class OfferCard extends StatefulWidget {
  const OfferCard({
    required this.offer,
    required this.onAccept,
    required this.onDecline,
    this.clock,
    super.key,
  });

  final Offer offer;
  final Future<void> Function() onAccept;
  final Future<void> Function() onDecline;

  /// Só para teste.
  final DateTime Function()? clock;

  @override
  State<OfferCard> createState() => _OfferCardState();
}

class _OfferCardState extends State<OfferCard> {
  Timer? _ticker;
  var _busy = false;

  DateTime _now() => (widget.clock ?? DateTime.now)();

  @override
  void initState() {
    super.initState();
    _ticker = Timer.periodic(const Duration(seconds: 1), (_) {
      if (mounted) setState(() {});
    });
  }

  @override
  void didUpdateWidget(covariant OfferCard oldWidget) {
    super.didUpdateWidget(oldWidget);
    // outra oferta no mesmo lugar: nada herdado da anterior
    if (oldWidget.offer.rideId != widget.offer.rideId) _busy = false;
  }

  @override
  void dispose() {
    _ticker?.cancel();
    super.dispose();
  }

  int get _secondsLeft {
    final left = widget.offer.expiresAt - _now().millisecondsSinceEpoch / 1000;
    return left <= 0 ? 0 : left.ceil();
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

  @override
  Widget build(BuildContext context) {
    final offer = widget.offer;
    final left = _secondsLeft;
    final toPickup = offer.secondsToPickup;
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Text(
              brl(offer.priceCents),
              style: Theme.of(context).textTheme.headlineMedium
                  ?.copyWith(fontSize: 40),
            ),
            const SizedBox(height: 8),
            Wrap(
              spacing: 8,
              runSpacing: 8,
              children: [
                InfoPill(
                  onCard: true,
                  icon: Icons.payments_outlined,
                  text: offer.paymentMethod == 'cash' ? 'Dinheiro' : 'Pix',
                ),
                InfoPill(
                  onCard: true,
                  icon: Icons.route_outlined,
                  text: 'Corrida de ${km(offer.distanceM)}',
                ),
                if (toPickup != null)
                  InfoPill(
                    onCard: true,
                    icon: Icons.two_wheeler_rounded,
                    text: '${(toPickup / 60).ceil()} min até o passageiro',
                  ),
              ],
            ),
            if (_hasRoute(offer)) ...[
              const SizedBox(height: 12),
              ClipRRect(
                borderRadius: BorderRadius.circular(16),
                child: SizedBox(
                  height: 140,
                  child: CorridaMapView(
                    interactive: false,
                    route: offer.route,
                    framePadding: const EdgeInsets.all(28),
                    markers: [
                      MapMarker(MarkerKind.pickup, offer.pickup),
                      MapMarker(MarkerKind.destination, offer.destination),
                    ],
                  ),
                ),
              ),
            ],
            const SizedBox(height: 8),
            if (offer.pickup.text.isNotEmpty)
              Text('Embarque: ${offer.pickup.text}'),
            if (offer.destination.text.isNotEmpty)
              Text('Destino: ${offer.destination.text}'),
            if (offer.willQueue)
              const Text(
                'Esta corrida espera na fila: você termina a de agora primeiro.',
              ),
            const SizedBox(height: 8),
            Text(
              left == 0 ? 'Tempo esgotado' : 'Responda em ${left}s',
              style: const TextStyle(fontWeight: FontWeight.w800),
            ),
            const SizedBox(height: 8),
            Row(
              children: [
                Expanded(
                  child: ElevatedButton(
                    onPressed: _busy ? null : () => _run(widget.onAccept),
                    child: const Text('Aceitar'),
                  ),
                ),
                const SizedBox(width: 8),
                Expanded(
                  child: OutlinedButton(
                    onPressed: _busy ? null : () => _run(widget.onDecline),
                    child: const Text('Recusar'),
                  ),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }
}
