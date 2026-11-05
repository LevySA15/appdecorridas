import 'dart:async';
import 'dart:convert';

import 'package:corrida_core/corrida_core.dart';
import 'package:http/http.dart' as http;
import 'package:rider/location_source.dart';
import 'package:rider/screen_awake.dart';
import 'package:stream_channel/stream_channel.dart';
import 'package:web_socket_channel/web_socket_channel.dart';

http.Response json(Object? body, [int status = 200]) => http.Response.bytes(
  utf8.encode(jsonEncode(body)),
  status,
  headers: {'content-type': 'application/json; charset=utf-8'},
);

Future<void> deixaRodar() =>
    Future<void>.delayed(const Duration(milliseconds: 20));

class FakeSink implements WebSocketSink {
  var fechado = false;
  final _done = Completer<void>();

  @override
  void add(Object? data) {}

  @override
  void addError(Object error, [StackTrace? stackTrace]) {}

  @override
  Future<void> addStream(Stream<Object?> stream) => stream.drain();

  @override
  Future<void> close([int? closeCode, String? closeReason]) async {
    fechado = true;
    if (!_done.isCompleted) _done.complete();
  }

  @override
  Future<void> get done => _done.future;
}

class FakeChannel extends StreamChannelMixin<Object?>
    implements WebSocketChannel {
  FakeChannel(this.uri);

  final Uri uri;
  final _entrada = StreamController<Object?>();
  @override
  final FakeSink sink = FakeSink();
  @override
  int? closeCode;

  void servidorMandaAviso(
    String type, [
    Map<String, Object?>? data,
    double at = 1.0,
  ]) => _entrada.add(jsonEncode({'type': type, 'data': data, 'at': at}));

  @override
  Stream<Object?> get stream => _entrada.stream;

  @override
  Future<void> get ready => Future<void>.value();

  @override
  String? get protocol => null;

  @override
  String? get closeReason => null;
}

/// O estado de um motoqueiro que ainda não se cadastrou.
const Map<String, Object?> estadoNaoCadastrado = {
  'registration': {'status': 'not_registered'},
  'account': null,
  'offer': null,
  'ride': null,
  'queued_ride': null,
  'awaiting_payment': null,
};

/// GPS controlável: o teste decide a permissão, o que o GPS emite e confere quando foi ligado e desligado.
class FakeGps implements LocationSource {
  FakeGps({this.access = LocationAccess.granted});

  LocationAccess access;
  var requests = 0;
  var listens = 0;
  var cancels = 0;
  StreamController<Place>? _current;

  bool get listening => listens > cancels;

  @override
  Future<LocationAccess> request() async {
    requests++;
    return access;
  }

  @override
  Stream<Place> positions() {
    final controller = StreamController<Place>(
      onListen: () => listens++,
      onCancel: () => cancels++,
    );
    _current = controller;
    return controller.stream;
  }

  void emit(Place place) => _current!.add(place);

  void emitError(Object error) => _current!.addError(error);
}

/// Anota cada `keepOn` para o teste conferir quando a tela foi segurada e solta.
class FakeScreenAwake implements ScreenAwake {
  final calls = <bool>[];

  bool? get last => calls.isEmpty ? null : calls.last;

  @override
  Future<void> keepOn(bool on) async => calls.add(on);
}
