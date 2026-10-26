plugins {
    id("com.android.library")
    id("org.jetbrains.kotlin.android")
    id("org.jetbrains.kotlin.plugin.compose")
}

// Cada app que incluye la librería la compila en su propia carpeta build: Llamadas y Asistencia no se pisan.
layout.buildDirectory.set(rootProject.layout.buildDirectory.dir("edumeeting-ui"))

android {
    namespace = "org.edumeeting.ui"
    compileSdk = 35

    defaultConfig { minSdk = 28 }

    buildFeatures { compose = true }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
}

kotlin { jvmToolchain(17) }

dependencies {
    val composeBom = platform("androidx.compose:compose-bom:2025.03.00")
    api(composeBom)
    api("androidx.compose.material3:material3")
    api("androidx.compose.material:material-icons-core")
    api("androidx.compose.ui:ui")
    api("androidx.datastore:datastore-preferences:1.1.4")
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.10.1")
    testImplementation("junit:junit:4.13.2")
}
