package org.edumeeting.asistencia

import android.content.Context
import androidx.datastore.preferences.SharedPreferencesMigration
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.stringPreferencesKey
import androidx.datastore.preferences.preferencesDataStore
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.ColorScheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Shapes
import androidx.compose.material3.Typography
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import java.io.IOException
import kotlinx.coroutines.launch

private val Context.appearancePreferences by preferencesDataStore(
    name = "appearance",
    produceMigrations = { context -> listOf(SharedPreferencesMigration(context, "appearance")) },
)
private val themeKey = stringPreferencesKey("theme")

val BrandPrimary = Color(0xFF4051B5)
private val AccentLight = Color(0xFF526CFE)
private val AccentDark = Color(0xFF7B8CFF)

private val LightColors = lightColorScheme(
    primary = AccentLight,
    onPrimary = Color.White,
    primaryContainer = Color(0xFFE8ECFF),
    onPrimaryContainer = Color(0xFF243278),
    secondary = BrandPrimary,
    onSecondary = Color.White,
    secondaryContainer = Color(0xFFE8ECFF),
    onSecondaryContainer = Color(0xFF243278),
    tertiary = BrandPrimary,
    background = Color.White,
    onBackground = Color(0xDE000000),
    surface = Color.White,
    onSurface = Color(0xDE000000),
    surfaceVariant = Color(0xFFF5F5F7),
    onSurfaceVariant = Color(0x8C000000),
    surfaceTint = Color.Transparent,
    outline = Color(0x1F000000),
    outlineVariant = Color(0x14000000),
    surfaceContainerLowest = Color.White,
    surfaceContainerLow = Color.White,
    surfaceContainer = Color(0xFFF5F5F7),
    surfaceContainerHigh = Color.White,
    surfaceContainerHighest = Color(0xFFF5F5F7),
)

private val DarkColors = darkColorScheme(
    primary = AccentDark,
    onPrimary = Color(0xFF0B0C0F),
    primaryContainer = Color(0xFF242B57),
    onPrimaryContainer = Color(0xFFE0E4FF),
    secondary = AccentDark,
    onSecondary = Color(0xFF0B0C0F),
    secondaryContainer = Color(0xFF242B57),
    onSecondaryContainer = Color(0xFFE0E4FF),
    tertiary = AccentDark,
    background = Color(0xFF0B0C0F),
    onBackground = Color(0xD1E2E4E9),
    surface = Color(0xFF0B0C0F),
    onSurface = Color(0xD1E2E4E9),
    surfaceVariant = Color(0xFF14161D),
    onSurfaceVariant = Color(0x8FE2E4E9),
    surfaceTint = Color.Transparent,
    outline = Color(0x1FE2E4E9),
    outlineVariant = Color(0x1FE2E4E9),
    surfaceContainerLowest = Color(0xFF0B0C0F),
    surfaceContainerLow = Color(0xFF0B0C0F),
    surfaceContainer = Color(0xFF14161D),
    surfaceContainerHigh = Color(0xFF14161D),
    surfaceContainerHighest = Color(0xFF1B1E27),
)

private val ZensicalTypography = Typography().let { base ->
    base.copy(
        headlineLarge = base.headlineLarge.copy(fontSize = 32.sp, fontWeight = FontWeight.Bold, letterSpacing = (-0.5).sp),
        headlineMedium = TextStyle(fontSize = 28.sp, lineHeight = 34.sp, fontWeight = FontWeight.Bold, letterSpacing = (-0.5).sp),
        headlineSmall = base.headlineSmall.copy(fontSize = 22.sp, fontWeight = FontWeight.Bold, letterSpacing = (-0.25).sp),
        titleLarge = base.titleLarge.copy(fontWeight = FontWeight.Bold),
        titleMedium = base.titleMedium.copy(fontWeight = FontWeight.Bold),
        titleSmall = base.titleSmall.copy(fontWeight = FontWeight.SemiBold),
        bodyLarge = base.bodyLarge.copy(fontSize = 15.sp, lineHeight = 22.sp, letterSpacing = 0.sp),
        bodyMedium = base.bodyMedium.copy(fontSize = 14.sp, lineHeight = 20.sp, letterSpacing = 0.sp),
        labelLarge = base.labelLarge.copy(fontSize = 15.sp, fontWeight = FontWeight.SemiBold),
    )
}

private val ZensicalShapes = Shapes(
    extraSmall = RoundedCornerShape(6.dp),
    small = RoundedCornerShape(8.dp),
    medium = RoundedCornerShape(12.dp),
    large = RoundedCornerShape(16.dp),
    extraLarge = RoundedCornerShape(24.dp),
)

/** Estado de apariencia compartido con la interfaz. */
class ThemeState(
    val dark: Boolean,
    val followsSystem: Boolean,
    val toggle: () -> Unit,
    val followSystem: () -> Unit,
)

/** Color de acento para estados seleccionados, enlaces y botones principales. */
val ColorScheme.accent: Color get() = primary

@Composable
fun EduMeetingTheme(content: @Composable (ThemeState) -> Unit) {
    val context = LocalContext.current
    val preferences = remember { context.applicationContext.appearancePreferences }
    val scope = rememberCoroutineScope()
    var choice by remember { mutableStateOf("system") }
    var loaded by remember { mutableStateOf(false) }
    var preferenceError by remember { mutableStateOf<String?>(null) }
    LaunchedEffect(preferences) {
        try {
            preferences.data.collect {
                choice = it[themeKey] ?: "system"
                loaded = true
            }
        } catch (error: IOException) {
            preferenceError = "No se pudo leer el tema: ${error.message}"
            loaded = true
        }
    }
    val dark = when (choice) {
        "dark" -> true
        "light" -> false
        else -> isSystemInDarkTheme()
    }
    fun save(value: String) {
        if (!loaded) return
        scope.launch {
            try {
                preferences.edit { it[themeKey] = value }
                choice = value
            } catch (error: IOException) {
                preferenceError = "No se pudo guardar el tema: ${error.message}"
            }
        }
    }
    MaterialTheme(
        colorScheme = if (dark) DarkColors else LightColors,
        typography = ZensicalTypography,
        shapes = ZensicalShapes,
    ) {
        preferenceError?.let { message ->
            AlertDialog(
                onDismissRequest = { preferenceError = null },
                title = { Text("Preferencias") },
                text = { Text(message) },
                confirmButton = { TextButton(onClick = { preferenceError = null }) { Text("Aceptar") } },
            )
        }
        content(
            ThemeState(
                dark = dark,
                followsSystem = choice != "dark" && choice != "light",
                toggle = { save(if (dark) "light" else "dark") },
                followSystem = { save("system") },
            )
        )
    }
}
