package org.edumeeting.ui

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.IntrinsicSize
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowForward
import androidx.compose.material.icons.automirrored.filled.List
import androidx.compose.material.icons.filled.CheckCircle
import androidx.compose.material.icons.filled.Edit
import androidx.compose.material.icons.filled.Info
import androidx.compose.material.icons.filled.Warning
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.SnackbarDuration
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.SnackbarVisuals
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.graphics.luminance
import androidx.compose.ui.semantics.LiveRegionMode
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.liveRegion
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp

/**
 * Tipos de aviso. [color] es el acento (barra, borde, icono); para texto se usan [lightText] y
 * [darkText], que cumplen contraste WCAG AA (4.5:1) sobre el fondo claro u oscuro del aviso.
 */
enum class AdmonitionKind(
    val title: String,
    val color: Color,
    val icon: ImageVector,
    val lightText: Color,
    val darkText: Color,
) {
    Note("Nota", Color(0xFF448AFF), Icons.Default.Edit, Color(0xFF1D4ED8), Color(0xFF7FADFF)),
    Info("Información", Color(0xFF00B8D4), Icons.Default.Info, Color(0xFF0E7490), Color(0xFF4DD8EE)),
    Success("Completado", Color(0xFF00A86B), Icons.Default.CheckCircle, Color(0xFF047857), Color(0xFF34D399)),
    Warning("Atención", Color(0xFFFF9100), Icons.Default.Warning, Color(0xFFB45309), Color(0xFFFFB04D)),
    Danger("Error", Color(0xFFD32F2F), Icons.Default.Warning, Color(0xFFB91C1C), Color(0xFFFF8A80)),
    Example("Ejemplo", Color(0xFF7C4DFF), Icons.AutoMirrored.Filled.List, Color(0xFF6D28D9), Color(0xFFB39DFF)),
}

/** Color de texto legible para el tipo de aviso según el tema activo. */
@Composable
fun AdmonitionKind.textColor(): Color =
    if (MaterialTheme.colorScheme.surface.luminance() > 0.5f) lightText else darkText

private val CardShape = RoundedCornerShape(12.dp)
private val AdmonitionShape = RoundedCornerShape(10.dp)

/** Aviso con el título del tipo (Nota, Atención…) y un mensaje corto. */
@Composable
fun Admonition(message: String, kind: AdmonitionKind = AdmonitionKind.Note) {
    // Sin controles dentro: TalkBack lee título y mensaje juntos.
    Admonition(kind, kind.title, Modifier.semantics(mergeDescendants = true) {}) {
        Text(message, style = MaterialTheme.typography.bodyMedium)
    }
}

/** Aviso con título propio y contenido libre (texto, botones, listas). */
@Composable
fun Admonition(
    kind: AdmonitionKind,
    title: String,
    modifier: Modifier = Modifier,
    content: @Composable () -> Unit = {},
) {
    Surface(
        modifier = modifier.fillMaxWidth(),
        shape = AdmonitionShape,
        color = kind.color.copy(alpha = 0.08f),
        contentColor = MaterialTheme.colorScheme.onSurface,
        border = BorderStroke(1.dp, kind.color.copy(alpha = 0.25f)),
    ) {
        Row(Modifier.height(IntrinsicSize.Min)) {
            Box(Modifier.width(4.dp).fillMaxHeight().background(kind.color))
            Row(Modifier.padding(12.dp), horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                Icon(kind.icon, contentDescription = null, tint = kind.color, modifier = Modifier.size(20.dp))
                Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
                    Text(title, fontWeight = FontWeight.Bold, color = kind.textColor(), style = MaterialTheme.typography.labelLarge)
                    content()
                }
            }
        }
    }
}

/** Sección de formulario con borde fino y título destacado. */
@Composable
fun DocSection(
    title: String,
    modifier: Modifier = Modifier,
    content: @Composable () -> Unit,
) {
    OutlinedPanel(modifier = modifier) {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            SectionHeading(title)
            content()
        }
    }
}

/** Texto monoespaciado sobre fondo neutro, para códigos y PIN. */
@Composable
fun CodeText(text: String, modifier: Modifier = Modifier) {
    Text(
        text,
        modifier
            .clip(RoundedCornerShape(8.dp))
            .background(MaterialTheme.colorScheme.surfaceVariant)
            .padding(horizontal = 8.dp, vertical = 4.dp),
        fontFamily = FontFamily.Monospace,
        style = MaterialTheme.typography.titleMedium,
    )
}

/** Icono ☀/☾ del botón que alterna entre tema claro y oscuro. */
@Composable
fun ThemeGlyph(dark: Boolean, contentDescription: String? = null) {
    Text(
        if (dark) "☀" else "☾",
        style = MaterialTheme.typography.titleLarge,
        modifier = if (contentDescription == null) Modifier else Modifier.semantics { this.contentDescription = contentDescription },
    )
}

/** Icono + texto para el contenido de un botón. */
@Composable
fun ActionLabel(text: String, icon: ImageVector) {
    Icon(icon, contentDescription = null, modifier = Modifier.size(20.dp))
    Spacer(Modifier.width(8.dp))
    Text(text)
}

@Composable
fun SectionHeading(title: String, modifier: Modifier = Modifier) {
    Text(
        title,
        modifier = modifier.semantics { heading() },
        style = MaterialTheme.typography.titleMedium,
        color = MaterialTheme.colorScheme.onSurface,
    )
}

@Composable
fun ScreenHeader(title: String, description: String) {
    Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
        Text(
            title,
            modifier = Modifier.semantics { heading() },
            style = MaterialTheme.typography.headlineMedium,
            color = MaterialTheme.colorScheme.onSurface,
        )
        Text(description, style = MaterialTheme.typography.bodyLarge, color = MaterialTheme.colorScheme.onSurfaceVariant)
    }
}

/** Círculo de color de acento con un icono, al estilo de las tarjetas de Zensical. */
@Composable
fun IconBadge(icon: ImageVector, size: Int = 36, tint: Color = MaterialTheme.colorScheme.primary) {
    Box(
        Modifier.size(size.dp).background(tint.copy(alpha = 0.12f), RoundedCornerShape(10.dp)),
        contentAlignment = Alignment.Center,
    ) {
        Icon(icon, contentDescription = null, tint = tint, modifier = Modifier.size((size * 0.56f).dp))
    }
}

@Composable
fun InitialsAvatar(name: String) {
    val initials = name.split(" ").filter { it.isNotBlank() }.take(2)
        .joinToString("") { it.first().uppercaseChar().toString() }.ifEmpty { "?" }
    Box(
        Modifier.size(40.dp).background(MaterialTheme.colorScheme.primary.copy(alpha = 0.14f), CircleShape),
        contentAlignment = Alignment.Center,
    ) {
        Text(initials, color = MaterialTheme.colorScheme.primary, fontWeight = FontWeight.Bold, style = MaterialTheme.typography.labelLarge)
    }
}

/** Tarjeta delineada de 12dp con borde fino. */
@Composable
fun OutlinedPanel(
    modifier: Modifier = Modifier,
    onClick: (() -> Unit)? = null,
    borderColor: Color = MaterialTheme.colorScheme.outline,
    containerColor: Color = MaterialTheme.colorScheme.surface,
    content: @Composable () -> Unit,
) {
    if (onClick != null) {
        Surface(
            onClick = onClick,
            modifier = modifier.fillMaxWidth(),
            shape = CardShape,
            color = containerColor,
            border = BorderStroke(1.dp, borderColor),
        ) { content() }
    } else {
        Surface(
            modifier = modifier.fillMaxWidth(),
            shape = CardShape,
            color = containerColor,
            border = BorderStroke(1.dp, borderColor),
        ) { content() }
    }
}

/** Tarjeta de cuadrícula: icono + título, divisor, descripción y acción en color de acento. */
@Composable
fun GridCard(
    icon: ImageVector,
    title: String,
    description: String,
    action: String,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
) {
    OutlinedPanel(modifier = modifier, onClick = onClick) {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                Icon(icon, contentDescription = null, tint = MaterialTheme.colorScheme.primary, modifier = Modifier.size(22.dp))
                Text(
                    title,
                    style = MaterialTheme.typography.titleSmall,
                    fontWeight = FontWeight.Bold,
                    maxLines = 2,
                    overflow = TextOverflow.Ellipsis,
                )
            }
            HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
            Text(
                description,
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                minLines = 3,
                maxLines = 3,
                overflow = TextOverflow.Ellipsis,
            )
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                Icon(
                    Icons.AutoMirrored.Filled.ArrowForward,
                    contentDescription = null,
                    tint = MaterialTheme.colorScheme.primary,
                    modifier = Modifier.size(16.dp),
                )
                Text(action, color = MaterialTheme.colorScheme.primary, style = MaterialTheme.typography.labelLarge)
            }
        }
    }
}

@Composable
fun StatCard(icon: ImageVector, value: String, label: String, modifier: Modifier = Modifier) {
    OutlinedPanel(modifier = modifier.semantics(mergeDescendants = true) {}, containerColor = MaterialTheme.colorScheme.surfaceVariant) {
        Column(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
            Icon(icon, contentDescription = null, tint = MaterialTheme.colorScheme.primary, modifier = Modifier.size(20.dp))
            Text(value, style = MaterialTheme.typography.headlineSmall, color = MaterialTheme.colorScheme.onSurface)
            Text(
                label,
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                minLines = 2,
                maxLines = 2,
            )
        }
    }
}

@Composable
fun EmptyState(
    icon: ImageVector,
    title: String,
    message: String,
    actionLabel: String? = null,
    actionIcon: ImageVector? = null,
    onAction: (() -> Unit)? = null,
    actionEnabled: Boolean = true,
) {
    Column(
        Modifier.fillMaxWidth().padding(vertical = 32.dp, horizontal = 8.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Box(
            Modifier.size(88.dp).background(MaterialTheme.colorScheme.primary.copy(alpha = 0.10f), CircleShape),
            contentAlignment = Alignment.Center,
        ) {
            Icon(icon, contentDescription = null, tint = MaterialTheme.colorScheme.primary, modifier = Modifier.size(44.dp))
        }
        Text(title, Modifier.semantics { heading() }, style = MaterialTheme.typography.titleLarge, textAlign = TextAlign.Center)
        Text(
            message,
            style = MaterialTheme.typography.bodyLarge,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            textAlign = TextAlign.Center,
        )
        if (actionLabel != null && onAction != null) {
            Spacer(Modifier.height(4.dp))
            PrimaryButton(actionLabel, actionIcon, onAction, enabled = actionEnabled)
        }
    }
}

private val ButtonShape = RoundedCornerShape(12.dp)
private val ButtonPadding = PaddingValues(horizontal = 20.dp, vertical = 12.dp)

@Composable
fun PrimaryButton(
    text: String,
    icon: ImageVector?,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    enabled: Boolean = true,
) {
    Button(
        onClick = onClick,
        modifier = modifier.heightIn(min = 48.dp),
        enabled = enabled,
        shape = ButtonShape,
        contentPadding = ButtonPadding,
        colors = ButtonDefaults.buttonColors(
            containerColor = MaterialTheme.colorScheme.primary,
            contentColor = MaterialTheme.colorScheme.onPrimary,
        ),
    ) {
        if (icon != null) {
            Icon(icon, contentDescription = null, modifier = Modifier.size(20.dp))
            Spacer(Modifier.width(8.dp))
        }
        Text(text)
    }
}

@Composable
fun SecondaryButton(
    text: String,
    icon: ImageVector?,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    enabled: Boolean = true,
) {
    OutlinedButton(
        onClick = onClick,
        modifier = modifier.heightIn(min = 48.dp),
        enabled = enabled,
        shape = ButtonShape,
        contentPadding = ButtonPadding,
        border = BorderStroke(1.dp, MaterialTheme.colorScheme.outline),
        colors = ButtonDefaults.outlinedButtonColors(contentColor = MaterialTheme.colorScheme.primary),
    ) {
        if (icon != null) {
            Icon(icon, contentDescription = null, modifier = Modifier.size(20.dp))
            Spacer(Modifier.width(8.dp))
        }
        Text(text)
    }
}

/** Aviso flotante en la parte inferior: siempre visible aunque la pantalla esté desplazada. */
class NoticeVisuals(override val message: String, val kind: AdmonitionKind) : SnackbarVisuals {
    override val actionLabel: String = "Cerrar"
    override val withDismissAction: Boolean = false
    override val duration: SnackbarDuration =
        if (kind == AdmonitionKind.Danger || kind == AdmonitionKind.Warning) SnackbarDuration.Indefinite
        else SnackbarDuration.Short
}

suspend fun SnackbarHostState.showNotice(message: String, kind: AdmonitionKind) {
    val current = currentSnackbarData
    if (current != null && current.visuals.message == message) return
    current?.dismiss()
    showSnackbar(NoticeVisuals(message, kind))
}

@Composable
fun NoticeSnackbarHost(state: SnackbarHostState, modifier: Modifier = Modifier) {
    SnackbarHost(state, modifier.navigationBarsPadding()) { data ->
        val kind = (data.visuals as? NoticeVisuals)?.kind ?: AdmonitionKind.Info
        Surface(
            // Region viva: TalkBack anuncia el aviso aunque el foco esté en otra parte de la pantalla.
            modifier = Modifier.fillMaxWidth().padding(horizontal = 12.dp, vertical = 8.dp).semantics {
                liveRegion = if (kind == AdmonitionKind.Danger || kind == AdmonitionKind.Warning) {
                    LiveRegionMode.Assertive
                } else {
                    LiveRegionMode.Polite
                }
            },
            shape = AdmonitionShape,
            color = MaterialTheme.colorScheme.surface,
            contentColor = MaterialTheme.colorScheme.onSurface,
            border = BorderStroke(1.dp, kind.color.copy(alpha = 0.6f)),
            shadowElevation = 8.dp,
        ) {
            Row(Modifier.height(IntrinsicSize.Min).background(kind.color.copy(alpha = 0.10f))) {
                Box(Modifier.width(5.dp).fillMaxHeight().background(kind.color))
                Icon(
                    kind.icon,
                    contentDescription = null,
                    tint = kind.color,
                    modifier = Modifier.padding(start = 12.dp, top = 12.dp).size(20.dp),
                )
                Column(Modifier.weight(1f).padding(start = 10.dp, top = 10.dp, bottom = 10.dp)) {
                    Text(kind.title, fontWeight = FontWeight.Bold, color = kind.textColor())
                    Text(data.visuals.message, style = MaterialTheme.typography.bodyMedium)
                }
                TextButton(
                    onClick = { data.dismiss() },
                    modifier = Modifier.align(Alignment.CenterVertically).heightIn(min = 48.dp),
                ) {
                    Text("Cerrar")
                }
            }
        }
    }
}
