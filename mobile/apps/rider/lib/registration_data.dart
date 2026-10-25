import 'package:corrida_core/corrida_core.dart';

import 'photo_source.dart';

/// O que o formulário de cadastro entrega ao controlador.
class RegistrationData {
  const RegistrationData({
    required this.name,
    required this.cpf,
    required this.cnhNumber,
    required this.plate,
    required this.motoModel,
    required this.cnhExpiresOn,
    required this.crlvExpiresOn,
    required this.photos,
  });

  final String name;
  final String cpf;
  final String cnhNumber;
  final String plate;
  final String motoModel;
  final DateTime cnhExpiresOn;
  final DateTime crlvExpiresOn;

  /// Precisa ter as três: selfie, CNH e documento da moto.
  final Map<DocKind, Photo> photos;
}
