package org.edumeeting.ui

import androidx.compose.material3.SnackbarDuration
import androidx.datastore.preferences.core.PreferenceDataStoreFactory
import java.io.File
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder

class ThemePreferencesTest {
    @get:Rule
    val folder = TemporaryFolder()

    private fun <T> withPreferences(block: suspend (ThemePreferences) -> T): T {
        val scope = CoroutineScope(Dispatchers.IO + SupervisorJob())
        val store = PreferenceDataStoreFactory.create(scope = scope) { File(folder.root, "appearance.preferences_pb") }
        return try {
            runBlocking { block(ThemePreferences(store)) }
        } finally {
            scope.cancel()
        }
    }

    @Test
    fun defaultsToSystemAndPersistsChoice() = withPreferences { preferences ->
        assertEquals(ThemeMode.System, preferences.mode.first())
        preferences.setMode(ThemeMode.Dark)
        assertEquals(ThemeMode.Dark, preferences.mode.first())
    }

    @Test
    fun legacyChoiceIsAdoptedOnlyWhenNothingIsSaved() = withPreferences { preferences ->
        preferences.adoptLegacy(ThemeMode.Dark)
        assertEquals(ThemeMode.Dark, preferences.mode.first())
        preferences.setMode(ThemeMode.Light)
        preferences.adoptLegacy(ThemeMode.Dark)
        assertEquals(ThemeMode.Light, preferences.mode.first())
    }

    @Test
    fun unknownKeysFallBackToSystem() {
        assertEquals(ThemeMode.System, ThemeMode.fromKey("sepia"))
        assertEquals(ThemeMode.System, ThemeMode.fromKey(null))
        assertEquals(ThemeMode.Light, ThemeMode.fromKey("light"))
    }

    @Test
    fun errorsAndWarningsStayUntilDismissed() {
        assertEquals(SnackbarDuration.Indefinite, NoticeVisuals("x", AdmonitionKind.Danger).duration)
        assertEquals(SnackbarDuration.Indefinite, NoticeVisuals("x", AdmonitionKind.Warning).duration)
        assertEquals(SnackbarDuration.Short, NoticeVisuals("x", AdmonitionKind.Success).duration)
    }
}
