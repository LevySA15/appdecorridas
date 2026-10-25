import 'dart:convert';

import 'package:corrida_core/corrida_core.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:rider/photo_source.dart';
import 'package:rider/screens/renew_documents_screen.dart';

Photo _foto(DocKind kind) =>
    Photo(bytes: utf8.encode(kind.name), contentType: 'image/jpeg');

Future<void> _pump(
  WidgetTester tester,
  Future<void> Function(DateTime, DateTime, Photo?, Photo?) onSubmit, {
  DateTime? initialCnh,
  DateTime? initialCrlv,
}) async {
  tester.view.physicalSize = const Size(800, 2000);
  tester.view.devicePixelRatio = 1.0;
  addTearDown(tester.view.reset);
  await tester.pumpWidget(
    MaterialApp(
      home: RenewDocumentsScreen(
        onPickPhoto: (kind) async => _foto(kind),
        onSubmit: onSubmit,
        initialCnhExpiresOn: initialCnh,
        initialCrlvExpiresOn: initialCrlv,
      ),
    ),
  );
}

void main() {
  testWidgets('datas invalidas nao enviam', (tester) async {
    var enviou = false;
    await _pump(tester, (_, _, _, _) async => enviou = true);
    await tester.enterText(find.byKey(const Key('validade_cnh')), '99/99/2030');
    await tester.enterText(find.byKey(const Key('validade_crlv')), '');

    await tester.tap(find.text('Enviar'));
    await tester.pumpAndSettle();

    expect(find.text('Use dd/mm/aaaa'), findsOneWidget);
    expect(find.text('Preencha este campo'), findsOneWidget);
    expect(enviou, isFalse);
  });

  testWidgets('datas boas sem foto enviam com null', (tester) async {
    DateTime? cnh;
    DateTime? crlv;
    Photo? fotoCnh = _foto(DocKind.selfie);
    Photo? fotoCrlv = _foto(DocKind.selfie);
    await _pump(tester, (a, b, c, d) async {
      cnh = a;
      crlv = b;
      fotoCnh = c;
      fotoCrlv = d;
    });
    await tester.enterText(find.byKey(const Key('validade_cnh')), '01/05/2031');
    await tester.enterText(
      find.byKey(const Key('validade_crlv')),
      '02/06/2032',
    );

    await tester.tap(find.text('Enviar'));
    await tester.pumpAndSettle();

    expect(cnh, DateTime(2031, 5, 1));
    expect(crlv, DateTime(2032, 6, 2));
    expect(fotoCnh, isNull);
    expect(fotoCrlv, isNull);
  });

  testWidgets('com a foto da CNH tirada envia a foto', (tester) async {
    Photo? fotoCnh;
    await _pump(tester, (_, _, c, _) async => fotoCnh = c);
    await tester.enterText(find.byKey(const Key('validade_cnh')), '01/05/2031');
    await tester.enterText(
      find.byKey(const Key('validade_crlv')),
      '02/06/2032',
    );
    await tester.tap(
      find.descendant(
        of: find.byKey(const Key('foto_cnh')),
        matching: find.byType(OutlinedButton),
      ),
    );
    await tester.pumpAndSettle();

    await tester.tap(find.text('Enviar'));
    await tester.pumpAndSettle();

    expect(fotoCnh, isNotNull);
    expect(fotoCnh!.bytes, utf8.encode('cnh'));
  });

  testWidgets('vem com as validades que ainda valem ja preenchidas', (
    tester,
  ) async {
    DateTime? cnh;
    await _pump(
      tester,
      (a, b, c, d) async => cnh = a,
      initialCnh: DateTime(2031, 5, 1),
    );

    String texto(String chave) =>
        tester.widget<TextField>(find.byKey(Key(chave))).controller!.text;
    expect(texto('validade_cnh'), '01/05/2031');
    expect(texto('validade_crlv'), '');

    await tester.enterText(
      find.byKey(const Key('validade_crlv')),
      '02/06/2032',
    );
    await tester.tap(find.text('Enviar'));
    await tester.pumpAndSettle();

    expect(cnh, DateTime(2031, 5, 1)); // manteve a CNH que não mudou
  });
}
