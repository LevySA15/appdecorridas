import 'dart:convert';

import 'package:corrida_core/corrida_core.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:rider/photo_source.dart';
import 'package:rider/registration_data.dart';

import 'support/fakes.dart';
import 'support/mundo.dart';

Photo _foto(String conteudo) =>
    Photo(bytes: utf8.encode(conteudo), contentType: 'image/jpeg');

RegistrationData _dados(Map<DocKind, Photo> fotos) => RegistrationData(
  name: 'João Silva',
  cpf: '529.982.247-25',
  cnhNumber: '12345678900',
  plate: 'ABC1D23',
  motoModel: 'Honda CG 160',
  cnhExpiresOn: DateTime(2030, 5, 1),
  crlvExpiresOn: DateTime(2029, 12, 31),
  photos: fotos,
);

Map<DocKind, Photo> _tresFotos() => {
  DocKind.selfie: _foto('selfie'),
  DocKind.cnh: _foto('cnh'),
  DocKind.crlv: _foto('crlv'),
};

http.Response _enviada(DocKind kind) =>
    json({'key': 'u1/${kind.name}-1.jpg', 'bytes': 5}, 201);

/// Liga as três rotas de envio; `falhaNaCnh` faz a CNH responder 413 enquanto for verdadeiro.
void _rotas(Mundo m, {bool Function()? falhaNaCnh}) {
  for (final kind in DocKind.values) {
    m.on('PUT', '/v1/rider/documents/${kind.name}', (_) {
      if (kind == DocKind.cnh && (falhaNaCnh?.call() ?? false)) {
        return json({
          'error': {
            'code': 'file_too_large',
            'message': 'A foto é grande demais (máximo 8 MB).',
          },
        }, 413);
      }
      return _enviada(kind);
    });
  }
}

Future<Mundo> _logado() async {
  final m = Mundo();
  await m.store.save(Session(token: 'tok-1', userId: 'u1', role: 'rider'));
  await m.controller.start();
  m.requests.clear();
  return m;
}

void main() {
  test('cadastro envia as tres fotos em ordem e depois cadastra', () async {
    final m = await _logado();
    _rotas(m);
    m.on('POST', '/v1/rider/register', (_) => json({'status': 'pending'}, 201));

    await m.controller.registerRider(_dados(_tresFotos()));

    final ordem = m.requests
        .where((r) => r.method != 'GET')
        .map((r) => '${r.method} ${r.url.path}')
        .toList();
    expect(ordem, [
      'PUT /v1/rider/documents/selfie',
      'PUT /v1/rider/documents/cnh',
      'PUT /v1/rider/documents/crlv',
      'POST /v1/rider/register',
    ]);
    final envio = m.sent('PUT', '/v1/rider/documents/cnh').single;
    expect(envio.headers['content-type'], 'image/jpeg');
    expect(envio.bodyBytes, utf8.encode('cnh'));
    final corpo = jsonDecode(
      m.sent('POST', '/v1/rider/register').single.body,
    ) as Map<String, Object?>;
    expect(corpo['selfie_key'], 'u1/selfie-1.jpg');
    expect(corpo['cnh_photo_key'], 'u1/cnh-1.jpg');
    expect(corpo['crlv_key'], 'u1/crlv-1.jpg');
    expect(corpo['cnh_expires_on'], '2030-05-01');
    expect(corpo['crlv_expires_on'], '2029-12-31');
    expect(corpo['name'], 'João Silva');
    expect(corpo['plate'], 'ABC1D23');
    expect(m.sent('GET', '/v1/rider/state'), hasLength(1));
  });

  test('foto que ja subiu nao sobe de novo no segundo toque', () async {
    final m = await _logado();
    var cnhFalha = true;
    _rotas(m, falhaNaCnh: () => cnhFalha);
    m.on('POST', '/v1/rider/register', (_) => json({'status': 'pending'}, 201));
    final fotos = _tresFotos();

    await expectLater(
      m.controller.registerRider(_dados(fotos)),
      throwsA(
        isA<ApiException>().having((e) => e.code, 'code', 'file_too_large'),
      ),
    );
    expect(m.sent('PUT', '/v1/rider/documents/selfie'), hasLength(1));
    expect(m.sent('PUT', '/v1/rider/documents/cnh'), hasLength(1));
    expect(m.sent('PUT', '/v1/rider/documents/crlv'), isEmpty);
    expect(m.sent('POST', '/v1/rider/register'), isEmpty);

    cnhFalha = false;
    await m.controller.registerRider(_dados(fotos));

    expect(m.sent('PUT', '/v1/rider/documents/selfie'), hasLength(1));
    expect(m.sent('PUT', '/v1/rider/documents/cnh'), hasLength(2));
    expect(m.sent('PUT', '/v1/rider/documents/crlv'), hasLength(1));
    expect(m.sent('POST', '/v1/rider/register'), hasLength(1));
  });

  test(
    'cadastro duplicado repassa a mensagem e guarda as fotos enviadas',
    () async {
      final m = await _logado();
      _rotas(m);
      var duplicado = true;
      m.on('POST', '/v1/rider/register', (_) {
        if (duplicado) {
          return json({
            'error': {
              'code': 'duplicate_registration',
              'message': 'Esse CPF já tem cadastro.',
              'field': 'cpf',
            },
          }, 409);
        }
        return json({'status': 'pending'}, 201);
      });
      final fotos = _tresFotos();

      await expectLater(
        m.controller.registerRider(_dados(fotos)),
        throwsA(
          isA<ApiException>().having(
            (e) => e.message,
            'message',
            'Esse CPF já tem cadastro.',
          ),
        ),
      );

      duplicado = false;
      await m.controller.registerRider(_dados(fotos));

      expect(m.sent('PUT', '/v1/rider/documents/selfie'), hasLength(1));
      expect(m.sent('PUT', '/v1/rider/documents/cnh'), hasLength(1));
      expect(m.sent('PUT', '/v1/rider/documents/crlv'), hasLength(1));
      expect(m.sent('POST', '/v1/rider/register'), hasLength(2));
    },
  );

  test('renovar documentos envia so a foto dada', () async {
    final m = await _logado();
    _rotas(m);
    m.on('POST', '/v1/rider/documents/renew', (_) => http.Response('', 204));

    await m.controller.renewDocuments(
      cnhExpiresOn: DateTime(2031, 1, 2),
      crlvExpiresOn: DateTime(2031, 3, 4),
      cnhPhoto: _foto('cnh nova'),
    );

    expect(m.sent('PUT', '/v1/rider/documents/cnh'), hasLength(1));
    expect(m.sent('PUT', '/v1/rider/documents/crlv'), isEmpty);
    final corpo = jsonDecode(
      m.sent('POST', '/v1/rider/documents/renew').single.body,
    ) as Map<String, Object?>;
    expect(corpo['cnh_expires_on'], '2031-01-02');
    expect(corpo['crlv_expires_on'], '2031-03-04');
    expect(corpo['cnh_photo_key'], 'u1/cnh-1.jpg');
    expect(corpo.containsKey('crlv_key'), isFalse);
    expect(m.sent('GET', '/v1/rider/state'), hasLength(1));
  });

  test(
    'cadastro que deu certo nao falha se a releitura do estado cair',
    () async {
      final m = await _logado();
      _rotas(m);
      m.on(
        'POST',
        '/v1/rider/register',
        (_) => json({'status': 'pending'}, 201),
      );
      m.on(
        'GET',
        '/v1/rider/state',
        (_) => throw http.ClientException('sem rede'),
      );

      await m.controller.registerRider(_dados(_tresFotos()));

      expect(m.sent('POST', '/v1/rider/register'), hasLength(1));
    },
  );
}
