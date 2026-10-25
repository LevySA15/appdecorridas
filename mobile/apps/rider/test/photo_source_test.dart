import 'package:flutter_test/flutter_test.dart';
import 'package:rider/photo_source.dart';

void main() {
  test('contentTypeOf reconhece as extensoes que o servidor aceita', () {
    expect(contentTypeOf('/tmp/a.jpg'), 'image/jpeg');
    expect(contentTypeOf('/tmp/A.JPEG'), 'image/jpeg');
    expect(contentTypeOf('x.png'), 'image/png');
    expect(contentTypeOf('y.webp'), 'image/webp');
  });

  test('contentTypeOf cai em jpeg para o que nao conhece', () {
    expect(contentTypeOf('sem_extensao'), 'image/jpeg');
    expect(contentTypeOf('foto.heic'), 'image/jpeg');
  });
}
