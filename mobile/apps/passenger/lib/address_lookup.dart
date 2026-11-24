import 'dart:async';
import 'dart:convert';

import 'package:corrida_core/corrida_core.dart';
import 'package:http/http.dart' as http;

/// Descobre o endereço escrito de um ponto do mapa ("Avenida Barros e Almeida - São Cristóvão"), para o motoqueiro, o recibo e o
/// painel mostrarem rua em vez de coordenadas. Quando não consegue, devolve `null` e o app segue sem endereço (nunca trava o pedido).
abstract class AddressLookup {
  Future<String?> describe(Place place);
}

/// Monta a frase curta a partir da resposta do Nominatim (`/reverse?format=jsonv2`). Testável sem rede.
String? addressFromNominatim(Map<String, Object?> json) {
  final raw = json['address'];
  final address = raw is Map ? raw : const <String, Object?>{};
  String? pick(List<String> keys) {
    for (final key in keys) {
      final value = address[key];
      if (value is String && value.trim().isNotEmpty) return value.trim();
    }
    return null;
  }

  final road = pick(['road', 'pedestrian', 'footway', 'path', 'residential']);
  final number = pick(['house_number']);
  final area = pick([
    'suburb',
    'neighbourhood',
    'quarter',
    'city_district',
    'village',
  ]);
  final name =
      json['name'] is String && (json['name'] as String).trim().isNotEmpty
      ? (json['name'] as String).trim()
      : null;
  final street = road == null
      ? null
      : (number == null ? road : '$road, $number');
  final main = street ?? name;
  final parts = <String>[?main, if (area != null && area != main) area];
  if (parts.isEmpty) {
    final display = json['display_name'];
    if (display is String && display.trim().isNotEmpty) {
      return display.split(',').take(2).map((p) => p.trim()).join(' - ');
    }
    return null;
  }
  return parts.join(' - ');
}

/// Nominatim, o serviço de endereços do OpenStreetMap. **Uso leve** (a política deles pede no máximo uma consulta por segundo
/// e identificação do app): serve ao teste fechado, uma consulta por ponto marcado. As coordenadas do ponto vão para o servidor
/// deles (aviso na política de privacidade). Antes de abrir ao público, trocar por um provedor com contrato.
class NominatimAddressLookup implements AddressLookup {
  NominatimAddressLookup({
    http.Client? client,
    this.timeout = const Duration(seconds: 4),
  }) : _client = client ?? http.Client();

  final http.Client _client;
  final Duration timeout;
  DateTime _last = DateTime.fromMillisecondsSinceEpoch(0);

  @override
  Future<String?> describe(Place place) async {
    // no máximo uma consulta por segundo
    final wait =
        const Duration(milliseconds: 1100) - DateTime.now().difference(_last);
    if (wait > Duration.zero) await Future<void>.delayed(wait);
    _last = DateTime.now();
    try {
      final uri = Uri.https('nominatim.openstreetmap.org', '/reverse', {
        'format': 'jsonv2',
        'lat': place.lat.toStringAsFixed(6),
        'lon': place.lng.toStringAsFixed(6),
        'zoom': '18',
        'accept-language': 'pt-BR',
      });
      final response = await _client
          .get(
            uri,
            headers: {'User-Agent': 'br.com.reconcavo.corrida (teste fechado)'},
          )
          .timeout(timeout);
      if (response.statusCode != 200) return null;
      final body = jsonDecode(utf8.decode(response.bodyBytes));
      if (body is! Map<String, Object?>) return null;
      return addressFromNominatim(body);
    } on Object {
      return null; // sem internet, lento, resposta estranha: segue sem endereço
    }
  }
}
