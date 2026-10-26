package org.edumeeting.ui

import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.compositeOver
import androidx.compose.ui.graphics.luminance
import org.junit.Assert.assertTrue
import org.junit.Test

/** El texto de los avisos debe cumplir WCAG AA (4.5:1) sobre su fondo en ambos temas. */
class ContrastTest {
    private fun contrast(a: Color, b: Color): Double {
        val la = a.luminance() + 0.05
        val lb = b.luminance() + 0.05
        return (maxOf(la, lb) / minOf(la, lb)).toDouble()
    }

    private fun assertReadable(kind: AdmonitionKind, text: Color, surface: Color, theme: String) {
        // Fondo real: acento al 8 % (aviso) o al 10 % (aviso flotante) sobre la superficie.
        for (alpha in listOf(0.08f, 0.10f)) {
            val background = kind.color.copy(alpha = alpha).compositeOver(surface)
            val ratio = contrast(text, background)
            assertTrue("$kind ($theme, alpha $alpha) contraste $ratio < 4.5", ratio >= 4.5)
        }
    }

    @Test
    fun admonitionTitlesAreReadableInLightTheme() {
        AdmonitionKind.entries.forEach { assertReadable(it, it.lightText, Color.White, "claro") }
    }

    @Test
    fun admonitionTitlesAreReadableInDarkTheme() {
        AdmonitionKind.entries.forEach { assertReadable(it, it.darkText, Color(0xFF0B0C0F), "oscuro") }
    }
}