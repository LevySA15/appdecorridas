import 'package:corrida_core/corrida_core.dart';
import 'package:image_picker/image_picker.dart';

/// Uma foto já lida: os bytes crus e o tipo que o servidor espera (`image/jpeg`, `image/png`, `image/webp`).
class Photo {
  const Photo({required this.bytes, required this.contentType});

  final List<int> bytes;
  final String contentType;
}

/// De onde vêm as fotos do cadastro. Devolve `null` quando a pessoa desiste.
abstract class PhotoSource {
  Future<Photo?> pick(DocKind kind);
}

/// O tipo da foto pela extensão do arquivo; o que não conhece vira `image/jpeg` (o que a câmera grava).
String contentTypeOf(String path) {
  final lower = path.toLowerCase();
  if (lower.endsWith('.png')) return 'image/png';
  if (lower.endsWith('.webp')) return 'image/webp';
  return 'image/jpeg';
}

/// Abre a câmera (a da frente para a selfie). Largura e qualidade limitadas deixam a foto bem abaixo
/// dos 8 MB que o servidor aceita.
class ImagePickerPhotoSource implements PhotoSource {
  ImagePickerPhotoSource([ImagePicker? picker])
    : _picker = picker ?? ImagePicker();

  final ImagePicker _picker;

  @override
  Future<Photo?> pick(DocKind kind) async {
    final file = await _picker.pickImage(
      source: ImageSource.camera,
      preferredCameraDevice: kind == DocKind.selfie
          ? CameraDevice.front
          : CameraDevice.rear,
      maxWidth: 1600,
      imageQuality: 85,
    );
    if (file == null) return null;
    return Photo(
      bytes: await file.readAsBytes(),
      contentType: contentTypeOf(file.path),
    );
  }
}
