package org.edumeeting.llamadas

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.ui.focus.FocusDirection
import androidx.compose.ui.platform.LocalFocusManager
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.material.icons.automirrored.filled.List
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject

internal class RoleWorkspaceState {
    var fullName by mutableStateOf("")
    var phone by mutableStateOf("")
    var consent by mutableStateOf(false)
    var members by mutableStateOf<JSONObject?>(null)
    var registrars by mutableStateOf<Set<Int>>(emptySet())
    var operators by mutableStateOf<Set<Int>>(emptySet())
    var statistics by mutableStateOf<JSONObject?>(null)
    val offline = OfflineAttendanceState()
}

@Composable
internal fun RoleWorkspace(
    api: DjangoSessionApi,
    canManage: Boolean,
    canRegister: Boolean,
    busy: Boolean,
    runRequest: (suspend () -> Unit) -> Unit,
    onNotice: (String) -> Unit,
    state: RoleWorkspaceState,
) = with(state) {
    val focusManager = LocalFocusManager.current
    Column(verticalArrangement = Arrangement.spacedBy(16.dp)) {
        if (canManage) {
            Text("Tu equipo, en un vistazo", style = MaterialTheme.typography.headlineLarge)
            Button(enabled = !busy, modifier = Modifier.fillMaxWidth(), onClick = {
                runRequest {
                    val assignment = withContext(Dispatchers.IO) { api.get("/api/v1/meetings/members/") }
                    val report = withContext(Dispatchers.IO) { api.get("/api/v1/meetings/statistics/") }
                    members = assignment
                    registrars = assignment.getJSONArray("selected_registrars").intSet()
                    operators = assignment.getJSONArray("selected_operators").intSet()
                    statistics = report
                }
            }) { ActionLabel("Consultar equipo y estadísticas", Icons.Default.Refresh) }
            if (statistics == null) EmptyState(Icons.AutoMirrored.Filled.List, "Conoce el progreso", "Consulta los datos de la reunión activa para ver estadísticas y asignar cuentas.")
            statistics?.let { report ->
                Text(report.getString("meeting_name"), style = MaterialTheme.typography.titleLarge)
                val stats = listOf(
                    Triple("Registrados", report.getInt("registered"), Icons.Default.Person),
                    Triple("Pendientes", report.getInt("pending_calls"), Icons.Default.Call),
                    Triple("Finalizadas", report.getInt("completed_calls"), Icons.Default.CheckCircle),
                    Triple("Intentos", report.getInt("call_attempts"), Icons.Default.Phone),
                    Triple("Aceptaron", report.getInt("accepted"), Icons.Default.ThumbUp),
                )
                stats.chunked(2).forEach { row ->
                    Row(horizontalArrangement = Arrangement.spacedBy(12.dp), modifier = Modifier.height(IntrinsicSize.Min)) {
                        row.forEach { (label, value, icon) -> StatTile(label, value, icon, Modifier.weight(1f).fillMaxHeight()) }
                        if (row.size == 1) Spacer(Modifier.weight(1f))
                    }
                }
                val users = report.getJSONArray("users")
                if (users.length() > 0) OutlinedCard(Modifier.fillMaxWidth()) {
                    Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                        Text("Actividad por usuario", style = MaterialTheme.typography.titleMedium)
                        for (index in 0 until users.length()) {
                            val user = users.getJSONObject(index)
                            ListItem(
                                headlineContent = { Text(user.getString("username"), fontWeight = FontWeight.Bold) },
                                supportingContent = { Text("Registrados: ${user.getInt("registered")} · Intentos: ${user.getInt("call_attempts")} · Aceptaciones: ${user.getInt("accepted")}") },
                                leadingContent = { Icon(Icons.Default.AccountCircle, null) },
                                colors = ListItemDefaults.colors(containerColor = MaterialTheme.colorScheme.surface),
                            )
                        }
                    }
                }
            }
            members?.let { data ->
                OutlinedCard(Modifier.fillMaxWidth()) {
                    Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
                        Text("Asignar cuentas", style = MaterialTheme.typography.titleLarge)
                        Text("Selecciona cuentas existentes. Desmarcar quita la asignación.", color = MaterialTheme.colorScheme.onSurfaceVariant)
                        for ((field, label) in listOf("registrars" to "Registradores de participantes", "operators" to "Operadores de llamadas")) {
                            Text(label, style = MaterialTheme.typography.titleMedium)
                            val choices = data.getJSONArray(field)
                            if (choices.length() == 0) Text("No hay cuentas activas de este grupo.")
                            for (index in 0 until choices.length()) {
                                val user = choices.getJSONObject(index)
                                val id = user.getInt("id")
                                val selected = if (field == "registrars") registrars else operators
                                fun updateSelection(checked: Boolean) {
                                    val updated = if (checked) selected + id else selected - id
                                    if (field == "registrars") registrars = updated else operators = updated
                                }
                                Row(
                                    Modifier.fillMaxWidth().heightIn(min = 48.dp).clickable(enabled = !busy) { updateSelection(id !in selected) },
                                    verticalAlignment = Alignment.CenterVertically,
                                ) {
                                    Checkbox(checked = id in selected, enabled = !busy, onCheckedChange = ::updateSelection)
                                    Text(user.getString("username"))
                                }
                            }
                        }
                        Button(enabled = !busy, modifier = Modifier.fillMaxWidth(), onClick = {
                            runRequest {
                                withContext(Dispatchers.IO) {
                                    api.post("/api/v1/meetings/members/", JSONObject()
                                        .put("registrars", JSONArray(registrars.toList()))
                                        .put("operators", JSONArray(operators.toList())))
                                }
                                onNotice("Asignaciones guardadas.")
                            }
                        }) { ActionLabel("Guardar asignaciones", Icons.Default.Check) }
                    }
                }
            }
            HorizontalDivider()
            OfflineAttendanceSection(api, busy, runRequest, onNotice, offline)
        }
        if (canRegister) {
            Text("Una persona, una conexión", style = MaterialTheme.typography.headlineLarge)
            Text("Agrega una persona a la cola de la reunión activa.", color = MaterialTheme.colorScheme.onSurfaceVariant)
            OutlinedCard(Modifier.fillMaxWidth()) {
                Column(Modifier.padding(20.dp), verticalArrangement = Arrangement.spacedBy(16.dp)) {
                    OutlinedTextField(
                        value = fullName, onValueChange = { fullName = it },
                        label = { Text("Nombre completo") }, leadingIcon = { Icon(Icons.Default.Person, null) },
                        modifier = Modifier.fillMaxWidth(), singleLine = true,
                        keyboardOptions = KeyboardOptions(imeAction = ImeAction.Next),
                        keyboardActions = KeyboardActions(onNext = { focusManager.moveFocus(FocusDirection.Down) }),
                    )
                    OutlinedTextField(
                        value = phone, onValueChange = { phone = it },
                        label = { Text("Teléfono") }, leadingIcon = { Icon(Icons.Default.Phone, null) },
                        modifier = Modifier.fillMaxWidth(), singleLine = true,
                        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Phone, imeAction = ImeAction.Done),
                        keyboardActions = KeyboardActions(onDone = { focusManager.clearFocus() }),
                    )
                    Row(Modifier.fillMaxWidth().clickable(enabled = !busy) { consent = !consent }, verticalAlignment = Alignment.CenterVertically) {
                        Checkbox(checked = consent, onCheckedChange = { consent = it }, enabled = !busy)
                        Text("La persona autorizó el contacto")
                    }
                    Admonition(AdmonitionKind.Info, "Consentimiento de contacto") {
                        Text("Sin autorización, la tarea se guarda pero no se ofrece a operadores para llamar.")
                    }
                    Button(
                        enabled = !busy && fullName.isNotBlank() && phone.isNotBlank(),
                        modifier = Modifier.fillMaxWidth().heightIn(min = 52.dp),
                        onClick = {
                            runRequest {
                                withContext(Dispatchers.IO) {
                                    api.post("/api/v1/participants/", JSONObject()
                                        .put("full_name", fullName).put("phone", phone)
                                        .put("contact_authorized", consent))
                                }
                                fullName = ""
                                phone = ""
                                consent = false
                                onNotice("Persona registrada en la cola de la reunión activa.")
                            }
                        },
                    ) { ActionLabel("Agregar a la cola", Icons.Default.Add) }
                }
            }
        }
    }
}

private fun JSONArray.intSet(): Set<Int> = (0 until length()).map { getInt(it) }.toSet()
