import java.util.Base64

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("org.jetbrains.kotlin.plugin.compose")
    id("org.jetbrains.kotlin.plugin.serialization")
    id("com.google.devtools.ksp")
}

// Firma de release estable: variables de entorno (CI) o propiedades de Gradle (~/.gradle/gradle.properties).
fun signingValue(environment: String, property: String): String? =
    providers.environmentVariable(environment).orElse(providers.gradleProperty(property)).orNull?.takeIf { it.isNotBlank() }

val releaseKeystore = signingValue("EDUMEETING_KEYSTORE_FILE", "edumeeting.keystore.file")
val appVersionCode = providers.gradleProperty("versionCode").orNull?.toIntOrNull() ?: 1
val appVersionName = providers.gradleProperty("versionName").orNull?.takeIf { it.isNotBlank() } ?: "1.0.0"

android {
    namespace = "org.edumeeting.asistencia"
    compileSdk = 35

    defaultConfig {
        applicationId = "org.edumeeting.asistencia"
        minSdk = 28
        targetSdk = 35
        versionCode = appVersionCode
        versionName = appVersionName
        val pinnedKey = providers.gradleProperty("attendancePublicKey").orElse("").get()
        if (pinnedKey.isNotEmpty()) {
            require(
                runCatching { Base64.getDecoder().decode(pinnedKey).size == 32 }.getOrDefault(false)
            ) { "attendancePublicKey debe ser una clave publica Ed25519 de 32 bytes en Base64." }
        }
        buildConfigField("String", "ATTENDANCE_PUBLIC_KEY_BASE64", "\"$pinnedKey\"")
    }

    signingConfigs {
        if (releaseKeystore != null) {
            create("release") {
                storeFile = file(releaseKeystore)
                storePassword = signingValue("EDUMEETING_KEYSTORE_PASSWORD", "edumeeting.keystore.password")
                keyAlias = signingValue("EDUMEETING_KEY_ALIAS", "edumeeting.key.alias")
                keyPassword = signingValue("EDUMEETING_KEY_PASSWORD", "edumeeting.key.password")
            }
        }
    }

    buildTypes {
        release {
            // Sin keystore configurado se firma con la clave debug para poder probar el build localmente.
            signingConfig = signingConfigs.findByName("release") ?: signingConfigs.getByName("debug")
        }
    }

    buildFeatures { compose = true; buildConfig = true }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
}

kotlin { jvmToolchain(17) }

dependencies {
    implementation(project(":edumeeting-ui"))
    val composeBom = platform("androidx.compose:compose-bom:2025.03.00")
    implementation(composeBom)
    implementation("androidx.activity:activity-compose:1.10.1")
    implementation("androidx.core:core-ktx:1.15.0")
    implementation("androidx.compose.material3:material3")
    implementation("androidx.compose.material:material-icons-core")
    implementation("androidx.compose.ui:ui")
    implementation("androidx.compose.ui:ui-tooling-preview")
    implementation("androidx.lifecycle:lifecycle-runtime-compose:2.8.7")
    implementation("androidx.lifecycle:lifecycle-viewmodel-compose:2.8.7")
    implementation("androidx.room:room-runtime:2.7.0")
    implementation("androidx.room:room-ktx:2.7.0")
    ksp("androidx.room:room-compiler:2.7.0")
    implementation("androidx.datastore:datastore-preferences:1.1.4")
    implementation("org.jetbrains.kotlinx:kotlinx-serialization-json:1.8.0")
    implementation("androidx.camera:camera-camera2:1.4.2")
    implementation("androidx.camera:camera-lifecycle:1.4.2")
    implementation("androidx.camera:camera-view:1.4.2")
    implementation("com.google.mlkit:barcode-scanning:17.3.0")
    debugImplementation("androidx.compose.ui:ui-tooling")
    testImplementation("junit:junit:4.13.2")
}

ksp { arg("room.schemaLocation", "$projectDir/schemas") }
