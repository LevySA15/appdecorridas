import java.util.Base64

plugins {
    id("com.android.application")
    // The Flutter Gradle Plugin must be applied after the Android and Kotlin Gradle plugins.
    id("dev.flutter.flutter-gradle-plugin")
}

// A chave do Google Maps vem da mesma opção do Dart (`--dart-define=GOOGLE_MAPS_API_KEY=...` ou
// `--dart-define-from-file=chaves.json`; o Flutter entrega as opções ao Gradle em `dart-defines`, em base64) ou da variável
// de ambiente `GOOGLE_MAPS_API_KEY`. Sem chave o manifesto fica com valor vazio e só o mapa do Google não aparece.
val dartDefines: Map<String, String> =
    (project.findProperty("dart-defines") as String?)
        ?.split(",")
        ?.mapNotNull { encoded ->
            val pair = String(Base64.getDecoder().decode(encoded), Charsets.UTF_8).split("=", limit = 2)
            if (pair.size == 2) pair[0] to pair[1] else null
        }
        ?.toMap()
        ?: emptyMap()
val googleMapsApiKey: String =
    dartDefines["GOOGLE_MAPS_API_KEY"] ?: System.getenv("GOOGLE_MAPS_API_KEY") ?: ""

android {
    namespace = "com.reconcavo.rider"
    compileSdk = flutter.compileSdkVersion
    ndkVersion = flutter.ndkVersion

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    defaultConfig {
        // TODO: Specify your own unique Application ID (https://developer.android.com/studio/build/application-id.html).
        applicationId = "com.reconcavo.rider"
        // You can update the following values to match your application needs.
        // For more information, see: https://flutter.dev/to/review-gradle-config.
        minSdk = flutter.minSdkVersion
        targetSdk = flutter.targetSdkVersion
        // Uses the version code from pubspec.yaml. When using split APKs, 1000 * ABI_VERSION
        // is added automatically by Flutter. (https://developer.android.com/studio/build/configure-apk-splits#configure-APK-versions)
        // You can force using the value of versionCode by specifying the `-P force-version-code-ignoring-abi=true`
        // flag during build.
        versionCode = flutter.versionCode
        versionName = flutter.versionName
        manifestPlaceholders["GOOGLE_MAPS_API_KEY"] = googleMapsApiKey
    }

    buildTypes {
        release {
            // TODO: Add your own signing config for the release build.
            // Signing with the debug keys for now, so `flutter run --release` works.
            signingConfig = signingConfigs.getByName("debug")
        }
    }
}

kotlin {
    compilerOptions {
        jvmTarget = org.jetbrains.kotlin.gradle.dsl.JvmTarget.JVM_17
    }
}

flutter {
    source = "../.."
}
