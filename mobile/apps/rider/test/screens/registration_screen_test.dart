import 'dart:convert';

import 'package:corrida_core/corrida_core.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:rider/photo_source.dart';
import 'package:rider/registration_data.dart';
import 'package:rider/screens/registration_screen.dart';

Photo _foto(DocKind kind) =>
    Photo(bytes: utf8.encode(kind.name), contentType: 'image/jpeg');

void _telaGrande(WidgetTester tester) {
  tester.view.physicalSize = const Size(800, 2600);
  tester.view.devicePixelRatio = 1.0;
  addTearDown(tester.view.reset);
}

Future<void> _pump(
  WidgetTester tester, {
  Future<Photo?> Function(DocKind kind)? onPickPhoto,
  Future<void> Function(RegistrationData data)? onSubmit,
}) async {
  _telaGrande(tester);
  await tester.pumpWidget(
    MaterialApp(
      home: RegistrationScreen(
        onPickPhoto: onPickPhoto ?? (kind) async => _foto(kind),
        onSubmit: onSubmit ?? (_) async {},
        onSignOut: () {},
      ),
    ),
  );
}

Future<void> _preencheTexto(WidgetTester tester) async {
  Future<void> digita(String chave, String texto) =>
      tester.enterText(find.byKey(Key(chave)), texto);
  await digita('nome', 'João Silva');
  await digita('cpf', '529.982.247-25');
  await digita('cnh', '12345678900');
  await digita('placa', 'ABC1D23');
  await digita('modelo', 'Honda CG 160');
  await digita('validade_cnh', '01/05/2030');
  await digita('validade_crlv', '31/12/2029');
}

Future<void> _tiraFoto(WidgetTester tester, String chave) async {
  await tester.tap(
    find.descendant(
      of: find.byKey(Key(chave)),
      matching: find.byType(OutlinedButton),
    ),
  );
  await tester.pumpAndSettle();
}

Future<void> _tiraTresFotos(WidgetTester tester) async {
  await _tiraFoto(tester, 'foto_selfie');
  await _tiraFoto(tester, 'foto_cnh');
  await _tiraFoto(tester, 'foto_crlv');
}

void main() {
  testWidgets('campos vazios mostram os avisos e nao enviam', (tester) async {
    var enviou = false;
    await _pump(tester, onSubmit: (_) async => enviou = true);

    await tester.tap(find.text('Enviar cadastro'));
    await tester.pumpAndSettle();

    expect(find.text('Preencha este campo'), findsNWidgets(7));
    expect(find.text('Falta a foto'), findsNWidgets(3));
    expect(enviou, isFalse);
  });

  testWidgets('data invalida mostra Use dd/mm/aaaa', (tester) async {
    var enviou = false;
    await _pump(tester, onSubmit: (_) async => enviou = true);
    await _preencheTexto(tester);
    await tester.enterText(find.byKey(const Key('validade_cnh')), '31/02/2030');
    await _tiraTresFotos(tester);

    await tester.tap(find.text('Enviar cadastro'));
    await tester.pumpAndSettle();

    expect(find.text('Use dd/mm/aaaa'), findsOneWidget);
    expect(enviou, isFalse);
  });

  testWidgets('sem foto mostra Falta a foto', (tester) async {
    var enviou = false;
    await _pump(tester, onSubmit: (_) async => enviou = true);
    await _preencheTexto(tester);
    await _tiraFoto(tester, 'foto_selfie');
    await _tiraFoto(tester, 'foto_cnh');

    await tester.tap(find.text('Enviar cadastro'));
    await tester.pumpAndSettle();

    expect(find.text('Falta a foto'), findsOneWidget);
    expect(enviou, isFalse);
  });

  testWidgets('tudo preenchido envia os dados certos', (tester) async {
    RegistrationData? recebido;
    await _pump(tester, onSubmit: (data) async => recebido = data);
    await _preencheTexto(tester);
    await _tiraTresFotos(tester);

    await tester.tap(find.text('Enviar cadastro'));
    await tester.pumpAndSettle();

    expect(recebido, isNotNull);
    expect(recebido!.name, 'João Silva');
    expect(recebido!.cpf, '529.982.247-25');
    expect(recebido!.cnhNumber, '12345678900');
    expect(recebido!.plate, 'ABC1D23');
    expect(recebido!.motoModel, 'Honda CG 160');
    expect(recebido!.cnhExpiresOn, DateTime(2030, 5, 1));
    expect(recebido!.crlvExpiresOn, DateTime(2029, 12, 31));
    expect(recebido!.photos.keys, unorderedEquals(DocKind.values));
    expect(recebido!.photos[DocKind.cnh]!.bytes, utf8.encode('cnh'));
  });

  testWidgets('erro do servidor mostra a mensagem e mantem o formulario', (
    tester,
  ) async {
    await _pump(
      tester,
      onSubmit: (_) async => throw ApiException(
        status: 409,
        code: 'duplicate_registration',
        message: 'Esse CPF já tem cadastro.',
      ),
    );
    await _preencheTexto(tester);
    await _tiraTresFotos(tester);

    await tester.tap(find.text('Enviar cadastro'));
    await tester.pumpAndSettle();

    expect(find.text('Esse CPF já tem cadastro.'), findsOneWidget);
    expect(find.text('João Silva'), findsOneWidget);
    expect(find.textContaining('Foto tirada'), findsNWidgets(3));
  });

  testWidgets('foto cancelada continua pedindo a foto', (tester) async {
    await _pump(tester, onPickPhoto: (_) async => null);

    await _tiraFoto(tester, 'foto_selfie');

    expect(find.text('Tirar foto'), findsNWidgets(3));
    expect(find.textContaining('Foto tirada'), findsNothing);
  });
}
