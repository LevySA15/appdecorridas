import 'package:corrida_core/corrida_core.dart';
import 'package:corrida_ui/corrida_ui.dart' show friendlyMessage;
import 'package:flutter/material.dart';

import '../format.dart';

/// "Minhas corridas": as corridas encerradas, da mais nova para a mais antiga, de 20 em 20.
class HistoryScreen extends StatefulWidget {
  const HistoryScreen({
    required this.onLoad,
    required this.onOpenReceipt,
    super.key,
  });

  /// Pede a página que começa depois de [offset] corridas.
  final Future<RideHistoryPage> Function(int offset) onLoad;
  final void Function(RideHistoryItem ride) onOpenReceipt;

  @override
  State<HistoryScreen> createState() => _HistoryScreenState();
}

class _HistoryScreenState extends State<HistoryScreen> {
  final _rides = <RideHistoryItem>[];
  var _hasMore = false;
  var _loadingFirst = true;
  var _loadingMore = false;
  String? _firstError;

  @override
  void initState() {
    super.initState();
    _loadFirst();
  }

  Future<void> _loadFirst() async {
    setState(() {
      _loadingFirst = true;
      _firstError = null;
    });
    try {
      final page = await widget.onLoad(0);
      if (!mounted) return;
      setState(() {
        _rides
          ..clear()
          ..addAll(page.rides);
        _hasMore = page.hasMore;
        _loadingFirst = false;
      });
    } on Exception catch (error) {
      if (!mounted) return;
      setState(() {
        _firstError = friendlyMessage(error);
        _loadingFirst = false;
      });
    }
  }

  Future<void> _loadMore() async {
    setState(() => _loadingMore = true);
    try {
      final page = await widget.onLoad(_rides.length);
      if (!mounted) return;
      setState(() {
        _rides.addAll(page.rides);
        _hasMore = page.hasMore;
      });
    } on Exception catch (error) {
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(friendlyMessage(error))));
    } finally {
      if (mounted) setState(() => _loadingMore = false);
    }
  }

  Widget _body() {
    if (_loadingFirst) {
      return const Center(child: CircularProgressIndicator());
    }
    if (_firstError != null) {
      return Center(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Text(_firstError!, textAlign: TextAlign.center),
              const SizedBox(height: 16),
              FilledButton(
                onPressed: _loadFirst,
                child: const Text('Tentar de novo'),
              ),
            ],
          ),
        ),
      );
    }
    if (_rides.isEmpty) {
      return const Center(child: Text('Você ainda não fez corridas.'));
    }
    return ListView(
      children: [
        for (final ride in _rides)
          ListTile(
            onTap: () => widget.onOpenReceipt(ride),
            title: Text(formatRideDate(ride.createdAt)),
            subtitle: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(rideStateLabel(ride.state)),
                Text(
                  ride.pickupText,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                ),
                Text(
                  '→ ${ride.destinationText}',
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                ),
              ],
            ),
            // só a corrida concluída teve preço cobrado
            trailing: ride.state == RideState.completed
                ? Text(brl(ride.priceCents))
                : null,
          ),
        if (_hasMore)
          Padding(
            padding: const EdgeInsets.all(16),
            child: OutlinedButton(
              onPressed: _loadingMore ? null : _loadMore,
              child: _loadingMore
                  ? const SizedBox(
                      width: 16,
                      height: 16,
                      child: CircularProgressIndicator(strokeWidth: 2),
                    )
                  : const Text('Ver mais'),
            ),
          ),
      ],
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Minhas corridas')),
      body: _body(),
    );
  }
}
