import 'package:corrida_core/corrida_core.dart';
import 'package:flutter/material.dart';

import 'package:corrida_ui/corrida_ui.dart';

const _labels = {'pix': 'Pix', 'cash': 'Dinheiro', 'balance': 'Saldo'};

/// Mapa de mentira para marcar origem e destino, depois a cotação e a forma de pagamento.
class RequestRideScreen extends StatefulWidget {
  const RequestRideScreen({
    required this.onQuote,
    required this.onConfirm,
    super.key,
  });

  final Future<Quote> Function(Place pickup, Place destination) onQuote;
  final Future<void> Function(String quoteId, String method) onConfirm;

  @override
  State<RequestRideScreen> createState() => _RequestRideScreenState();
}

class _RequestRideScreenState extends State<RequestRideScreen> {
  Quote? _quote;
  String? _method;
  var _loading = false;

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
      final quote = await widget.onQuote(pickup, destination);
      if (!mounted) return;
      setState(() {
        _quote = quote;
        _method = quote.paymentMethods.first;
      });
    } on Exception catch (error) {
      _showError(_messageOf(error));
    } finally {
      if (mounted) setState(() => _loading = false);
    }
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
      body: quote == null ? _buildMarcando() : _buildCotado(quote),
    );
  }

  Widget _buildMarcando() {
    return Column(
      children: [
        const Padding(
          padding: EdgeInsets.all(16),
          child: Text('Toque para marcar a origem e depois o destino.'),
        ),
        Expanded(
          child: AspectRatio(
            aspectRatio: 1,
            child: FakeMapPicker(onChanged: _onPointsChanged),
          ),
        ),
        if (_loading)
          const Padding(
            padding: EdgeInsets.all(16),
            child: CircularProgressIndicator(),
          ),
      ],
    );
  }

  Widget _buildCotado(Quote quote) {
    return Padding(
      padding: const EdgeInsets.all(16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Text(
            brl(quote.priceCents),
            style: Theme.of(context).textTheme.headlineMedium,
            textAlign: TextAlign.center,
          ),
          const SizedBox(height: 8),
          Text('Distância: ${(quote.distanceM / 1000).toStringAsFixed(1)} km'),
          if (quote.etaSeconds != null)
            Text(
              'Moto chega em cerca de ${(quote.etaSeconds! / 60).round()} min',
            ),
          const SizedBox(height: 16),
          const Text('Forma de pagamento'),
          RadioGroup<String>(
            groupValue: _method,
            onChanged: (value) => setState(() => _method = value),
            child: Column(
              children: [
                for (final method in quote.paymentMethods)
                  RadioListTile<String>(
                    value: method,
                    title: Text(_labels[method] ?? method),
                  ),
              ],
            ),
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
      ),
    );
  }
}
