import 'package:url_launcher/url_launcher.dart';

/// O número da polícia. O servidor também devolve `emergency_number` no SOS, mas o discador abre antes de
/// a resposta chegar: numa emergência ninguém espera a rede.
const emergencyNumber = '190';

/// Abre o discador com o número preenchido; devolve se abriu.
typedef Dial = Future<bool> Function(String number);

Uri dialUri(String number) => Uri(scheme: 'tel', path: number);

/// Abre o discador do celular (a pessoa aperta "ligar": assim o app não precisa da permissão de ligações).
/// Nunca levanta erro: celular sem discador devolve `false`, e o SOS segue mesmo assim.
Future<bool> dialNumber(
  String number, {
  Future<bool> Function(Uri uri)? launch,
}) async {
  final open =
      launch ?? (Uri uri) => launchUrl(uri, mode: LaunchMode.externalApplication);
  try {
    return await open(dialUri(number));
  } on Object {
    return false;
  }
}
