import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:rider/input_masks.dart';

TextEditingValue _type(TextInputFormatter f, String text) =>
    f.formatEditUpdate(TextEditingValue.empty, TextEditingValue(text: text));

void main() {
  test('CPF ganha pontos e traço enquanto digita', () {
    expect(_type(cpfMask, '5').text, '5');
    expect(_type(cpfMask, '5299').text, '529.9');
    expect(_type(cpfMask, '529982247').text, '529.982.247');
    expect(_type(cpfMask, '52998224725').text, '529.982.247-25');
  });

  test('CPF ignora o que não é número e o que passa de 11 dígitos', () {
    expect(_type(cpfMask, '529.982.247-25999').text, '529.982.247-25');
    expect(_type(cpfMask, 'abc').text, '');
  });

  test('o texto fixo não aparece sozinho no fim', () {
    expect(_type(dateMask, '31').text, '31');
    expect(_type(dateMask, '311').text, '31/1');
  });

  test('data completa', () {
    expect(_type(dateMask, '31122030').text, '31/12/2030');
  });

  test('o cursor vai para o fim', () {
    expect(_type(dateMask, '3112').selection.baseOffset, 5);
  });

  test('placa em maiúsculas, sem traço e com 7 caracteres', () {
    expect(_type(const PlateMask(), 'abc-1d23').text, 'ABC1D23');
    expect(_type(const PlateMask(), 'abc1d23xyz').text, 'ABC1D23');
  });

  test('CNH só números, 11 dígitos', () {
    expect(_type(cnhMask, '123.456.789-00999').text, '12345678900');
  });
}
