package org.edumeeting.llamadas

import android.content.Context
import androidx.datastore.core.DataStore
import androidx.datastore.preferences.core.Preferences
import androidx.datastore.preferences.SharedPreferencesMigration
import androidx.datastore.preferences.core.booleanPreferencesKey
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.stringPreferencesKey
import androidx.datastore.preferences.preferencesDataStore
import kotlinx.coroutines.flow.first

private val Context.dialPreferences by preferencesDataStore(
    name = "edumeeting_llamadas",
    produceMigrations = { context -> listOf(SharedPreferencesMigration(context, "edumeeting_llamadas_ui")) },
)

internal data class DialSettings(val darkMode: Boolean?, val serverUrl: String)

internal class DialPreferences(private val store: DataStore<Preferences>) {
    constructor(context: Context) : this(context.applicationContext.dialPreferences)
    private val darkModeKey = booleanPreferencesKey("dark_mode")
    private val serverUrlKey = stringPreferencesKey("server_url")

    suspend fun load(): DialSettings {
        val preferences = store.data.first()
        return DialSettings(preferences[darkModeKey], preferences[serverUrlKey] ?: "https://")
    }

    suspend fun setDarkMode(enabled: Boolean) {
        store.edit { it[darkModeKey] = enabled }
    }

    suspend fun setServerUrl(url: String) {
        store.edit { it[serverUrlKey] = url.trimEnd('/') }
    }
}
