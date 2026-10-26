package org.edumeeting.llamadas

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.IntrinsicSize
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.LocalMinimumInteractiveComponentSize
import androidx.compose.material3.Typography
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Shapes
import androidx.compose.material3.SnackbarDuration
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.SnackbarVisuals
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.unit.sp
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp

/** Superficies neutras y acentos índigo inspirados en Zensical. */
private val DialLight = lightColorScheme(
    primary = Color(0xFF526CFE),
    onPrimary = Color.White,
    primaryContainer = Color(0xFFE8EAF6),
    onPrimaryContainer = Color(0xFF1A237E),
    secondary = Color(0xFF4051B5),
    onSecondary = Color.White,
    background = Color.White,
    onBackground = Color(0xDE000000),
    surface = Color.White,
    onSurface = Color(0xDE000000),
    surfaceVariant = Color(0xFFF5F5F7),
    onSurfaceVariant = Color(0x8C000000),
    outline = Color(0x1F000000),
    outlineVariant = Color(0x14000000),
    error = Color(0xFFD32F2F),
    surfaceContainerLowest = Color.White,
    surfaceContainerLow = Color(0xFFFAFAFA),
    surfaceContainer = Color(0xFFF7F7FA),
    surfaceContainerHigh = Color(0xFFF5F6FA),
    surfaceContainerHighest = Color(0xFFF2F3F8),
)

private val DialDark = darkColorScheme(
    primary = Color(0xFF7B8CFF),
    onPrimary = Color(0xFF10132B),
    primaryContainer = Color(0xFF3C4B9E),
    onPrimaryContainer = Color.White,
    secondary = Color(0xFF7B8CFF),
    onSecondary = Color(0xFF10132B),
    background = Color(0xFF0B0C0F),
    onBackground = Color(0xD1E2E4E9),
    surface = Color(0xFF0B0C0F),
    onSurface = Color(0xD1E2E4E9),
    surfaceVariant = Color(0xFF14161D),
    onSurfaceVariant = Color(0x8FE2E4E9),
    outline = Color(0x1FE2E4E9),
    outlineVariant = Color(0x1FE2E4E9),
    error = Color(0xFFFF6E6E),
    surfaceContainerLowest = Color(0xFF14161D),
    surfaceContainerLow = Color(0xFF14161D),
    surfaceContainer = Color(0xFF14161D),
    surfaceContainerHigh = Color(0xFF14161D),
    surfaceContainerHighest = Color(0xFF14161D),
)

private val DialShapes = Shapes(
    extraSmall = RoundedCornerShape(12.dp),
    small = RoundedCornerShape(12.dp),
    medium = RoundedCornerShape(12.dp),
    large = RoundedCornerShape(12.dp),
    extraLarge = RoundedCornerShape(12.dp),
)

@Composable
internal fun DialTheme(dark: Boolean, content: @Composable () -> Unit) {
    CompositionLocalProvider(LocalMinimumInteractiveComponentSize provides 48.dp) {
        MaterialTheme(
            colorScheme = if (dark) DialDark else DialLight,
            shapes = DialShapes,
            typography = Typography(
                headlineLarge = TextStyle(fontSize = 28.sp, lineHeight = 34.sp, fontWeight = FontWeight.Bold, letterSpacing = (-0.5).sp),
                headlineSmall = TextStyle(fontSize = 24.sp, lineHeight = 30.sp, fontWeight = FontWeight.Bold),
                titleLarge = TextStyle(fontSize = 21.sp, lineHeight = 28.sp, fontWeight = FontWeight.Bold),
                titleMedium = TextStyle(fontSize = 17.sp, lineHeight = 24.sp, fontWeight = FontWeight.Bold),
                bodyLarge = TextStyle(fontSize = 15.sp, lineHeight = 24.sp),
                bodyMedium = TextStyle(fontSize = 15.sp, lineHeight = 22.sp),
            ),
            content = content,
        )
    }
}

internal enum class AdmonitionKind(val color: Color, val glyph: String, val title: String) {
    Note(Color(0xFF448AFF), "✎", "Nota"),
    Info(Color(0xFF00B8D4), "ℹ", "Información"),
    Success(Color(0xFF00A86B), "✓", "Listo"),
    Warning(Color(0xFFFF9100), "⚠", "Atención"),
    Danger(Color(0xFFD32F2F), "✕", "Error"),
    Example(Color(0xFF7C4DFF), "≡", "Ejemplo"),
}

/** Aviso flotante inferior: visible aunque la lista esté desplazada. Los errores esperan a "Cerrar". */
internal class NoticeVisuals(override val message: String, val kind: AdmonitionKind) : SnackbarVisuals {
    override val actionLabel: String = "Cerrar"
    override val withDismissAction: Boolean = false
    override val duration: SnackbarDuration =
        if (kind == AdmonitionKind.Danger || kind == AdmonitionKind.Warning) SnackbarDuration.Indefinite
        else SnackbarDuration.Short
}

internal suspend fun SnackbarHostState.showNotice(message: String, kind: AdmonitionKind) {
    val current = currentSnackbarData
    if (current != null && current.visuals.message == message) return
    current?.dismiss()
    showSnackbar(NoticeVisuals(message, kind))
}

@Composable
internal fun NoticeSnackbarHost(state: SnackbarHostState, modifier: Modifier = Modifier) {
    SnackbarHost(state, modifier.navigationBarsPadding()) { data ->
        val kind = (data.visuals as? NoticeVisuals)?.kind ?: AdmonitionKind.Info
        Surface(
            modifier = Modifier.fillMaxWidth().padding(horizontal = 12.dp, vertical = 8.dp),
            shape = RoundedCornerShape(12.dp),
            color = MaterialTheme.colorScheme.surface,
            contentColor = MaterialTheme.colorScheme.onSurface,
            border = BorderStroke(1.dp, kind.color),
            shadowElevation = 8.dp,
        ) {
            Row(Modifier.height(IntrinsicSize.Min).background(kind.color.copy(alpha = 0.10f))) {
                Surface(color = kind.color, modifier = Modifier.width(5.dp).fillMaxHeight()) {}
                Column(Modifier.weight(1f).padding(start = 12.dp, top = 10.dp, bottom = 10.dp)) {
                    Text("${kind.glyph}  ${kind.title}", fontWeight = FontWeight.Bold, color = kind.color)
                    Text(data.visuals.message, style = MaterialTheme.typography.bodyMedium)
                }
                TextButton(onClick = { data.dismiss() }, modifier = Modifier.align(Alignment.CenterVertically)) {
                    Text("Cerrar")
                }
            }
        }
    }
}

/** Aviso contextual: borde izquierdo de color, título tintado y contenido. */
@Composable
internal fun Admonition(
    kind: AdmonitionKind,
    title: String,
    modifier: Modifier = Modifier,
    content: @Composable () -> Unit = {},
) {
    val shape = RoundedCornerShape(12.dp)
    Row(
        modifier
            .fillMaxWidth()
            .height(IntrinsicSize.Min)
            .clip(shape)
            .border(BorderStroke(1.dp, kind.color.copy(alpha = 0.35f)), shape)
            .background(MaterialTheme.colorScheme.surface),
    ) {
        Surface(color = kind.color, modifier = Modifier.width(4.dp).fillMaxHeight()) {}
        Column(Modifier.fillMaxWidth()) {
            Row(
                Modifier.fillMaxWidth().background(kind.color.copy(alpha = 0.1f)).padding(horizontal = 12.dp, vertical = 8.dp),
                horizontalArrangement = Arrangement.spacedBy(8.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text(kind.glyph, color = kind.color, fontWeight = FontWeight.Bold)
                Text(title, fontWeight = FontWeight.Bold, style = MaterialTheme.typography.bodyMedium)
            }
            Column(Modifier.padding(horizontal = 12.dp, vertical = 8.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                content()
            }
        }
    }
}

/** Sección de formulario con borde discreto y título destacado. */
@Composable
internal fun DocSection(
    title: String,
    modifier: Modifier = Modifier,
    content: @Composable () -> Unit,
) {
    Column(
        modifier
            .fillMaxWidth()
            .border(1.dp, MaterialTheme.colorScheme.outline, RoundedCornerShape(12.dp))
            .padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        Text(title, style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold)
        content()
    }
}

@Composable
internal fun CodeText(text: String, modifier: Modifier = Modifier) {
    Text(
        text,
        modifier
            .clip(RoundedCornerShape(12.dp))
            .background(MaterialTheme.colorScheme.surfaceVariant)
            .padding(horizontal = 8.dp, vertical = 4.dp),
        fontFamily = FontFamily.Monospace,
        style = MaterialTheme.typography.titleMedium,
    )
}
