package org.edumeeting.ui

import android.content.Context
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.platform.LocalContext
import androidx.datastore.core.DataStore
import androidx.datastore.preferences.SharedPreferencesMigration
import androidx.datastore.preferences.core.Preferences
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.stringPreferencesKey
import androidx.datastore.preferences.preferencesDataStore
import java.io.IOException
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.launch

enum class ThemeMode(val key: String) {
    System("system"),
    Light("light"),
    Dark("dark");

    companion object {
        fun fromKey(value: String?): ThemeMode = entries.firstOrNull { it.key == value } ?: System
    }
}

private val Context.appearanceStore by preferencesDataStore(
    name = "appearance",
    produceMigrations = { context -> listOf(SharedPreferencesMigration(context, "appearance")) },
)
private val themeKey = stringPreferencesKey("theme")

/** Tema elegido por el usuario, guardado con DataStore en el archivo «appearance» de cada app. */
class ThemePreferences(private val store: DataStore<Preferences>) {
    constructor(context: Context) : this(context.applicationContext.appearanceStore)

    val mode: Flow<ThemeMode> = store.data.map { ThemeMode.fromKey(it[themeKey]) }

    suspend fun setMode(mode: ThemeMode) {
        store.edit { it[themeKey] = mode.key }
    }

    /** Adopta la preferencia guardada por una versión anterior de la app solo si aún no hay ninguna. */
    suspend fun adoptLegacy(mode: ThemeMode) {
        store.edit { if (themeKey !in it) it[themeKey] = mode.key }
    }
}

/** Estado de apariencia compartido con la interfaz. */
class ThemeState(
    val dark: Boolean,
    val followsSystem: Boolean,
    val toggle: () -> Unit,
    val followSystem: () -> Unit,
)

/** Tema EduMeeting que recuerda la elección del usuario (claro, oscuro o según el sistema). */
@Composable
fun EduMeetingTheme(content: @Composable (ThemeState) -> Unit) {
    val context = LocalContext.current
    val preferences = remember { ThemePreferences(context) }
    EduMeetingTheme(preferences, content)
}

@Composable
fun EduMeetingTheme(preferences: ThemePreferences, content: @Composable (ThemeState) -> Unit) {
    val scope = rememberCoroutineScope()
    var mode by remember { mutableStateOf(ThemeMode.System) }
    var loaded by remember { mutableStateOf(false) }
    var preferenceError by remember { mutableStateOf<String?>(null) }
    LaunchedEffect(preferences) {
        try {
            preferences.mode.collect {
                mode = it
                loaded = true
            }
        } catch (error: IOException) {
            preferenceError = "No se pudo leer el tema: ${error.message}"
            loaded = true
        }
    }
    val dark = when (mode) {
        ThemeMode.Dark -> true
        ThemeMode.Light -> false
        ThemeMode.System -> isSystemInDarkTheme()
    }
    fun save(value: ThemeMode) {
        if (!loaded) return
        scope.launch {
            try {
                preferences.setMode(value)
                mode = value
            } catch (error: IOException) {
                preferenceError = "No se pudo guardar el tema: ${error.message}"
            }
        }
    }
    EduMeetingTheme(dark = dark) {
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
                followsSystem = mode == ThemeMode.System,
                toggle = { save(if (dark) ThemeMode.Light else ThemeMode.Dark) },
                followSystem = { save(ThemeMode.System) },
            )
        )
    }
}
