import 'dart:convert';

import 'package:corrida_core/corrida_core.dart';
import 'package:corrida_ui/corrida_ui.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:passenger/address_lookup.dart';
import 'package:passenger/screens/request_ride_screen.dart';

void main() {
  group('frase de endereço', () {
    test('rua, número e bairro', () {
      expect(
        addressFromNominatim({
          'address': {
            'road': 'Avenida Barros e Almeida',
            'house_number': '120',
            'suburb': 'São Cristóvão',
            'city': 'Santo Antônio de Jesus',
          },
        }),
        'Avenida Barros e Almeida, 120 - São Cristóvão',
      );
    });

    test('só a rua', () {
      expect(
        addressFromNominatim({
          'address': {'road': 'Rua Sete de Setembro'},
        }),
        'Rua Sete de Setembro',
      );
    });

    test('sem rua usa o nome do lugar e o bairro', () {
      expect(
        addressFromNominatim({
          'name': 'Praça Duque de Caxias',
          'address': {'suburb': 'Centro'},
        }),
        'Praça Duque de Caxias - Centro',
      );
    });

    test('sem nada útil cai no começo do nome completo', () {
      expect(
        addressFromNominatim({
          'display_name': 'Fazenda X, Zona Rural, Bahia, Brasil',
        }),
        'Fazenda X - Zona Rural',
      );
    });

    test('resposta vazia não vira endereço', () {
      expect(addressFromNominatim({}), isNull);
      expect(addressFromNominatim({'address': {}}), isNull);
    });
  });

  group('consulta ao Nominatim', () {
    test(
      'manda coordenada, idioma e identificação, e devolve a frase',
      () async {
        Uri? pedido;
        Map<String, String>? cabecalhos;
        final lookup = NominatimAddressLookup(
          client: MockClient((request) async {
            pedido = request.url;
            cabecalhos = request.headers;
            return http.Response(
              jsonEncode({
                'address': {'road': 'Rua A', 'suburb': 'Centro'},
              }),
              200,
              headers: {'content-type': 'application/json; charset=utf-8'},
            );
          }),
        );

        final text = await lookup.describe(
          const Place(lat: -12.9644, lng: -39.2597),
        );

        expect(text, 'Rua A - Centro');
        expect(pedido!.host, 'nominatim.openstreetmap.org');
        expect(pedido!.queryParameters['lat'], '-12.964400');
        expect(pedido!.queryParameters['accept-language'], 'pt-BR');
        expect(cabecalhos!['User-Agent'], contains('reconcavo'));
      },
    );

    test('erro do servidor, rede caída e resposta torta viram null (o pedido segue sem endereço)', () async {
      for (final client in [
        MockClient((_) async => http.Response('ruim', 503)),
        MockClient((_) async => throw http.ClientException('sem rede')),
        MockClient((_) async => http.Response('não é json', 200)),
        MockClient((_) async => http.Response('[]', 200)),
      ]) {
        expect(
          await NominatimAddressLookup(client: client)
              .describe(const Place(lat: 1, lng: 1)),
          isNull,
        );
      }
    });
  });

  group('na tela de pedir', () {
    Quote quote(Place from, Place to) => Quote(
      quoteId: 'q',
      priceCents: 800,
      distanceM: 2000,
      durationS: 600,
      reason: 'normal',
      expiresAt: 9999999999,
      pickup: from,
      destination: to,
      etaSeconds: 120,
      nearbyRiders: 1,
      paymentMethods: const ['cash'],
    );

    testWidgets('a cotação sai com o endereço e a folha mostra De e Para', (
      tester,
    ) async {
      final recebidos = <Place>[];
      await tester.pumpWidget(
        MaterialApp(
          theme: corridaTheme(Brightness.light),
          home: RequestRideScreen(
            addressLookup: _Fixo((p) => 'Rua ${p.lat.toStringAsFixed(3)}'),
            onQuote: (a, b) async {
              recebidos
                ..add(a)
                ..add(b);
              return quote(a, b);
            },
            onConfirm: (_, _) async {},
          ),
        ),
      );
      final rect = tester.getRect(find.byType(FakeMapPicker));
      await tester.tapAt(rect.topLeft + const Offset(60, 120));
      await tester.pump();
      await tester.tapAt(rect.bottomRight - const Offset(60, 200));
      await tester.pumpAndSettle();

      expect(recebidos, hasLength(2));
      expect(recebidos.every((p) => p.text.isNotEmpty), isTrue);
      expect(find.textContaining('De: '), findsOneWidget);
      expect(find.textContaining('Para: '), findsOneWidget);
    });

    testWidgets('serviço que não acha endereço não trava a cotação', (
      tester,
    ) async {
      final recebidos = <Place>[];
      await tester.pumpWidget(
        MaterialApp(
          theme: corridaTheme(Brightness.light),
          home: RequestRideScreen(
            addressLookup: _Fixo((_) => null),
            onQuote: (a, b) async {
              recebidos.add(a);
              return quote(a, b);
            },
            onConfirm: (_, _) async {},
          ),
        ),
      );
      final rect = tester.getRect(find.byType(FakeMapPicker));
      await tester.tapAt(rect.topLeft + const Offset(60, 120));
      await tester.pump();
      await tester.tapAt(rect.bottomRight - const Offset(60, 200));
      await tester.pumpAndSettle();

      expect(recebidos.single.text, '');
      expect(find.text('Pedir corrida'), findsOneWidget);
      expect(find.textContaining('De: '), findsNothing);
    });
  });
}

class _Fixo implements AddressLookup {
  _Fixo(this.f);

  final String? Function(Place) f;

  @override
  Future<String?> describe(Place place) async => f(place);
}
