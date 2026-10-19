// Contrato do cliente Dart com o servidor de verdade (descartável): uma sequência de corridas inteira, do cadastro ao
// saque. Só roda com CORRIDA_URL (veja mobile/tool/contrato.sh). Cada etapa depende da anterior; um erro aqui quase
// sempre quer dizer que o pacote e o servidor se afastaram.
import 'dart:async';
import 'dart:io';

import 'package:corrida_core/corrida_core.dart';
import 'package:test/test.dart';

final String? url = Platform.environment['CORRIDA_URL'];
final String adminPhone = Platform.environment['CORRIDA_ADMIN_PHONE'] ?? '';

/// Santo Antônio de Jesus, aproximado (o mesmo ponto que o servidor usa nos testes).
const origem = Place(lat: -12.9644, lng: -39.2597, text: 'Rua A');
const destino = Place(lat: -12.950911, lng: -39.2597, text: 'Feira livre'); // ~1,5 km ao norte
const motoPerto = (lat: -12.961702, lng: -39.2597); // ~300 m ao norte da origem
const jpeg = [0xff, 0xd8, 0xff, 0xe0, 83, 73, 77, 85, 76, 65, 68, 79, 82];

class Pessoa {
  Pessoa(this.phone, this.role) : api = ApiClient(baseUrl: Uri.parse(url!)) {
    auth = AuthApi(api);
  }

  final String phone;
  final String role;
  final ApiClient api;
  late final AuthApi auth;
  late final VerifyResult entrada;
  RealtimeClient? tempoReal;
  final _pendentes = <ServerEvent>[];

  Future<void> entrar({String? nome}) async {
    await auth.requestCode(phone);
    final dev = (await api.get('/v1/dev/otp', query: {'phone': phone}))! as Map;
    entrada = await auth.verify(phone: phone, code: '${dev['code']}', role: role, device: 'contrato-dart');
    if (nome != null) await auth.updateName(nome);
  }

  Future<void> abrirTempoReal() async {
    final cliente = RealtimeClient(baseUrl: Uri.parse(url!), tokenProvider: () => api.token ?? '');
    tempoReal = cliente;
    cliente.events.listen(_pendentes.add);
    final pronto = cliente.status.firstWhere((s) => s == RealtimeStatus.ready).timeout(const Duration(seconds: 10));
    cliente.start();
    await pronto;
  }

  /// Espera um aviso do tipo dado (e, se pedido, daquela corrida) e o consome.
  Future<ServerEvent> espera(String type, {String? rideId, Duration limite = const Duration(seconds: 10)}) async {
    final fim = DateTime.now().add(limite);
    while (DateTime.now().isBefore(fim)) {
      final i = _pendentes.indexWhere((e) => e.type == type && (rideId == null || e.data['ride_id'] == rideId));
      if (i >= 0) return _pendentes.removeAt(i);
      await Future<void>.delayed(const Duration(milliseconds: 40));
    }
    throw TimeoutException('não chegou o aviso "$type" (chegaram: ${_pendentes.map((e) => e.type).toList()})');
  }

  Future<void> fechar() async {
    await tempoReal?.close();
    api.close();
  }
}

Future<void> pagarNoDev(Pessoa quem, String chargeId) async {
  final resposta = (await quem.api.post('/v1/dev/pix/$chargeId/pay'))! as Map;
  expect(resposta['status'], 'applied');
}

void main() {
  if (url == null) {
    test('contrato com o servidor', () {}, skip: 'defina CORRIDA_URL (veja mobile/tool/contrato.sh)');
    return;
  }

  late final Pessoa admin;
  late final Pessoa ana; // passageira
  late final Pessoa joao; // motoqueiro
  late final PassengerApi passageiro;
  late final RiderApi motoqueiro;

  setUpAll(() async {
    admin = Pessoa(adminPhone, 'admin');
    ana = Pessoa('75 98851-0001', 'passenger');
    joao = Pessoa('75 98851-0002', 'rider');
    passageiro = PassengerApi(ana.api);
    motoqueiro = RiderApi(joao.api);
  });

  tearDownAll(() async {
    for (final p in [admin, ana, joao]) {
      await p.fechar();
    }
  });

  /// Uma corrida do pedido até o aceite. Devolve o id da corrida (o motoqueiro precisa estar disponível e perto).
  Future<String> pedirEAceitar(String method) async {
    await motoqueiro.sendPosition(motoPerto.lat, motoPerto.lng);
    final cotacao = await passageiro.quote(origem, destino);
    final corrida = await passageiro.requestRide(quoteId: cotacao.quoteId, method: method);
    expect(corrida.state, RideState.searching);
    final oferta = await joao.espera('offer', rideId: corrida.rideId);
    expect(Offer.fromJson(oferta.data).priceCents, cotacao.priceCents);
    final estadoMoto = await motoqueiro.state();
    expect(estadoMoto.offer!.rideId, corrida.rideId);
    final aceita = await motoqueiro.accept(corrida.rideId);
    expect(aceita.state, RideState.accepted);
    await joao.espera('ride_assigned', rideId: corrida.rideId);
    final aviso = await ana.espera('rider_accepted', rideId: corrida.rideId);
    expect(aviso.data['pin'], matches(RegExp(r'^\d{4}$')));
    return corrida.rideId;
  }

  /// Da moto a caminho até o fim da corrida (a corrida já está paga, ou é em dinheiro).
  Future<void> viajar(String rideId) async {
    await motoqueiro.arrive(rideId);
    await ana.espera('rider_arrived', rideId: rideId);
    await motoqueiro.confirmHelmet(rideId);
    final pin = (await passageiro.state()).ride!.pin;
    final errado = pin == '0000' ? '1111' : '0000';
    await expectLater(motoqueiro.start(rideId, errado), throwsA(isA<ApiException>().having((e) => e.code, 'code', 'wrong_pin')));
    final andando = await motoqueiro.start(rideId, pin);
    expect(andando.state, RideState.inProgress);
    await ana.espera('trip_started', rideId: rideId);
    await motoqueiro.sendPosition(motoPerto.lat, motoPerto.lng);
    final fim = await motoqueiro.complete(rideId);
    expect(fim.state, RideState.completed);
    await ana.espera('trip_completed', rideId: rideId);
    await joao.espera('trip_completed', rideId: rideId);
  }

  test('1. entrar: passageira, motoqueiro e administrador', () async {
    await ana.entrar(nome: 'Ana Contrato');
    await joao.entrar();
    await admin.entrar();
    expect(ana.entrada.isNewUser, isTrue);
    expect(ana.entrada.session.role, 'passenger');
    final eu = await ana.auth.me();
    expect((eu.name, eu.role), ('Ana Contrato', 'passenger'));
    await expectLater(
      AuthApi(ApiClient(baseUrl: Uri.parse(url!))).verify(phone: ana.phone, code: '000000', role: 'passenger'),
      throwsA(isA<ApiException>().having((e) => e.code, 'code', 'code_invalid')),
    );
    await ana.abrirTempoReal();
    await joao.abrirTempoReal();
  });

  test('2. o estado vazio do passageiro e do motoqueiro novo', () async {
    final estado = await passageiro.state();
    expect(estado.ride, isNull);
    expect(estado.balanceCents, 0);
    expect(estado.paymentMethods, containsAll(['pix', 'cash']));
    expect(estado.withdrawEnabled, isTrue); // o servidor descartável liga o saque
    await passageiro.setEmergencyContact(name: 'Maria', phone: '75 98851-0824');
    expect((await passageiro.state()).emergencyContact!.name, 'Maria');
    final moto = await motoqueiro.state();
    expect(moto.registration.status, RegistrationStatus.notRegistered);
    expect(moto.account, isNull);
  });

  test('3. cadastro do motoqueiro, aprovação pelo administrador e ficar disponível', () async {
    final chaves = <DocKind, String>{};
    for (final tipo in DocKind.values) {
      chaves[tipo] = (await motoqueiro.uploadDocument(tipo, jpeg, contentType: 'image/jpeg')).key;
    }
    await motoqueiro.register(RiderRegistrationForm(
      name: 'João da Moto',
      cpf: '529.982.247-25',
      cnhNumber: '12345678900',
      plate: 'ABC1D23',
      motoModel: 'Honda CG 160',
      selfieKey: chaves[DocKind.selfie]!,
      cnhPhotoKey: chaves[DocKind.cnh]!,
      crlvKey: chaves[DocKind.crlv]!,
      cnhExpiresOn: DateTime(2031, 1, 1),
      crlvExpiresOn: DateTime(2031, 6, 30),
    ));
    expect((await motoqueiro.state()).registration.status, RegistrationStatus.pending);
    await expectLater(motoqueiro.goOnline(), throwsA(isA<ApiException>().having((e) => e.code, 'code', 'not_approved')));

    final fila = (await admin.api.get('/v1/admin/riders', query: {'status': 'pending'}))! as List;
    final riderId = (fila.single as Map)['rider_id'];
    await admin.api.post('/v1/admin/riders/$riderId/approve');
    await joao.espera('rider_approved');
    final estado = await motoqueiro.state();
    expect(estado.registration.status, RegistrationStatus.approved);
    expect(estado.account!.trialRides, greaterThan(0));
    expect(estado.account!.blockedReason, isNull);

    await motoqueiro.goOnline();
    await motoqueiro.sendPosition(motoPerto.lat, motoPerto.lng);
    expect((await motoqueiro.state()).registration.online, isTrue);
  });

  test('4. corrida paga com Pix, do pedido à avaliação', () async {
    final cotacao = await passageiro.quote(origem, destino);
    expect(cotacao.etaSeconds, isNotNull);
    expect(cotacao.paymentMethods, containsAll(['pix', 'cash']));
    expect(cotacao.canPayWithBalance, isFalse);
    await motoqueiro.sendPosition(motoPerto.lat, motoPerto.lng);
    final corrida = await passageiro.requestRide(quoteId: cotacao.quoteId, method: 'pix');
    await joao.espera('offer', rideId: corrida.rideId);
    await motoqueiro.accept(corrida.rideId);
    final aviso = await ana.espera('rider_accepted', rideId: corrida.rideId);
    final pagar = PixToPay.fromJson((aviso.data['pay']! as Map).cast<String, Object?>());
    final noEstado = (await passageiro.state()).ride!;
    expect(noEstado.state, RideState.accepted);
    expect(noEstado.pay!.chargeId, pagar.chargeId);
    expect(noEstado.rider!.name, isNotEmpty);
    expect(noEstado.cancel!.feeCentsNow, 0);
    final cobranca = await passageiro.charge(pagar.chargeId);
    expect((cobranca.purpose, cobranca.amountCents, cobranca.paid), ('ride', cotacao.priceCents, false));
    expect(cobranca.brCode, isNotEmpty);

    await pagarNoDev(ana, pagar.chargeId);
    await ana.espera('pix_confirmed', rideId: corrida.rideId);
    await joao.espera('payment_received', rideId: corrida.rideId);
    expect((await passageiro.state()).ride!.pixPaid, isTrue);

    await viajar(corrida.rideId);
    expect((await passageiro.state()).ride, isNull);
    await passageiro.rate(corrida.rideId, 5);
    await motoqueiro.rate(corrida.rideId, 4);
    await expectLater(passageiro.rate(corrida.rideId, 5), throwsA(isA<ApiException>().having((e) => e.code, 'code', 'already_rated')));
  });

  test('5. saldo: recarregar, pagar a corrida com ele e sacar o que sobrou', () async {
    final recarga = await passageiro.topup(2000);
    await pagarNoDev(ana, recarga.chargeId);
    final mudou = await ana.espera('balance_changed');
    expect(mudou.data['balance_cents'], 2000);
    final cotacao = await passageiro.quote(origem, destino);
    expect(cotacao.canPayWithBalance, isTrue);
    await motoqueiro.sendPosition(motoPerto.lat, motoPerto.lng);
    final corrida = await passageiro.requestRide(quoteId: cotacao.quoteId, method: 'balance');
    expect(corrida.payWithBalance, isTrue);
    await joao.espera('offer', rideId: corrida.rideId);
    await motoqueiro.accept(corrida.rideId);
    final pago = await ana.espera('balance_paid', rideId: corrida.rideId);
    expect(pago.data['amount_cents'], cotacao.priceCents);
    final noEstado = (await passageiro.state()).ride!;
    expect((noEstado.payWithBalance, noEstado.pixPaid, noEstado.pay), (true, true, null));
    await ana.espera('rider_accepted', rideId: corrida.rideId);

    await viajar(corrida.rideId);
    final restante = 2000 - cotacao.priceCents;
    expect((await passageiro.state()).balanceCents, restante);

    final saque = await passageiro.withdraw(amountCents: 1000, pixKey: '529.982.247-25');
    expect((saque.amountCents, saque.balanceCents, saque.key), (1000, restante - 1000, 'final 4725'));
    await ana.espera('withdrawal_done');
    await expectLater(
      passageiro.withdraw(amountCents: 100, pixKey: '529.982.247-25'),
      throwsA(isA<ApiException>().having((e) => e.code, 'code', 'invalid')),
    );
    await expectLater(
      passageiro.withdraw(amountCents: 1000, pixKey: 'chave-que-nao-existe'),
      throwsA(isA<ApiException>().having((e) => e.code, 'code', 'invalid')),
    );
  });

  test('6. cancelar de graça e cotação já usada', () async {
    await motoqueiro.sendPosition(motoPerto.lat, motoPerto.lng);
    final cotacao = await passageiro.quote(origem, destino);
    final corrida = await passageiro.requestRide(quoteId: cotacao.quoteId, method: 'cash');
    await expectLater(
      passageiro.requestRide(quoteId: cotacao.quoteId, method: 'cash'),
      throwsA(isA<ApiException>().having((e) => e.code, 'code', 'quote_expired')),
    );
    await joao.espera('offer', rideId: corrida.rideId);
    await motoqueiro.accept(corrida.rideId);
    await ana.espera('rider_accepted', rideId: corrida.rideId);
    final cancelada = await passageiro.cancel(corrida.rideId);
    expect((cancelada.feeCents, cancelada.refund, cancelada.fee, cancelada.refundTo), (0, false, null, null));
    final aviso = await joao.espera('ride_cancelled', rideId: corrida.rideId);
    expect(aviso.data['by'], 'passenger');
    expect((await passageiro.state()).ride, isNull);
    expect((await motoqueiro.state()).ride, isNull);
  });

  test('7. corrida em dinheiro, dívida da taxa e voltar a ficar disponível', () async {
    final rideId = await pedirEAceitar('cash');
    await viajar(rideId);
    final aReceber = (await motoqueiro.state()).awaitingPayment!;
    expect((aReceber.rideId, aReceber.method), (rideId, 'cash'));
    await motoqueiro.cashReceived(rideId);
    await ana.espera('payment_confirmed', rideId: rideId);
    await passageiro.rate(rideId, 5);

    final bloqueado = await motoqueiro.state();
    expect(bloqueado.account!.blockedReason, 'debt_pending');
    expect(bloqueado.account!.debtToPayCents, greaterThan(0));
    expect(bloqueado.registration.online, isFalse);
    await expectLater(motoqueiro.goOnline(), throwsA(isA<ApiException>().having((e) => e.code, 'code', 'debt_pending')));

    final divida = await motoqueiro.debtCharge();
    expect(divida.amountCents, bloqueado.account!.debtToPayCents);
    await pagarNoDev(joao, divida.chargeId);
    await joao.espera('debt_paid');
    expect((await motoqueiro.state()).account!.cashDebtCents, 0);
    await motoqueiro.goOnline();
    expect((await motoqueiro.state()).registration.online, isTrue);
  });

  test('8. sair: a sessão deixa de valer', () async {
    await ana.auth.logout();
    expect(ana.api.token, isNull);
    final antigo = ApiClient(baseUrl: Uri.parse(url!))..token = ana.entrada.session.token;
    await expectLater(
      PassengerApi(antigo).state(),
      throwsA(isA<ApiException>().having((e) => e.status, 'status', 401)),
    );
    expect(antigo.token, isNull);
  });
}
