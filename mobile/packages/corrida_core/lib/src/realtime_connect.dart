// Escolhe a conexão WebSocket certa para a plataforma: celular/computador (dart:io, com ping do protocolo) ou
// navegador (o navegador cuida do protocolo sozinho e não deixa o app mexer no ping).
export 'realtime_connect_io.dart'
    if (dart.library.js_interop) 'realtime_connect_web.dart';
