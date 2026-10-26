package org.edumeeting.llamadas

import androidx.datastore.preferences.core.PreferenceDataStoreFactory
import java.io.File
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.cancelAndJoin
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.runBlocking
import org.junit.Assert.*
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder

class DialPreferencesTest {
    @get:Rule
    val folder = TemporaryFolder()

    @Test
    fun defaultsAndSettingsPersistAcrossStoreRecreation() = runBlocking {
        val file = File(folder.root, "settings.preferences_pb")
        val firstJob = SupervisorJob()
        val firstScope = CoroutineScope(Dispatchers.IO + firstJob)
        val firstStore = PreferenceDataStoreFactory.create(scope = firstScope) { file }
        try {
            val preferences = DialPreferences(firstStore)
            assertEquals(DialSettings(null, "https://"), preferences.load())
            preferences.setDarkMode(true)
            preferences.setServerUrl("https://meeting.example.test/")
            assertEquals(DialSettings(true, "https://meeting.example.test"), preferences.load())
        } finally {
            firstJob.cancelAndJoin()
        }
        val secondScope = CoroutineScope(Dispatchers.IO + SupervisorJob())
        val secondStore = PreferenceDataStoreFactory.create(scope = secondScope) { file }
        try {
            val preferences = DialPreferences(secondStore)
            assertEquals(DialSettings(true, "https://meeting.example.test"), preferences.load())
            preferences.setDarkMode(false)
            assertEquals(DialSettings(false, "https://meeting.example.test"), preferences.load())
            assertEquals(setOf("dark_mode", "server_url"), secondStore.data.first().asMap().keys.map { it.name }.toSet())
        } finally {
            secondScope.cancel()
        }
    }
}
