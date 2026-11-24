import 'package:corrida_core/corrida_core.dart';
import 'package:corrida_ui/corrida_ui.dart';
import 'package:flutter/material.dart';

import '../dates.dart';
import '../format.dart';

/// O extrato do dia: corridas, o que entrou, a taxa do app e a taxa da próxima corrida. Abre em hoje; dá para
/// voltar aos dias anteriores. Quem carrega os dados é quem monta a tela (`onLoad`).
class StatementScreen extends StatefulWidget {
  const StatementScreen({required this.onLoad, this.clock, super.key});

  final Future<RiderStatement> Function(DateTime day) onLoad;

  /// Só para teste.
  final DateTime Function()? clock;

  @override
  State<StatementScreen> createState() => _StatementScreenState();
}

class _StatementScreenState extends State<StatementScreen> {
  late final DateTime _today;
  late DateTime _day;
  RiderStatement? _statement;
  String? _error;
  var _loading = true;
  var _request =
      0; // descarta a resposta de um dia que a pessoa já deixou para trás

  @override
  void initState() {
    super.initState();
    final now = (widget.clock ?? DateTime.now)();
    _today = DateTime(now.year, now.month, now.day);
    _day = _today;
    _load();
  }

  Future<void> _load() async {
    final request = ++_request;
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final statement = await widget.onLoad(_day);
      if (!mounted || request != _request) return;
      setState(() => _statement = statement);
    } on Exception catch (error) {
      if (!mounted || request != _request) return;
      setState(() {
        _statement = null;
        _error = friendlyMessage(error);
      });
    } finally {
      if (mounted && request == _request) setState(() => _loading = false);
    }
  }

  void _go(int days) {
    _day = DateTime(_day.year, _day.month, _day.day + days);
    _statement =
        null; // não deixa os números do dia anterior embaixo da data nova
    _load();
  }

  String _time(double epochSeconds) {
    final when = DateTime.fromMillisecondsSinceEpoch(
      (epochSeconds * 1000).round(),
    );
    return '${when.hour.toString().padLeft(2, '0')}:'
        '${when.minute.toString().padLeft(2, '0')}';
  }

  Widget _summary(RiderStatement statement) {
    final next = statement.nextRideNumber;
    final nextFee = statement.nextFeeCents;
    final theme = Theme.of(context);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Card(
          child: Padding(
            padding: const EdgeInsets.all(16),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  'Seu ganho: ${brl(statement.netCents)}',
                  style: theme.textTheme.headlineSmall,
                ),
                const SizedBox(height: 12),
                Wrap(
                  spacing: 8,
                  runSpacing: 8,
                  children: [
                    InfoPill(
                      onCard: true,
                      icon: Icons.two_wheeler_rounded,
                      text: 'Corridas: ${statement.completedCount}',
                    ),
                    InfoPill(
                      onCard: true,
                      icon: Icons.payments_outlined,
                      text: 'Total das corridas: ${brl(statement.grossCents)}',
                    ),
                    InfoPill(
                      onCard: true,
                      icon: Icons.percent_rounded,
                      text: 'Taxa do app: ${brl(statement.feeCents)}',
                    ),
                    InfoPill(
                      onCard: true,
                      icon: Icons.account_balance_wallet_outlined,
                      text:
                          'No Pix: ${brl(statement.pixCents)} · '
                          'Em dinheiro: ${brl(statement.cashCents)}',
                    ),
                    if (statement.pendingCents > 0)
                      InfoPill(
                        onCard: true,
                        icon: Icons.hourglass_bottom_rounded,
                        text:
                            'A receber (dinheiro): ${brl(statement.pendingCents)}',
                      ),
                  ],
                ),
              ],
            ),
          ),
        ),
        if (statement.cashDebtCents > 0) ...[
          const SizedBox(height: 12),
          NoticeCard(title: 'Taxas devidas: ${brl(statement.cashDebtCents)}'),
        ],
        if (next != null && nextFee != null) ...[
          const SizedBox(height: 12),
          Text(
            'Próxima corrida ($nextª do dia): taxa de ${brl(nextFee)}',
            style: TextStyle(color: theme.colorScheme.onSurfaceVariant),
          ),
        ],
        const SizedBox(height: 16),
        if (statement.rides.isEmpty) const Text('Nenhuma corrida neste dia.'),
        for (final ride in statement.rides)
          Padding(
            padding: const EdgeInsets.only(bottom: 8),
            child: Card(
              child: ListTile(
                title: Text(
                  '${_time(ride.completedAt)} · ${brl(ride.priceCents)} · '
                  '${ride.method == 'cash' ? 'Dinheiro' : 'Pix'}'
                  '${ride.confirmed ? '' : ' · a receber'}',
                  style: const TextStyle(fontWeight: FontWeight.w700),
                ),
                subtitle: Text(
                  'Ganho ${brl(ride.netCents)} (taxa ${brl(ride.feeCents)}) · '
                  '${km(ride.distanceM)}',
                ),
              ),
            ),
          ),
      ],
    );
  }

  @override
  Widget build(BuildContext context) {
    final statement = _statement;
    return Scaffold(
      appBar: AppBar(title: const Text('Extrato do dia')),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              TextButton(
                onPressed: () => _go(-1),
                child: const Text('Dia anterior'),
              ),
              Text(
                formatBrDate(_day),
                style: Theme.of(context).textTheme.titleMedium,
              ),
              TextButton(
                onPressed: _day.isBefore(_today) ? () => _go(1) : null,
                child: const Text('Próximo dia'),
              ),
            ],
          ),
          const SizedBox(height: 8),
          if (_loading && statement == null)
            const Center(child: CircularProgressIndicator())
          else if (_error != null) ...[
            Text(_error!),
            ElevatedButton(
              onPressed: _load,
              child: const Text('Tentar de novo'),
            ),
          ] else if (statement != null)
            _summary(statement),
        ],
      ),
    );
  }
}
