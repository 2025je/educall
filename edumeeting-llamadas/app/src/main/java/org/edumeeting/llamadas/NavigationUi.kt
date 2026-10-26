package org.edumeeting.llamadas

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.List
import androidx.compose.material.icons.automirrored.filled.KeyboardArrowRight
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp

internal enum class DialDestination(val title: String, val icon: ImageVector, val description: String) {
    Home("Inicio", Icons.Default.Home, "Tu espacio de trabajo"),
    Meetings("Reuniones", Icons.Default.DateRange, "Elige la reunión en la que vas a trabajar"),
    Calls("Llamadas", Icons.Default.Call, "Atiende la siguiente persona de la cola"),
    Search("Buscar", Icons.Default.Search, "Encuentra participantes y prepara invitaciones"),
    Register("Registrar", Icons.Default.Person, "Agrega una persona a la reunión activa"),
    Assignments("Asignaciones y estadísticas", Icons.AutoMirrored.Filled.List, "Organiza tu equipo y consulta el progreso"),
    Manage("Gestionar reuniones", Icons.Default.Edit, "Crea y actualiza tus reuniones"),
}

@Composable
internal fun ActionLabel(text: String, icon: ImageVector) {
    Icon(icon, contentDescription = null, modifier = Modifier.size(20.dp))
    Spacer(Modifier.width(8.dp))
    Text(text)
}

@Composable
internal fun EmptyState(icon: ImageVector, title: String, description: String, action: @Composable () -> Unit = {}) {
    Column(
        Modifier.fillMaxWidth().padding(vertical = 24.dp, horizontal = 12.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Surface(shape = CircleShape, color = MaterialTheme.colorScheme.primary.copy(alpha = 0.10f)) {
            Icon(icon, null, Modifier.padding(20.dp).size(40.dp), tint = MaterialTheme.colorScheme.primary)
        }
        Text(title, style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold)
        Text(description, style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
        action()
    }
}

@Composable
internal fun WorkspaceHome(
    username: String,
    meeting: String,
    roles: List<String>,
    destinations: List<DialDestination>,
    navigate: (DialDestination) -> Unit,
) {
    Column(verticalArrangement = Arrangement.spacedBy(20.dp)) {
        Text("Hola, $username", style = MaterialTheme.typography.headlineLarge)
        Text("¿Qué quieres hacer hoy?", color = MaterialTheme.colorScheme.onSurfaceVariant)
        OutlinedCard(onClick = { navigate(DialDestination.Meetings) }, modifier = Modifier.fillMaxWidth()) {
            Row(Modifier.padding(16.dp), verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                Icon(Icons.Default.DateRange, null, tint = MaterialTheme.colorScheme.primary)
                Column(Modifier.weight(1f)) {
                    Text("Reunión activa", style = MaterialTheme.typography.labelLarge, color = MaterialTheme.colorScheme.onSurfaceVariant)
                    Text(meeting, style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)
                    Text("Usuario: $username", style = MaterialTheme.typography.bodySmall)
                }
                Icon(Icons.AutoMirrored.Filled.KeyboardArrowRight, "Cambiar reunión")
            }
        }
        RoleChips(roles)
        Text("Accesos rápidos", style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold)
        destinations.filter { it != DialDestination.Home }.chunked(2).forEach { row ->
            Row(horizontalArrangement = Arrangement.spacedBy(12.dp), modifier = Modifier.height(IntrinsicSize.Min)) {
                row.forEach { destination ->
                    OutlinedCard(
                        onClick = { navigate(destination) },
                        modifier = Modifier.weight(1f).fillMaxHeight(),
                        border = BorderStroke(1.dp, MaterialTheme.colorScheme.outline),
                        shape = RoundedCornerShape(12.dp),
                    ) {
                        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
                            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                                Surface(shape = RoundedCornerShape(8.dp), color = MaterialTheme.colorScheme.primary.copy(alpha = 0.10f)) {
                                    Icon(destination.icon, null, Modifier.padding(6.dp).size(20.dp), tint = MaterialTheme.colorScheme.primary)
                                }
                                Text(destination.title, style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.Bold)
                            }
                            HorizontalDivider()
                            Text(destination.description, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                            Row(verticalAlignment = Alignment.CenterVertically) {
                                Icon(Icons.AutoMirrored.Filled.KeyboardArrowRight, null, Modifier.size(18.dp), tint = MaterialTheme.colorScheme.primary)
                                Text("Abrir", color = MaterialTheme.colorScheme.primary, fontWeight = FontWeight.Bold)
                            }
                        }
                    }
                }
                if (row.size == 1) Spacer(Modifier.weight(1f))
            }
        }
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun RoleChips(roles: List<String>) {
    FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        roles.forEach { role ->
            Surface(shape = RoundedCornerShape(8.dp), color = MaterialTheme.colorScheme.surfaceVariant, modifier = Modifier.padding(bottom = 8.dp)) {
                Row(Modifier.padding(horizontal = 10.dp, vertical = 8.dp), verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                    Icon(Icons.Default.CheckCircle, null, Modifier.size(16.dp), tint = MaterialTheme.colorScheme.primary)
                    Text(role, style = MaterialTheme.typography.labelMedium)
                }
            }
        }
    }
}

@Composable
internal fun OutcomeGrid(options: List<Pair<String, String>>, enabled: Boolean, onSelect: (String) -> Unit) {
    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        options.chunked(2).forEach { row ->
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.height(IntrinsicSize.Min)) {
                row.forEach { (outcome, label) ->
                    FilledTonalButton(
                        onClick = { onSelect(outcome) }, enabled = enabled,
                        modifier = Modifier.weight(1f).fillMaxHeight().heightIn(min = 48.dp),
                        contentPadding = PaddingValues(12.dp),
                    ) {
                        ActionLabel(label, when (outcome) {
                            "accepted" -> Icons.Default.CheckCircle
                            "declined", "do_not_contact" -> Icons.Default.Close
                            "no_answer" -> Icons.Default.Notifications
                            "follow_up" -> Icons.Default.DateRange
                            "contacted" -> Icons.Default.Call
                            else -> Icons.Default.Edit
                        })
                    }
                }
                if (row.size == 1) Spacer(Modifier.weight(1f))
            }
        }
    }
}

@Composable
internal fun StatTile(label: String, value: Int, icon: ImageVector, modifier: Modifier = Modifier) {
    OutlinedCard(modifier) {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Icon(icon, null, tint = MaterialTheme.colorScheme.primary)
            Text(value.toString(), style = MaterialTheme.typography.headlineLarge)
            Text(label, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
    }
}
