import 'package:flutter/services.dart';

/// Máscaras dos campos do cadastro: a pessoa digita só os números e o campo vai colocando os pontos e as barras.
/// O servidor aceita com ou sem máscara (ele mesmo limpa e confere).
class DigitsMask extends TextInputFormatter {
  /// `#` é um dígito; o resto é texto fixo. Ex.: `###.###.###-##`.
  const DigitsMask(this.pattern);

  final String pattern;

  @override
  TextEditingValue formatEditUpdate(
    TextEditingValue oldValue,
    TextEditingValue newValue,
  ) {
    final digits = newValue.text.replaceAll(RegExp(r'\D'), '');
    final out = StringBuffer();
    var used = 0;
    for (var i = 0; i < pattern.length && used < digits.length; i++) {
      if (pattern[i] == '#') {
        out.write(digits[used++]);
      } else {
        out.write(pattern[i]);
        // o texto fixo só entra se ainda vier um dígito depois dele
      }
    }
    final text = out.toString();
    return TextEditingValue(
      text: text,
      selection: TextSelection.collapsed(offset: text.length),
    );
  }
}

/// Placa: letras maiúsculas e números, sem traço, no máximo 7 caracteres (ABC1D23).
class PlateMask extends TextInputFormatter {
  const PlateMask();

  @override
  TextEditingValue formatEditUpdate(
    TextEditingValue oldValue,
    TextEditingValue newValue,
  ) {
    var text = newValue.text.toUpperCase().replaceAll(RegExp(r'[^A-Z0-9]'), '');
    if (text.length > 7) text = text.substring(0, 7);
    return TextEditingValue(
      text: text,
      selection: TextSelection.collapsed(offset: text.length),
    );
  }
}

const cpfMask = DigitsMask('###.###.###-##');
const dateMask = DigitsMask('##/##/####');
const cnhMask = DigitsMask('###########');
