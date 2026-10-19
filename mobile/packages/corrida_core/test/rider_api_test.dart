import 'dart:convert';

import 'package:corrida_core/corrida_core.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:test/test.dart';

http.Response json(Object? body, [int status = 200]) =>
    http.Response.bytes(utf8.encode(jsonEncode(body)), status, headers: {'content-type': 'application/json'});

class Chamada {
  Chamada(this.method, this.path, this.body, this.bytes, this.contentType);

  final String method;
  final String path;
  final Object? body;
  final List<int> bytes;
  final String? contentType;
}

({RiderApi api, List<Chamada> chamadas}) mundo(http.Response Function(http.Request) responde) {
  final chamadas = <Chamada>[];
  final client = ApiClient(
    baseUrl: Uri.parse('http://s.teste'),
    httpClient: MockClient((r) async {
      final eJson = r.headers['content-type']?.startsWith('application/json') ?? false;
      chamadas.add(Chamada(r.method, r.url.path, eJson && r.body.isNotEmpty ? jsonDecode(r.body) : null, r.bodyBytes, r.headers['content-type']));
      return responde(r);
    }),
  )..token = 't';
  return (api: RiderApi(client), chamadas: chamadas);
}

const corrida = {'ride_id': 'ride-1', 'state': 'accepted', 'passenger': {'name': 'Ana'}};

void main() {
  test('state', () async {
    final m = mundo((r) => json({'registration': {'status': 'approved', 'online': false}}));
    final estado = await m.api.state();
    expect(estado.registration.status, RegistrationStatus.approved);
    expect((m.chamadas.single.method, m.chamadas.single.path), ('GET', '/v1/rider/state'));
  });

  test('ficar disponível, parar e mandar a posição', () async {
    final m = mundo((r) => http.Response('', 204));
    await m.api.goOnline();
    await m.api.sendPosition(-12.96, -39.26);
    await m.api.goOffline();
    expect(m.chamadas.map((c) => '${c.method} ${c.path}').toList(), [
      'POST /v1/rider/online',
      'POST /v1/rider/position',
      'POST /v1/rider/offline',
    ]);
    expect(m.chamadas[1].body, {'lat': -12.96, 'lng': -39.26});
  });

  test('ficar disponível recusado traz o motivo no código', () async {
    for (final codigo in ['not_approved', 'blocked', 'documents_expired', 'entry_pending', 'debt_pending']) {
      final m = mundo((r) => json({'error': {'code': codigo, 'message': 'frase'}}, 409));
      await expectLater(m.api.goOnline(), throwsA(isA<ApiException>().having((e) => e.code, 'code', codigo)));
    }
  });

  test('aceitar e recusar a oferta', () async {
    final m = mundo((r) => r.url.path.endsWith('decline') ? http.Response('', 204) : json(corrida));
    final aceita = await m.api.accept('ride-1');
    await m.api.decline('ride-2');
    expect(aceita.rideId, 'ride-1');
    expect(m.chamadas.map((c) => c.path).toList(), ['/v1/rider/offers/ride-1/accept', '/v1/rider/offers/ride-2/decline']);
  });

  test('chegar, capacete, iniciar com o código e terminar', () async {
    final m = mundo((r) => json(corrida));
    await m.api.arrive('ride-1');
    await m.api.confirmHelmet('ride-1');
    await m.api.start('ride-1', '4821');
    await m.api.complete('ride-1');
    expect(m.chamadas.map((c) => '${c.method} ${c.path}').toList(), [
      'POST /v1/rider/rides/ride-1/arrive',
      'POST /v1/rider/rides/ride-1/helmet',
      'POST /v1/rider/rides/ride-1/start',
      'POST /v1/rider/rides/ride-1/complete',
    ]);
    expect(m.chamadas[2].body, {'pin': '4821'});
  });

  test('código errado chega como wrong_pin', () async {
    final m = mundo((r) => json({'error': {'code': 'wrong_pin', 'message': 'Código errado.'}}, 422));
    await expectLater(m.api.start('ride-1', '0000'), throwsA(isA<ApiException>().having((e) => e.code, 'code', 'wrong_pin')));
  });

  test('recebi o dinheiro na mão', () async {
    final m = mundo((r) => http.Response('', 204));
    await m.api.cashReceived('ride-1');
    expect(m.chamadas.single.path, '/v1/rider/rides/ride-1/cash-received');
  });

  test('cobranças da entrada e da dívida', () async {
    final m = mundo((r) => json({'charge_id': 'c1', 'amount_cents': 5000, 'br_code': 'x'}, 201));
    final entrada = await m.api.entryCharge();
    final divida = await m.api.debtCharge();
    expect((entrada.chargeId, entrada.amountCents), ('c1', 5000));
    expect(divida.brCode, 'x');
    expect(m.chamadas.map((c) => c.path).toList(), ['/v1/rider/entry-charge', '/v1/rider/debt-charge']);
  });

  test('foto do documento vai como bytes crus com o tipo', () async {
    final m = mundo((r) => json({'key': 'k1', 'bytes': 3}, 201));
    final enviado = await m.api.uploadDocument(DocKind.selfie, [1, 2, 3], contentType: 'image/jpeg');
    expect((enviado.key, enviado.bytes), ('k1', 3));
    final chamada = m.chamadas.single;
    expect((chamada.method, chamada.path, chamada.contentType), ('PUT', '/v1/rider/documents/selfie', 'image/jpeg'));
    expect(chamada.bytes, [1, 2, 3]);
  });

  test('cada tipo de documento tem a sua rota', () async {
    final m = mundo((r) => json({'key': 'k', 'bytes': 1}, 201));
    await m.api.uploadDocument(DocKind.cnh, [1], contentType: 'image/png');
    await m.api.uploadDocument(DocKind.crlv, [1], contentType: 'image/webp');
    expect(m.chamadas.map((c) => c.path).toList(), ['/v1/rider/documents/cnh', '/v1/rider/documents/crlv']);
  });

  test('foto grande demais chega como file_too_large', () async {
    final m = mundo((r) => json({'error': {'code': 'file_too_large', 'message': 'A foto é grande demais (máximo 8 MB).'}}, 413));
    await expectLater(
      m.api.uploadDocument(DocKind.selfie, [1], contentType: 'image/jpeg'),
      throwsA(isA<ApiException>().having((e) => e.code, 'code', 'file_too_large').having((e) => e.status, 'status', 413)),
    );
  });

  test('cadastro manda todos os campos do formulário', () async {
    final m = mundo((r) => json({'status': 'pending'}, 201));
    final formulario = RiderRegistrationForm(
      name: 'João',
      cpf: '1',
      cnhNumber: '2',
      plate: 'ABC1D23',
      motoModel: 'CG',
      selfieKey: 's',
      cnhPhotoKey: 'c',
      crlvKey: 'r',
      cnhExpiresOn: DateTime(2028, 5, 1),
      crlvExpiresOn: DateTime(2027, 12, 31),
    );
    await m.api.register(formulario);
    expect((m.chamadas.single.method, m.chamadas.single.path), ('POST', '/v1/rider/register'));
    expect(m.chamadas.single.body, formulario.toJson());
  });

  test('renovar documentos manda só as fotos que mudaram', () async {
    final m = mundo((r) => http.Response('', 204));
    await m.api.renewDocuments(cnhExpiresOn: DateTime(2030, 1, 2), crlvExpiresOn: DateTime(2029, 3, 4));
    await m.api.renewDocuments(cnhExpiresOn: DateTime(2030, 1, 2), crlvExpiresOn: DateTime(2029, 3, 4), cnhPhotoKey: 'nova');
    expect(m.chamadas[0].path, '/v1/rider/documents/renew');
    expect(m.chamadas[0].body, {'cnh_expires_on': '2030-01-02', 'crlv_expires_on': '2029-03-04'});
    expect(m.chamadas[1].body, {'cnh_expires_on': '2030-01-02', 'crlv_expires_on': '2029-03-04', 'cnh_photo_key': 'nova'});
  });
}
