package org.edumeeting.llamadas

import org.edumeeting.ui.*
import androidx.compose.foundation.clickable
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.foundation.layout.*
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.List
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardCapitalization
import androidx.compose.ui.unit.dp
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject

internal data class AccountGroup(val id: Int, val name: String, val label: String)

internal data class ManagedAccount(
    val id: Int,
    val username: String,
    val firstName: String,
    val lastName: String,
    val fullName: String,
    val isActive: Boolean,
    val initials: String,
    val groups: List<AccountGroup>,
)

internal data class AccountDirectory(val accounts: List<ManagedAccount>, val groups: List<AccountGroup>)

private fun JSONArray.objects(): List<JSONObject> = (0 until length()).map(::getJSONObject)

private fun parseGroup(item: JSONObject) = AccountGroup(item.getInt("id"), item.getString("name"), item.getString("label"))

internal fun parseAccount(item: JSONObject) = ManagedAccount(
    id = item.getInt("id"),
    username = item.getString("username"),
    firstName = item.optString("first_name"),
    lastName = item.optString("last_name"),
    fullName = item.optString("full_name"),
    isActive = item.getBoolean("is_active"),
    initials = item.optString("initials"),
    groups = item.getJSONArray("groups").objects().map(::parseGroup),
)

internal fun parseAccountDirectory(payload: JSONObject) = AccountDirectory(
    accounts = payload.getJSONArray("users").objects().map(::parseAccount),
    groups = payload.getJSONArray("groups").objects().map(::parseGroup),
)

/** Cuerpo de POST /api/v1/users/: las contraseñas solo se envían si se escribieron. */
internal fun accountPayload(
    username: String,
    firstName: String,
    lastName: String,
    groups: Set<Int>,
    initials: String,
    isActive: Boolean,
    password1: String,
    password2: String,
): JSONObject = JSONObject()
    .put("username", username.trim())
    .put("first_name", firstName.trim())
    .put("last_name", lastName.trim())
    .put("groups", JSONArray(groups.sorted()))
    .put("initials", initials.trim().uppercase())
    .put("is_active", isActive)
    .apply {
        if (password1.isNotEmpty() || password2.isNotEmpty()) {
            put("password1", password1)
            put("password2", password2)
        }
    }

internal class SuperuserState {
    var statistics by mutableStateOf<JSONObject?>(null)
    var directory by mutableStateOf<AccountDirectory?>(null)
    var filter by mutableStateOf("")
    var formOpen by mutableStateOf(false)
    var editingId by mutableStateOf<Int?>(null)
    var username by mutableStateOf("")
    var firstName by mutableStateOf("")
    var lastName by mutableStateOf("")
    var groups by mutableStateOf<Set<Int>>(emptySet())
    var initials by mutableStateOf("")
    var isActive by mutableStateOf(true)
    var password1 by mutableStateOf("")
    var password2 by mutableStateOf("")
    var confirmStatus by mutableStateOf<ManagedAccount?>(null)

    fun openForm(account: ManagedAccount?) {
        formOpen = true
        editingId = account?.id
        username = account?.username.orEmpty()
        firstName = account?.firstName.orEmpty()
        lastName = account?.lastName.orEmpty()
        groups = account?.groups?.map { it.id }?.toSet().orEmpty()
        initials = account?.initials.orEmpty()
        isActive = account?.isActive ?: true
        password1 = ""
        password2 = ""
    }

    fun closeForm() {
        openForm(null)
        formOpen = false
    }
}

@Composable
internal fun SuperuserHome(username: String, navigate: (DialDestination) -> Unit) {
    Column(verticalArrangement = Arrangement.spacedBy(20.dp)) {
        Text("Hola, $username", style = MaterialTheme.typography.headlineLarge)
        Admonition(
            "Como superusuario gestionas cuentas y grupos, y consultas las estadísticas de todas las reuniones. " +
                "Las reuniones las operan sus administradores.",
            AdmonitionKind.Note,
        )
        Row(horizontalArrangement = Arrangement.spacedBy(12.dp), modifier = Modifier.height(IntrinsicSize.Min)) {
            listOf(DialDestination.Statistics, DialDestination.Users).forEach { destination ->
                GridCard(
                    icon = destination.icon, title = destination.title, description = destination.description,
                    action = "Abrir", onClick = { navigate(destination) },
                    modifier = Modifier.weight(1f).fillMaxHeight(),
                )
            }
        }
    }
}

@Composable
private fun Tag(text: String, highlighted: Boolean = false) {
    Surface(
        shape = RoundedCornerShape(8.dp),
        color = if (highlighted) MaterialTheme.colorScheme.primary.copy(alpha = 0.12f) else MaterialTheme.colorScheme.surfaceVariant,
        modifier = Modifier.padding(bottom = 4.dp),
    ) {
        Text(text, style = MaterialTheme.typography.labelMedium, modifier = Modifier.padding(horizontal = 10.dp, vertical = 6.dp))
    }
}

@Composable
private fun StatGrid(stats: List<Triple<String, Int, ImageVector>>) {
    Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
        stats.chunked(2).forEach { row ->
            Row(horizontalArrangement = Arrangement.spacedBy(12.dp), modifier = Modifier.height(IntrinsicSize.Min)) {
                row.forEach { (label, value, icon) -> StatCard(icon, value.toString(), label, Modifier.weight(1f).fillMaxHeight()) }
                if (row.size == 1) Spacer(Modifier.weight(1f))
            }
        }
    }
}

@Composable
internal fun SuperuserStatistics(
    api: DjangoSessionApi,
    busy: Boolean,
    runRequest: (suspend () -> Unit) -> Unit,
    state: SuperuserState,
) {
    fun load() = runRequest {
        state.statistics = withContext(Dispatchers.IO) { api.get("/api/v1/statistics/") }
    }
    LaunchedEffect(Unit) { if (state.statistics == null) load() }
    Column(verticalArrangement = Arrangement.spacedBy(16.dp)) {
        Text("Estadísticas globales", style = MaterialTheme.typography.headlineLarge)
        Text("Todas las reuniones, activas e inactivas. Solo lectura.", color = MaterialTheme.colorScheme.onSurfaceVariant)
        OutlinedButton(enabled = !busy, onClick = ::load) { ActionLabel("Actualizar", Icons.Default.Refresh) }
        val report = state.statistics
        if (report == null) {
            EmptyState(Icons.AutoMirrored.Filled.List, "Sin datos todavía", "Toca Actualizar para consultar las estadísticas.")
            return@Column
        }
        val totals = report.getJSONObject("totals")
        StatGrid(listOf(
            Triple("Reuniones", totals.getInt("meetings"), Icons.Default.DateRange),
            Triple("Reuniones activas", totals.getInt("active_meetings"), Icons.Default.PlayArrow),
            Triple("Registrados", totals.getInt("registered"), Icons.Default.Person),
            Triple("Llamadas pendientes", totals.getInt("pending_calls"), Icons.Default.Call),
            Triple("Llamadas finalizadas", totals.getInt("completed_calls"), Icons.Default.CheckCircle),
            Triple("Intentos", totals.getInt("call_attempts"), Icons.Default.Phone),
            Triple("Aceptaron", totals.getInt("accepted"), Icons.Default.ThumbUp),
            Triple("Asistencias", totals.getInt("attendance"), Icons.Default.Done),
            Triple("Por revisar", totals.getInt("pending_review"), Icons.Default.Warning),
            Triple("Rechazadas", totals.getInt("rejected"), Icons.Default.Close),
        ))
        val meetings = report.getJSONArray("meetings").objects()
        if (meetings.isEmpty()) EmptyState(Icons.Default.DateRange, "Sin reuniones", "Aún no hay reuniones creadas.")
        meetings.forEach { meeting -> MeetingOverviewCard(meeting) }
    }
}

@Composable
private fun MeetingOverviewCard(meeting: JSONObject) {
    var expanded by remember(meeting.getString("meeting_id")) { mutableStateOf(false) }
    val users = meeting.getJSONArray("users").objects()
    OutlinedCard(Modifier.fillMaxWidth()) {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Text(
                    meeting.getString("meeting_name"),
                    style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold,
                    modifier = Modifier.weight(1f),
                )
                val active = meeting.getBoolean("active")
                Tag(if (active) "Activa" else "Inactiva", highlighted = active)
            }
            meeting.optString("call_phase_label").takeIf { it.isNotBlank() }?.let {
                Text(it, style = MaterialTheme.typography.labelLarge, color = MaterialTheme.colorScheme.primary)
            }
            meeting.optJSONArray("schedules")?.objects()?.forEach { schedule ->
                Text(
                    "• ${schedule.optString("label")} · Aceptaron ${schedule.optInt("accepted")} · Confirmaron ${schedule.optInt("confirmed")}",
                    style = MaterialTheme.typography.bodySmall,
                )
            }
            Text(
                "Administrador: ${meeting.optString("administrator").takeUnless { meeting.isNull("administrator") } ?: "sin asignar"}",
                style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            Text(
                "Registrados ${meeting.getInt("registered")} · Pendientes ${meeting.getInt("pending_calls")} · " +
                    "Finalizadas ${meeting.getInt("completed_calls")} · Intentos ${meeting.getInt("call_attempts")} · " +
                    "Aceptaron ${meeting.getInt("accepted")} · Confirmaron ${meeting.optInt("confirmed")} · " +
                    "No asistirán ${meeting.optInt("will_not_attend")}",
            )
            Text(
                "Asistencias ${meeting.getInt("attendance")} · Por revisar ${meeting.getInt("pending_review")} · " +
                    "Rechazadas ${meeting.getInt("rejected")}",
            )
            if (users.isNotEmpty()) {
                TextButton(onClick = { expanded = !expanded }) {
                    ActionLabel(
                        if (expanded) "Ocultar actividad por usuario" else "Ver actividad por usuario (${users.size})",
                        if (expanded) Icons.Default.KeyboardArrowUp else Icons.Default.KeyboardArrowDown,
                    )
                }
                if (expanded) users.forEach { user ->
                    ListItem(
                        headlineContent = { Text(user.getString("username"), fontWeight = FontWeight.Bold) },
                        supportingContent = {
                            Text("Registrados: ${user.getInt("registered")} · Intentos: ${user.getInt("call_attempts")} · Aceptaciones: ${user.getInt("accepted")}")
                        },
                        leadingContent = { Icon(Icons.Default.AccountCircle, null) },
                        colors = ListItemDefaults.colors(containerColor = MaterialTheme.colorScheme.surface),
                    )
                }
            }
        }
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
internal fun SuperuserAccounts(
    api: DjangoSessionApi,
    busy: Boolean,
    runRequest: (suspend () -> Unit) -> Unit,
    onNotice: (String) -> Unit,
    state: SuperuserState,
) = with(state) {
    fun load() = runRequest {
        directory = parseAccountDirectory(withContext(Dispatchers.IO) { api.get("/api/v1/users/") })
    }
    LaunchedEffect(Unit) { if (directory == null) load() }
    val operatorGroup = directory?.groups?.firstOrNull { it.name == "OPERADOR" }
    val initialsEnabled = operatorGroup != null && operatorGroup.id in groups
    val creating = editingId == null
    val canSave = !busy && username.isNotBlank() && (!creating || (password1.isNotEmpty() && password2.isNotEmpty()))

    fun save() = runRequest {
        val body = accountPayload(
            username, firstName, lastName, groups, if (initialsEnabled) initials else "", isActive, password1, password2,
        )
        val path = editingId?.let { "/api/v1/users/$it/" } ?: "/api/v1/users/"
        val saved = parseAccount(withContext(Dispatchers.IO) { api.post(path, body) }.getJSONObject("user"))
        directory = parseAccountDirectory(withContext(Dispatchers.IO) { api.get("/api/v1/users/") })
        closeForm()
        onNotice(if (creating) "Usuario ${saved.username} creado." else "Usuario ${saved.username} actualizado.")
    }

    fun setStatus(account: ManagedAccount, active: Boolean) = runRequest {
        val updated = parseAccount(
            withContext(Dispatchers.IO) {
                api.post("/api/v1/users/${account.id}/status/", JSONObject().put("is_active", active))
            }.getJSONObject("user"),
        )
        directory = directory?.let { current ->
            current.copy(accounts = current.accounts.map { if (it.id == updated.id) updated else it })
        }
        onNotice(if (updated.isActive) "Usuario ${updated.username} activado." else "Usuario ${updated.username} desactivado.")
    }

    confirmStatus?.let { account ->
        AlertDialog(
            onDismissRequest = { confirmStatus = null },
            icon = { Icon(Icons.Default.Warning, null) },
            title = { Text("¿Desactivar a ${account.username}?") },
            text = { Text("No podrá iniciar sesión en la web ni en las apps hasta que lo actives de nuevo. Sus datos se conservan.") },
            confirmButton = {
                TextButton(onClick = { confirmStatus = null; setStatus(account, false) }) { Text("Desactivar") }
            },
            dismissButton = { TextButton(onClick = { confirmStatus = null }) { Text("Cancelar") } },
        )
    }

    Column(verticalArrangement = Arrangement.spacedBy(16.dp)) {
        Text("Usuarios y grupos", style = MaterialTheme.typography.headlineLarge)
        Text(
            "Crea cuentas, asigna sus grupos y actívalas o desactívalas. Tu propia cuenta no aparece aquí.",
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Button(enabled = !busy, onClick = { openForm(null) }) { ActionLabel("Nuevo usuario", Icons.Default.Add) }
            OutlinedButton(enabled = !busy, onClick = ::load) { ActionLabel("Actualizar", Icons.Default.Refresh) }
        }

        if (formOpen) DocSection(if (creating) "Crear usuario" else "Editar $username") {
            FormTextField(
                value = username, onValueChange = { username = it.uppercase() }, label = "Usuario",
                leadingIcon = Icons.Default.Person, capitalization = KeyboardCapitalization.Characters,
                modifier = Modifier.fillMaxWidth(),
            )
            FormTextField(
                value = firstName, onValueChange = { firstName = it }, label = "Nombre",
                capitalization = KeyboardCapitalization.Words, modifier = Modifier.fillMaxWidth(),
            )
            FormTextField(
                value = lastName, onValueChange = { lastName = it }, label = "Apellidos",
                capitalization = KeyboardCapitalization.Words, modifier = Modifier.fillMaxWidth(),
            )
            Text("Grupos", style = MaterialTheme.typography.titleSmall)
            directory?.groups.orEmpty().forEach { group ->
                fun toggle(checked: Boolean) { groups = if (checked) groups + group.id else groups - group.id }
                Row(
                    Modifier.fillMaxWidth().heightIn(min = 48.dp).clickable(enabled = !busy) { toggle(group.id !in groups) },
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Checkbox(checked = group.id in groups, enabled = !busy, onCheckedChange = ::toggle)
                    Text(group.label)
                }
            }
            FormTextField(
                value = if (initialsEnabled) initials else "",
                onValueChange = { initials = it.filter(Char::isLetter).take(2).uppercase() },
                label = "Iniciales de operador", leadingIcon = Icons.Default.Info,
                enabled = initialsEnabled, capitalization = KeyboardCapitalization.Characters,
                supportingText = if (initialsEnabled) {
                    if (creating) "Dos letras, obligatorias para operadores." else "Vacío conserva las iniciales actuales."
                } else "Solo para Operador de llamadas.",
                modifier = Modifier.fillMaxWidth(),
            )
            Row(
                Modifier.fillMaxWidth().heightIn(min = 48.dp).clickable(enabled = !busy) { isActive = !isActive },
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text("Usuario activo", Modifier.weight(1f))
                Switch(checked = isActive, enabled = !busy, onCheckedChange = { isActive = it })
            }
            PasswordField(
                value = password1, onValueChange = { password1 = it }, label = "Contraseña",
                imeAction = ImeAction.Next, modifier = Modifier.fillMaxWidth(),
            )
            PasswordField(
                value = password2, onValueChange = { password2 = it }, label = "Confirmar contraseña",
                imeAction = ImeAction.Done, onSubmit = { if (canSave) save() }, modifier = Modifier.fillMaxWidth(),
            )
            if (!creating) Text(
                "Deja ambas contraseñas vacías para conservar la actual.",
                style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Button(enabled = canSave, onClick = ::save) {
                    ActionLabel(if (creating) "Crear usuario" else "Guardar cambios", Icons.Default.Check)
                }
                OutlinedButton(enabled = !busy, onClick = { closeForm() }) { ActionLabel("Cancelar", Icons.Default.Close) }
            }
        }

        val data = directory
        if (data == null) {
            EmptyState(Icons.Default.AccountCircle, "Sin datos todavía", "Toca Actualizar para cargar los usuarios.")
            return@Column
        }
        FormTextField(
            value = filter, onValueChange = { filter = it }, label = "Filtrar por usuario, nombre o grupo",
            leadingIcon = Icons.Default.Search, clearable = true, imeAction = ImeAction.Search,
            modifier = Modifier.fillMaxWidth(),
        )
        val needle = filter.trim().lowercase()
        val visible = data.accounts.filter { account ->
            needle.isEmpty() || listOf(account.username, account.fullName, account.initials)
                .plus(account.groups.map { it.label })
                .any { it.lowercase().contains(needle) }
        }
        Text("${visible.size} de ${data.accounts.size} usuario(s)", style = MaterialTheme.typography.bodySmall)
        if (data.accounts.isEmpty()) EmptyState(
            Icons.Default.Person, "No hay otros usuarios", "Crea la primera cuenta con Nuevo usuario.",
        )
        visible.forEach { account ->
            OutlinedCard(Modifier.fillMaxWidth()) {
                Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        Icon(Icons.Default.AccountCircle, null, tint = MaterialTheme.colorScheme.primary)
                        Column(Modifier.weight(1f)) {
                            Text(account.username, fontWeight = FontWeight.Bold)
                            if (account.fullName.isNotBlank()) Text(account.fullName, style = MaterialTheme.typography.bodySmall)
                        }
                        Text(
                            if (account.isActive) "Activo" else "Inactivo",
                            style = MaterialTheme.typography.labelLarge,
                            color = if (account.isActive) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.error,
                        )
                    }
                    FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        if (account.groups.isEmpty()) Text("Sin grupos", color = MaterialTheme.colorScheme.onSurfaceVariant)
                        account.groups.forEach { group ->
                            Tag(group.label)
                        }
                        if (account.initials.isNotBlank()) Tag("Iniciales ${account.initials}")
                    }
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        OutlinedButton(enabled = !busy, onClick = { openForm(account) }) { ActionLabel("Editar", Icons.Default.Edit) }
                        if (account.isActive) {
                            OutlinedButton(enabled = !busy, onClick = { confirmStatus = account }) { ActionLabel("Desactivar", Icons.Default.Lock) }
                        } else {
                            OutlinedButton(enabled = !busy, onClick = { setStatus(account, true) }) { ActionLabel("Activar", Icons.Default.CheckCircle) }
                        }
                    }
                }
            }
        }
    }
}
