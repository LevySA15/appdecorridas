import 'package:web_socket_channel/io.dart';
import 'package:web_socket_channel/web_socket_channel.dart';

/// Conexão padrão no celular: `IOWebSocketChannel` com ping do protocolo (ver [RealtimeClient]).
WebSocketChannel connectDefault(
  Uri uri, {
  required Duration pingEvery,
  required Duration connectTimeout,
}) => IOWebSocketChannel.connect(
  uri,
  pingInterval: pingEvery,
  connectTimeout: connectTimeout,
);
