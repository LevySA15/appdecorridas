import 'package:flutter/material.dart';

import 'theme.dart';

/// A folha de baixo das telas com mapa (spec, seção 11: "mapa em primeiro plano, com a faixa de controles embaixo"):
/// cantos de cima arredondados, sombra para cima e respeito ao recorte do aparelho embaixo.
class SheetCard extends StatelessWidget {
  const SheetCard({required this.child, super.key});

  final Widget child;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return Container(
      decoration: BoxDecoration(
        color: scheme.surface,
        borderRadius: const BorderRadius.vertical(top: Radius.circular(28)),
        boxShadow: [
          BoxShadow(
            color: Colors.black.withValues(alpha: 0.14),
            blurRadius: 32,
            offset: const Offset(0, -12),
          ),
        ],
      ),
      // celular pequeno ou letra grande: a folha nunca passa de 80% da tela, o resto rola
      child: ConstrainedBox(
        constraints: BoxConstraints(
          maxHeight: MediaQuery.sizeOf(context).height * 0.8,
        ),
        child: SafeArea(
          top: false,
          child: SingleChildScrollView(
            padding: const EdgeInsets.fromLTRB(20, 20, 20, 16),
            child: child,
          ),
        ),
      ),
    );
  }
}

/// Bolinha com as iniciais do nome (ainda não há foto de perfil).
class InitialsAvatar extends StatelessWidget {
  const InitialsAvatar({required this.name, this.radius = 24, super.key});

  final String name;
  final double radius;

  String get _initials {
    final parts = name.trim().split(RegExp(r'\s+')).where((p) => p.isNotEmpty);
    if (parts.isEmpty) return '?';
    final first = parts.first.characters.first.toUpperCase();
    if (parts.length == 1) return first;
    return first + parts.last.characters.first.toUpperCase();
  }

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return CircleAvatar(
      radius: radius,
      backgroundColor: scheme.onSurface,
      child: Text(
        _initials,
        style: TextStyle(
          color: scheme.surface,
          fontWeight: FontWeight.w800,
          fontSize: radius * 0.75,
        ),
      ),
    );
  }
}

/// O código de 4 dígitos que o passageiro diz ao motoqueiro: bem grande, espaçado, num cartão só.
class PinDigits extends StatelessWidget {
  const PinDigits({required this.pin, super.key});

  final String pin;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 10),
      decoration: BoxDecoration(
        color: theme.colorScheme.surfaceContainer,
        borderRadius: BorderRadius.circular(16),
      ),
      child: Text(
        pin,
        style: theme.textTheme.headlineMedium?.copyWith(
          fontSize: 40,
          letterSpacing: 14,
          fontFeatures: const [FontFeature.tabularFigures()],
        ),
      ),
    );
  }
}

/// Uma informação curta com ícone ("3,3 km", "2 min", "Dinheiro").
class InfoPill extends StatelessWidget {
  const InfoPill({
    required this.text,
    this.icon,
    this.onCard = false,
    super.key,
  });

  final String text;
  final IconData? icon;

  /// Dentro de um cartão cinza a pílula usa o fundo da tela, para não sumir.
  final bool onCard;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
      decoration: BoxDecoration(
        color: onCard ? scheme.surface : scheme.surfaceContainer,
        borderRadius: BorderRadius.circular(99),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          if (icon != null) ...[
            Icon(icon, size: 16, color: scheme.onSurfaceVariant),
            const SizedBox(width: 6),
          ],
          Flexible(
            child: Text(
              text,
              maxLines: 2,
              overflow: TextOverflow.ellipsis,
              style: const TextStyle(fontWeight: FontWeight.w700),
            ),
          ),
        ],
      ),
    );
  }
}

/// Aviso com tarja vermelha na esquerda e texto dizendo o que houve (o vermelho nunca vai sozinho: spec, seção 11).
/// O botão fica ao lado do texto; em tela estreita (ou letra grande) desce para baixo do texto.
class NoticeCard extends StatelessWidget {
  const NoticeCard({
    this.title,
    this.body,
    this.children,
    this.action,
    super.key,
  }) : assert(
         title != null || children != null,
         'precisa de um título ou de linhas próprias',
       );

  final String? title;
  final String? body;

  /// Linhas próprias no lugar do título e do texto (ex.: vários avisos de documento).
  final List<Widget>? children;
  final Widget? action;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final text = Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children:
          children ??
          [
            Text(
              title!,
              style: const TextStyle(fontWeight: FontWeight.w800, fontSize: 16),
            ),
            if (body != null)
              Padding(
                padding: const EdgeInsets.only(top: 2),
                child: Text(
                  body!,
                  style: TextStyle(color: scheme.onSurfaceVariant),
                ),
              ),
          ],
    );
    return Container(
      decoration: BoxDecoration(
        color: scheme.surfaceContainer,
        borderRadius: BorderRadius.circular(14),
        border: const Border(left: BorderSide(color: corridaAccent, width: 5)),
      ),
      padding: const EdgeInsets.fromLTRB(14, 12, 12, 12),
      child: LayoutBuilder(
        builder: (context, constraints) {
          final action = this.action;
          if (action == null) return text;
          final scaled = MediaQuery.textScalerOf(context).scale(16) / 16;
          final narrow = constraints.maxWidth < 330 || scaled > 1.2;
          if (narrow) {
            return Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [text, const SizedBox(height: 10), action],
            );
          }
          return Row(
            children: [
              Expanded(child: text),
              const SizedBox(width: 8),
              action,
            ],
          );
        },
      ),
    );
  }
}
