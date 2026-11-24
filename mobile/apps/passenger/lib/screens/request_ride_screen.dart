import 'package:corrida_core/corrida_core.dart';
import 'package:flutter/material.dart';

import 'package:corrida_ui/corrida_ui.dart';

import '../format.dart';

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
  var _pickerRound = 0; // muda para o mapa recomeçar sem os pontos antigos

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
      if (mounted)
        setState(() => _pickerRound++); // a cotação falhou: marca tudo de novo
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
      body: Stack(
        children: [
          Positioned.fill(
            child: FakeMapPicker(
              key: ValueKey(_pickerRound),
              onChanged: _onPointsChanged,
            ),
          ),
          if (quote == null)
            Align(
              alignment: Alignment.topCenter,
              child: Padding(
                padding: const EdgeInsets.all(16),
                child: _Hint(
                  loading: _loading,
                  text: 'Toque para marcar a origem e depois o destino.',
                ),
              ),
            )
          else
            Align(
              alignment: Alignment.bottomCenter,
              child: SheetCard(child: _buildCotado(quote)),
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
