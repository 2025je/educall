package org.edumeeting.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Check
import androidx.compose.material.icons.filled.Person
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onRoot
import androidx.compose.ui.unit.dp
import com.github.takahirom.roborazzi.captureRoboImage
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import org.robolectric.annotation.GraphicsMode

/**
 * Capturas de los componentes compartidos en tema claro y oscuro. Detectan cambios visuales
 * involuntarios en ambas apps: `SCREENSHOTS=record` regenera las referencias y `verify` las compara.
 */
@RunWith(RobolectricTestRunner::class)
@GraphicsMode(GraphicsMode.Mode.NATIVE)
@Config(sdk = [34], qualifiers = "w360dp-h900dp-xhdpi")
class ComponentsScreenshotTest {
    @get:Rule
    val compose = createComposeRule()

    private fun capture(name: String, dark: Boolean, content: @Composable () -> Unit) {
        compose.setContent {
            EduMeetingTheme(dark = dark) {
                Surface(color = MaterialTheme.colorScheme.background) {
                    Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) { content() }
                }
            }
        }
        compose.onRoot().captureRoboImage("src/test/screenshots/${name}_${if (dark) "dark" else "light"}.png")
    }

    @Composable
    private fun Admonitions() {
        AdmonitionKind.entries.forEach { Admonition("Mensaje de ejemplo para ${it.title.lowercase()}.", it) }
    }

    @Composable
    private fun Controls() {
        ScreenHeader("Registrar asistencia", "Busca por nombre, teléfono o código.")
        SectionHeading("Formulario")
        FormTextField("Ana Pérez", {}, "Nombre", leadingIcon = Icons.Default.Person, clearable = true)
        PasswordField("secreto", {})
        PinField("1234", {}, label = "PIN de la reunión", isError = true, supportingText = "El PIN no coincide.")
        PrimaryButton("Guardar", Icons.Default.Check, {})
        SecondaryButton("Cancelar", null, {})
        Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            StatCard(Icons.Default.Person, "120", "Invitados", Modifier.weight(1f))
            StatCard(Icons.Default.Check, "87", "Asistencias", Modifier.weight(1f))
        }
    }

    @Test fun admonitionsLight() = capture("admonitions", dark = false) { Admonitions() }

    @Test fun admonitionsDark() = capture("admonitions", dark = true) { Admonitions() }

    @Test fun controlsLight() = capture("controls", dark = false) { Controls() }

    @Test fun controlsDark() = capture("controls", dark = true) { Controls() }
}