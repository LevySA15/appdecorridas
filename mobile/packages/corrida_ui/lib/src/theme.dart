import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';

/// Identidade visual dos dois apps (spec, seção 11; protótipo em `docs/prototipo/index.html`): estilo "claro e
/// direto" no modo claro, "escuro e ousado" no escuro, e uma cor de destaque só — o vermelho que o Levy escolheu.
///
/// Regra de contraste: o vermelho é **fundo** (botão, pino, barra) com texto branco por cima; nunca texto pequeno
/// sobre o preto. Erro comum também nunca é só vermelho: sempre vem com texto dizendo o que houve.
const corridaAccent = Color(0xFFD92D27);
const corridaOnAccent = Color(0xFFFFFFFF);

/// Cores que o `ColorScheme` do Material não tem nome para (tons de cartão e de linha do protótipo).
class CorridaPalette {
  const CorridaPalette({
    required this.page,
    required this.ink,
    required this.muted,
    required this.card,
    required this.line,
  });

  final Color page;
  final Color ink;
  final Color muted;
  final Color card;
  final Color line;

  static const light = CorridaPalette(
    page: Color(0xFFFFFFFF),
    ink: Color(0xFF14161A),
    muted: Color(0xFF5F6672),
    card: Color(0xFFF1F2F4),
    line: Color(0xFFE2E4E8),
  );

  static const dark = CorridaPalette(
    page: Color(0xFF0C0F14),
    ink: Color(0xFFF3F5F8),
    muted: Color(0xFF9AA3B2),
    card: Color(0xFF171C25),
    line: Color(0xFF232A36),
  );
}

ThemeData corridaTheme(Brightness brightness) {
  final p = brightness == Brightness.dark
      ? CorridaPalette.dark
      : CorridaPalette.light;
  final scheme = ColorScheme(
    brightness: brightness,
    primary: corridaAccent,
    onPrimary: corridaOnAccent,
    secondary: p.ink,
    onSecondary: p.page,
    error: brightness == Brightness.dark
        ? const Color(0xFFFF8A80)
        : const Color(0xFFB3261E),
    onError: brightness == Brightness.dark
        ? const Color(0xFF14161A)
        : const Color(0xFFFFFFFF),
    errorContainer: brightness == Brightness.dark
        ? const Color(0xFF3A1B1B)
        : const Color(0xFFFCE4E2),
    onErrorContainer: p.ink,
    surface: p.page,
    onSurface: p.ink,
    onSurfaceVariant: p.muted,
    surfaceContainerLowest: p.page,
    surfaceContainerLow: p.card,
    surfaceContainer: p.card,
    surfaceContainerHigh: p.card,
    surfaceContainerHighest: p.card,
    outline: p.line,
    outlineVariant: p.line,
    primaryContainer: p.card,
    onPrimaryContainer: p.ink,
    secondaryContainer: p.card,
    onSecondaryContainer: p.ink,
    inverseSurface: p.ink,
    onInverseSurface: p.page,
  );

  final base = ThemeData(
    useMaterial3: true,
    brightness: brightness,
    colorScheme: scheme,
    scaffoldBackgroundColor: p.page,
    canvasColor: p.page,
  );

  const buttonShape = StadiumBorder();
  final buttonPadding = const EdgeInsets.symmetric(
    horizontal: 24,
    vertical: 16,
  );
  const buttonText = TextStyle(fontSize: 16, fontWeight: FontWeight.w800);

  return base.copyWith(
    textTheme: base.textTheme
        .apply(bodyColor: p.ink, displayColor: p.ink)
        .copyWith(
          headlineMedium: base.textTheme.headlineMedium?.copyWith(
            fontWeight: FontWeight.w800,
            letterSpacing: -0.6,
            color: p.ink,
          ),
          headlineSmall: base.textTheme.headlineSmall?.copyWith(
            fontWeight: FontWeight.w800,
            letterSpacing: -0.4,
            color: p.ink,
          ),
          titleLarge: base.textTheme.titleLarge?.copyWith(
            fontWeight: FontWeight.w800,
            letterSpacing: -0.3,
            color: p.ink,
          ),
          titleMedium: base.textTheme.titleMedium?.copyWith(
            fontWeight: FontWeight.w700,
            color: p.ink,
          ),
        ),
    appBarTheme: AppBarTheme(
      backgroundColor: p.page,
      foregroundColor: p.ink,
      surfaceTintColor: Colors.transparent,
      elevation: 0,
      scrolledUnderElevation: 0,
      centerTitle: false,
      titleTextStyle: TextStyle(
        color: p.ink,
        fontSize: 20,
        fontWeight: FontWeight.w800,
        letterSpacing: -0.3,
      ),
    ),
    filledButtonTheme: FilledButtonThemeData(
      style: FilledButton.styleFrom(
        backgroundColor: corridaAccent,
        foregroundColor: corridaOnAccent,
        disabledBackgroundColor: p.card,
        disabledForegroundColor: p.muted,
        shape: buttonShape,
        padding: buttonPadding,
        textStyle: buttonText,
      ),
    ),
    elevatedButtonTheme: ElevatedButtonThemeData(
      style: ElevatedButton.styleFrom(
        backgroundColor: corridaAccent,
        foregroundColor: corridaOnAccent,
        disabledBackgroundColor: p.card,
        disabledForegroundColor: p.muted,
        elevation: 0,
        shape: buttonShape,
        padding: buttonPadding,
        textStyle: buttonText,
      ),
    ),
    outlinedButtonTheme: OutlinedButtonThemeData(
      style: OutlinedButton.styleFrom(
        foregroundColor: p.ink,
        side: BorderSide(color: p.ink, width: 1.5),
        shape: buttonShape,
        padding: buttonPadding,
        textStyle: buttonText,
      ),
    ),
    textButtonTheme: TextButtonThemeData(
      style: TextButton.styleFrom(
        foregroundColor: p.ink,
        shape: buttonShape,
        textStyle: const TextStyle(fontSize: 15, fontWeight: FontWeight.w700),
      ),
    ),
    inputDecorationTheme: InputDecorationTheme(
      filled: true,
      fillColor: p.card,
      contentPadding: const EdgeInsets.symmetric(horizontal: 18, vertical: 16),
      labelStyle: TextStyle(color: p.muted),
      floatingLabelStyle: TextStyle(color: p.ink, fontWeight: FontWeight.w700),
      border: _fieldBorder(BorderSide.none),
      enabledBorder: _fieldBorder(BorderSide.none),
      disabledBorder: _fieldBorder(BorderSide.none),
      focusedBorder: _fieldBorder(
        const BorderSide(color: corridaAccent, width: 2),
      ),
      errorBorder: _fieldBorder(BorderSide(color: scheme.error, width: 1.5)),
      focusedErrorBorder: _fieldBorder(
        BorderSide(color: scheme.error, width: 2),
      ),
    ),
    cardTheme: CardThemeData(
      color: p.card,
      elevation: 0,
      margin: EdgeInsets.zero,
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(18)),
    ),
    listTileTheme: ListTileThemeData(
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
      iconColor: p.ink,
    ),
    dividerTheme: DividerThemeData(color: p.line, space: 1, thickness: 1),
    dialogTheme: DialogThemeData(
      backgroundColor: p.page,
      surfaceTintColor: Colors.transparent,
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(24)),
      titleTextStyle: TextStyle(
        color: p.ink,
        fontSize: 22,
        fontWeight: FontWeight.w800,
        letterSpacing: -0.3,
      ),
    ),
    bottomSheetTheme: BottomSheetThemeData(
      backgroundColor: p.page,
      surfaceTintColor: Colors.transparent,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(28)),
      ),
    ),
    snackBarTheme: SnackBarThemeData(
      behavior: SnackBarBehavior.floating,
      backgroundColor: p.ink,
      contentTextStyle: TextStyle(color: p.page, fontWeight: FontWeight.w600),
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(14)),
    ),
    switchTheme: SwitchThemeData(
      thumbColor: const WidgetStatePropertyAll(Colors.white),
      trackColor: WidgetStateProperty.resolveWith(
        (states) =>
            states.contains(WidgetState.selected) ? corridaAccent : p.line,
      ),
      trackOutlineColor: const WidgetStatePropertyAll(Colors.transparent),
    ),
    chipTheme: ChipThemeData(
      backgroundColor: p.card,
      side: BorderSide.none,
      shape: const StadiumBorder(),
      labelStyle: TextStyle(color: p.ink, fontWeight: FontWeight.w600),
    ),
    progressIndicatorTheme: const ProgressIndicatorThemeData(
      color: corridaAccent,
    ),
  );
}

InputBorder _fieldBorder(BorderSide side) => UnderlineInputBorder(
  borderRadius: BorderRadius.circular(16),
  borderSide: side,
);

/// Os apps falam português do Brasil: botões do sistema ("Voltar", "Copiar"), datas e leitores de tela.
const corridaLocale = Locale('pt', 'BR');
const corridaSupportedLocales = [corridaLocale];
const corridaLocalizationsDelegates = GlobalMaterialLocalizations.delegates;
