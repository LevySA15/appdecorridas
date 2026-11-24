import 'package:web_socket_channel/html.dart';
import 'package:web_socket_channel/web_socket_channel.dart';

/// Conexão padrão no navegador (só para conferir as telas no Chrome): o navegador não deixa configurar o ping.
WebSocketChannel connectDefault(
  Uri uri, {
  required Duration pingEvery,
  required Duration connectTimeout,
}) => HtmlWebSocketChannel.connect(uri);
