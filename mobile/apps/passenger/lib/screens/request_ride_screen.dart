import 'package:corrida_core/corrida_core.dart';
import 'package:flutter/material.dart';

import 'package:corrida_ui/corrida_ui.dart';

import '../format.dart';
import '../address_lookup.dart';
import '../my_location.dart';

const _labels = {'pix': 'Pix', 'cash': 'Dinheiro', 'balance': 'Saldo'};

/// Mapa de mentira para marcar origem e destino, depois a cotação e a forma de pagamento.
class RequestRideScreen extends StatefulWidget {
  const RequestRideScreen({
    required this.onQuote,
    required this.onConfirm,
    this.myLocation,
    this.addressLookup,
    this.engine,
    super.key,
  });

  /// Com isto os dois pontos ganham o endereço escrito antes da cotação (o motoqueiro e o recibo mostram a rua).
  final AddressLookup? addressLookup;

  /// Com isto o mapa ganha o botão "Estou aqui" (o embarque vira a posição do celular). `null` esconde o botão.
  final MyLocation? myLocation;

  /// Só para teste: força o motor do mapa.
  final MapEngine? engine;

  final Future<Quote> Function(Place pickup, Place destination) onQuote;
  final Future<void> Function(String quoteId, String method) onConfirm;

  @override
  State<RequestRideScreen> createState() => _RequestRideScreenState();
}

class _RequestRideScreenState extends State<RequestRideScreen> {
  Quote? _quote;
  String? _method;
  var _loading = false;
  var _pickerRound = 0; // muda para o mapa recomeçar sem os pontos antigos
  Place? _myPlace; // onde a pessoa disse "estou aqui"
  var _locating = false;

  Future<void> _useMyLocation() async {
    final source = widget.myLocation;
    if (source == null || _locating) return;
    setState(() => _locating = true);
    try {
      final place = await source.current();
      if (!mounted) return;
      setState(() {
        _myPlace = place;
        _quote = null; // um embarque novo pede cotação nova
      });
    } on MyLocationUnavailable catch (error) {
      _showError(error.message);
    } on Exception catch (error) {
      _showError(_messageOf(error));
    } finally {
      if (mounted) setState(() => _locating = false);
    }
  }

  String _messageOf(Object error) => switch (error) {
    ApiException(message: final message) => message,
    NetworkException(message: final message) => message,
    _ => 'Algo deu errado. Tente de novo.',
  };

  void _showError(String message) {
    if (!mounted) return;
    ScaffoldMessenger.of(context)
        .showSnackBar(SnackBar(content: Text(message)));
  }

  Future<void> _onPointsChanged(Place? pickup, Place? destination) async {
    if (pickup == null || destination == null) return;
    setState(() => _loading = true);
    try {
      final from = await _withAddress(pickup);
      final to = await _withAddress(destination);
      final quote = await widget.onQuote(from, to);
      if (!mounted) return;
      setState(() {
        _quote = quote;
        _method = quote.paymentMethods.first;
      });
    } on Exception catch (error) {
      if (mounted)
        setState(() => _pickerRound++); // a cotação falhou: marca tudo de novo
      _showError(_messageOf(error));
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  /// O ponto com o endereço escrito, se o serviço de endereços achar (se não, o mesmo ponto: a cotação não espera por isso).
  Future<Place> _withAddress(Place place) async {
    final lookup = widget.addressLookup;
    if (lookup == null || place.text.isNotEmpty) return place;
    final text = await lookup.describe(place);
    if (text == null || text.isEmpty) return place;
    return Place(lat: place.lat, lng: place.lng, text: text);
  }

  Future<void> _confirm() async {
    final quote = _quote;
    final method = _method;
    if (quote == null || method == null) return;
    setState(() => _loading = true);
    try {
      await widget.onConfirm(quote.quoteId, method);
    } on ApiException catch (error) {
      if (error.code == 'quote_expired') {
        if (mounted) setState(() => _quote = null);
        _showError('Essa cotação venceu, marque de novo.');
      } else {
        _showError(error.message);
      }
    } on Exception catch (error) {
      _showError(_messageOf(error));
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final quote = _quote;
    return Scaffold(
      appBar: AppBar(title: const Text('Nova corrida')),
      body: Stack(
        children: [
          Positioned.fill(
            child: CorridaMapPicker(
              engine: widget.engine,
              pickup: _myPlace,
              bottomSpace: 300,
              key: ValueKey(_pickerRound),
              onChanged: _onPointsChanged,
            ),
          ),
          if (quote == null)
            Align(
              alignment: Alignment.topCenter,
              // a dica não pode engolir o toque: no celular pequeno ela cobre o alto do mapa
              child: IgnorePointer(
                child: Padding(
                  // sobra espaço em cima para a atribuição do mapa de verdade ("© OpenStreetMap")
                  padding: const EdgeInsets.fromLTRB(16, 34, 16, 16),
                  child: _Hint(
                    loading: _loading,
                    text: 'Toque para marcar a origem e depois o destino.',
                  ),
                ),
              ),
            )
          else
            Align(
              alignment: Alignment.bottomCenter,
              child: SheetCard(child: _buildCotado(quote)),
            ),
          if (quote == null && widget.myLocation != null)
            Positioned(
              right: 16,
              bottom: 24,
              child: SafeArea(
                child: FloatingActionButton.extended(
                  onPressed: _locating ? null : _useMyLocation,
                  backgroundColor: Theme.of(context).colorScheme.surface,
                  foregroundColor: Theme.of(context).colorScheme.onSurface,
                  icon: _locating
                      ? const SizedBox(
                          width: 20,
                          height: 20,
                          child: CircularProgressIndicator(strokeWidth: 2),
                        )
                      : const Icon(Icons.my_location_rounded),
                  label: const Text('Estou aqui'),
                ),
              ),
            ),
        ],
      ),
    );
  }

  Widget _buildCotado(Quote quote) {
    final theme = Theme.of(context);
    return Column(
      mainAxisSize: MainAxisSize.min,
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Text(
          brl(quote.priceCents),
          style: theme.textTheme.headlineMedium?.copyWith(fontSize: 40),
        ),
        const SizedBox(height: 8),
        Wrap(
          spacing: 8,
          runSpacing: 8,
          children: [
            InfoPill(
              icon: Icons.route_outlined,
              text: formatKm(quote.distanceM),
            ),
            if (quote.etaSeconds != null)
              InfoPill(
                icon: Icons.two_wheeler_rounded,
                text: 'chega em ${(quote.etaSeconds! / 60).round()} min',
              ),
          ],
        ),
        if (quote.pickup.text.isNotEmpty ||
            quote.destination.text.isNotEmpty) ...[
          const SizedBox(height: 12),
          if (quote.pickup.text.isNotEmpty)
            Text(
              'De: ${quote.pickup.text}',
              maxLines: 2,
              overflow: TextOverflow.ellipsis,
            ),
          if (quote.destination.text.isNotEmpty)
            Text(
              'Para: ${quote.destination.text}',
              maxLines: 2,
              overflow: TextOverflow.ellipsis,
            ),
        ],
        const SizedBox(height: 16),
        Text(
          'Forma de pagamento',
          style: TextStyle(color: theme.colorScheme.onSurfaceVariant),
        ),
        const SizedBox(height: 8),
        Wrap(
          spacing: 8,
          children: [
            for (final method in quote.paymentMethods)
              ChoiceChip(
                label: Text(_labels[method] ?? method),
                selected: _method == method,
                showCheckmark: false,
                selectedColor: corridaAccent,
                labelStyle: TextStyle(
                  fontWeight: FontWeight.w700,
                  color: _method == method
                      ? corridaOnAccent
                      : theme.colorScheme.onSurface,
                ),
                onSelected: (_) => setState(() => _method = method),
              ),
          ],
        ),
        const SizedBox(height: 16),
        ElevatedButton(
          onPressed: _loading ? null : _confirm,
          child: _loading
              ? const SizedBox(
                  width: 20,
                  height: 20,
                  child: CircularProgressIndicator(strokeWidth: 2),
                )
              : const Text('Pedir corrida'),
        ),
      ],
    );
  }
}

/// Dica no alto do mapa; vira um "calculando" enquanto a cotação não volta.
class _Hint extends StatelessWidget {
  const _Hint({required this.text, required this.loading});

  final String text;
  final bool loading;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
      decoration: BoxDecoration(
        color: scheme.surface,
        borderRadius: BorderRadius.circular(16),
        boxShadow: [
          BoxShadow(
            color: Colors.black.withValues(alpha: 0.12),
            blurRadius: 12,
          ),
        ],
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          if (loading) ...[
            const SizedBox(
              width: 16,
              height: 16,
              child: CircularProgressIndicator(strokeWidth: 2),
            ),
            const SizedBox(width: 10),
          ],
          Flexible(
            child: Text(
              loading ? 'Calculando o preço...' : text,
              style: const TextStyle(fontWeight: FontWeight.w600),
            ),
          ),
        ],
      ),
    );
  }
}
