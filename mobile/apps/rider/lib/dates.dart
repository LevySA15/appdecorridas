/// Lê `dd/mm/aaaa` (com os zeros). Devolve `null` se estiver vazio, mal escrito ou for uma data que não
/// existe (31/02, mês 13, ano antes de 1900).
DateTime? parseBrDate(String text) {
  final match = RegExp(r'^(\d{2})/(\d{2})/(\d{4})$').firstMatch(text.trim());
  if (match == null) return null;
  final day = int.parse(match.group(1)!);
  final month = int.parse(match.group(2)!);
  final year = int.parse(match.group(3)!);
  if (year < 1900) return null;
  final date = DateTime(year, month, day);
  // DateTime "arruma" 31/02 para março: se mudou algum número, a data não existia.
  if (date.year != year || date.month != month || date.day != day) return null;
  return date;
}

/// Escreve `dd/mm/aaaa`.
String formatBrDate(DateTime date) =>
    '${date.day.toString().padLeft(2, '0')}/'
    '${date.month.toString().padLeft(2, '0')}/'
    '${date.year.toString().padLeft(4, '0')}';

/// O aviso de um campo de data, ou `null` se está bom.
String? dateFieldError(String text) {
  if (text.trim().isEmpty) return 'Preencha este campo';
  return parseBrDate(text) == null ? 'Use dd/mm/aaaa' : null;
}
