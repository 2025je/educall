plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("org.jetbrains.kotlin.plugin.compose")
}

// Firma de release estable: variables de entorno (CI) o propiedades de Gradle (~/.gradle/gradle.properties).
fun signingValue(environment: String, property: String): String? =
    providers.environmentVariable(environment).orElse(providers.gradleProperty(property)).orNull?.takeIf { it.isNotBlank() }

val releaseKeystore = signingValue("EDUMEETING_KEYSTORE_FILE", "edumeeting.keystore.file")
val appVersionCode = providers.gradleProperty("versionCode").orNull?.toIntOrNull() ?: 1
val appVersionName = providers.gradleProperty("versionName").orNull?.takeIf { it.isNotBlank() } ?: "1.0.0"

android {
    namespace = "org.edumeeting.llamadas"
    compileSdk = 35

    defaultConfig {
        applicationId = "org.edumeeting.llamadas"
        minSdk = 28
        targetSdk = 35
        versionCode = appVersionCode
        versionName = appVersionName
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

    buildFeatures { compose = true }
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
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.10.1")
    implementation("androidx.datastore:datastore-preferences:1.1.4")
    implementation("com.squareup.retrofit2:retrofit:2.11.0")
    implementation("com.squareup.okhttp3:okhttp-urlconnection:4.12.0")
    testImplementation("junit:junit:4.13.2")
    testImplementation("org.json:json:20240303")
    testImplementation("com.squareup.okhttp3:mockwebserver:4.12.0")
    testImplementation("com.squareup.okhttp3:okhttp-tls:4.12.0")
    debugImplementation("androidx.compose.ui:ui-tooling")
}
