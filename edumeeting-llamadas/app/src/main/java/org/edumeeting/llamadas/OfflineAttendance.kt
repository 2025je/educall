package org.edumeeting.llamadas

import org.edumeeting.ui.*
import android.net.Uri
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.Send
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.focus.FocusDirection
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalFocusManager
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject

internal class OfflineAttendanceState {
    var conflicts by mutableStateOf<JSONArray?>(null)
    val keepChoices = mutableStateMapOf<Int, String>()
    val resolutions = mutableStateMapOf<Int, String>()
    var pendingPackage by mutableStateOf<ByteArray?>(null)
    var pinConfigured by mutableStateOf<Boolean?>(null)
    var pin by mutableStateOf("")
    var pinConfirmation by mutableStateOf("")
}

private const val MAX_EXPORT_POLLS = 90
private const val MAX_RESULT_FILES = 20

@Composable
internal fun OfflineAttendanceSection(
    api: DjangoSessionApi,
    busy: Boolean,
    runRequest: (suspend () -> Unit) -> Unit,
    onNotice: (String) -> Unit,
    state: OfflineAttendanceState,
) = with(state) {
    val context = LocalContext.current
    val focusManager = LocalFocusManager.current
    val meetingId = api.meetingId

    suspend fun loadConflicts() {
        val id = meetingId ?: return
        val items = withContext(Dispatchers.IO) { api.get("/api/v1/meetings/$id/conflicts/") }.getJSONArray("conflicts")
        conflicts = items
        keepChoices.clear()
        resolutions.clear()
    }

    val saveLauncher = rememberLauncherForActivityResult(
        ActivityResultContracts.CreateDocument("application/vnd.edumeeting.attendance+zip"),
    ) { uri: Uri? ->
        val contents = pendingPackage
        pendingPackage = null
        if (uri == null || contents == null) {
            if (contents != null) onNotice("Exportación cancelada: no se guardó el paquete.")
            return@rememberLauncherForActivityResult
        }
        runRequest {
            withContext(Dispatchers.IO) {
                context.contentResolver.openOutputStream(uri, "wt")?.use { it.write(contents) }
                    ?: throw IllegalStateException("No se pudo escribir el archivo elegido.")
            }
            onNotice("Paquete guardado. Ábrelo desde la app Asistencia con «Importar paquete».")
        }
    }

    val importLauncher = rememberLauncherForActivityResult(ActivityResultContracts.OpenMultipleDocuments()) { uris: List<Uri> ->
        if (uris.isEmpty()) return@rememberLauncherForActivityResult
        if (uris.size > MAX_RESULT_FILES) {
            onNotice("Importa como máximo $MAX_RESULT_FILES archivos a la vez.")
            return@rememberLauncherForActivityResult
        }
        runRequest {
            var imported = 0
            var created = 0
            var duplicates = 0
            var newConflicts = 0
            val people = sortedMapOf<String, Int>()
            val failures = mutableListOf<String>()
            uris.forEachIndexed { index, uri ->
                // Cada archivo se importa por separado: uno inválido no impide combinar los demás.
                try {
                    val contents = withContext(Dispatchers.IO) {
                        context.contentResolver.openInputStream(uri)?.use { it.readBytes() }
                            ?: throw IllegalStateException("No se pudo leer el archivo.")
                    }
                    val report = withContext(Dispatchers.IO) {
                        api.upload("/api/v1/attendance/import/", "resultados-${index + 1}.attendance-results", contents)
                    }
                    imported++
                    created += report.getJSONArray("created").length()
                    duplicates += report.getJSONArray("duplicates").length()
                    newConflicts += report.getJSONArray("conflicts").length()
                    report.optJSONObject("by_operator")?.let { byOperator ->
                        byOperator.keys().forEach { name -> people[name] = (people[name] ?: 0) + byOperator.getInt(name) }
                    }
                } catch (error: CancellationException) {
                    throw error
                } catch (error: Exception) {
                    failures += "Archivo ${index + 1}: ${error.message ?: "no se pudo importar"}"
                }
            }
            loadConflicts()
            val summary = buildString {
                append("Se combinaron $imported de ${uris.size} archivos: $created nuevos, $duplicates ya importados y $newConflicts conflictos nuevos.")
                if (people.isNotEmpty()) append(" Registrado por: ${people.entries.joinToString { "${it.key} (${it.value})" }}.")
                if (failures.isNotEmpty()) append(" ${failures.joinToString(" ")}")
            }
            onNotice(summary)
        }
    }

    LaunchedEffect(meetingId) {
        pinConfigured = null
        val id = meetingId ?: return@LaunchedEffect
        pinConfigured = try {
            withContext(Dispatchers.IO) { api.get("/api/v1/meetings/$id/attendance-pin/") }.getBoolean("configured")
        } catch (error: CancellationException) {
            throw error
        } catch (_: Exception) {
            null
        }
    }

    Text("Asistencia offline", style = MaterialTheme.typography.headlineLarge)
    Text(
        "Define el PIN, exporta el paquete para la app Asistencia, combina los resultados de varios teléfonos y resuelve registros duplicados de la reunión activa.",
        color = MaterialTheme.colorScheme.onSurfaceVariant,
    )
    if (meetingId == null) {
        Admonition(AdmonitionKind.Info, "Sin reunión activa") { Text("Selecciona una reunión para continuar.") }
        return@with
    }
    OutlinedCard(Modifier.fillMaxWidth()) {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            Text("1. PIN de la app Asistencia", style = MaterialTheme.typography.titleMedium)
            Text("Quien use la app Asistencia escribe su nombre y este PIN. Así sabrás quién registró cada asistencia.")
            when (pinConfigured) {
                true -> Admonition(AdmonitionKind.Success, "PIN definido") {
                    Text("Si lo cambias, exporta un paquete nuevo: los anteriores conservan el PIN anterior.")
                }
                false -> Admonition(AdmonitionKind.Warning, "Sin PIN") { Text("Define el PIN antes de exportar el paquete.") }
                null -> Unit
            }
            OutlinedTextField(
                value = pin,
                onValueChange = { value -> pin = value.filter(Char::isDigit).take(8) },
                label = { Text(if (pinConfigured == true) "Nuevo PIN (6 a 8 dígitos)" else "PIN (6 a 8 dígitos)") },
                singleLine = true,
                visualTransformation = PasswordVisualTransformation(),
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.NumberPassword, imeAction = ImeAction.Next),
                keyboardActions = KeyboardActions(onNext = { focusManager.moveFocus(FocusDirection.Down) }),
                modifier = Modifier.fillMaxWidth(),
            )
            OutlinedTextField(
                value = pinConfirmation,
                onValueChange = { value -> pinConfirmation = value.filter(Char::isDigit).take(8) },
                label = { Text("Repite el PIN") },
                singleLine = true,
                isError = pinConfirmation.isNotEmpty() && pinConfirmation != pin,
                visualTransformation = PasswordVisualTransformation(),
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.NumberPassword, imeAction = ImeAction.Done),
                keyboardActions = KeyboardActions(onDone = { focusManager.clearFocus() }),
                modifier = Modifier.fillMaxWidth(),
            )
            Button(
                enabled = !busy && pin.length >= 6 && pin == pinConfirmation,
                modifier = Modifier.fillMaxWidth(),
                onClick = {
                    focusManager.clearFocus()
                    runRequest {
                        withContext(Dispatchers.IO) {
                            api.post("/api/v1/meetings/$meetingId/attendance-pin/", JSONObject().put("pin", pin))
                        }
                        pinConfigured = true
                        pin = ""
                        pinConfirmation = ""
                        onNotice("PIN guardado. Exporta un paquete nuevo para los teléfonos.")
                    }
                },
            ) { ActionLabel("Guardar PIN", Icons.Default.Lock) }
        }
    }
    OutlinedCard(Modifier.fillMaxWidth()) {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            Text("2. Exportar paquete", style = MaterialTheme.typography.titleMedium)
            Text("Genera un paquete firmado con los participantes, sus códigos y el PIN. Luego elige dónde guardarlo y cárgalo en cada teléfono.")
            Button(enabled = !busy && pinConfigured != false, modifier = Modifier.fillMaxWidth(), onClick = {
                runRequest {
                    var job = withContext(Dispatchers.IO) { api.post("/api/v1/meetings/$meetingId/exports/", JSONObject()) }
                    var polls = 0
                    while (job.getString("status") in setOf("pending", "running")) {
                        check(polls++ < MAX_EXPORT_POLLS) { "La exportación sigue en proceso. Inténtalo de nuevo en unos minutos." }
                        delay(1_000)
                        val statusUrl = job.getString("status_url")
                        job = withContext(Dispatchers.IO) { api.get(statusUrl) }
                    }
                    check(job.getString("status") == "succeeded") { job.optString("error").ifBlank { "La exportación falló." } }
                    val downloadUrl = job.getString("download_url")
                    pendingPackage = withContext(Dispatchers.IO) { api.download(downloadUrl) }
                    saveLauncher.launch("reunion-${meetingId.take(8)}.attendance")
                }
            }) { ActionLabel("Exportar asistencia", Icons.Default.Share) }
        }
    }
    OutlinedCard(Modifier.fillMaxWidth()) {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            Text("3. Importar y combinar resultados", style = MaterialTheme.typography.titleMedium)
            Text("Elige a la vez los archivos .attendance-results de todos los teléfonos (hasta $MAX_RESULT_FILES). Se combinan en la reunión; reimportarlos no duplica registros.")
            Button(enabled = !busy, modifier = Modifier.fillMaxWidth(), onClick = { importLauncher.launch(arrayOf("*/*")) }) {
                ActionLabel("Importar resultados", Icons.AutoMirrored.Filled.Send)
            }
        }
    }
    OutlinedCard(Modifier.fillMaxWidth()) {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            Text("4. Resolver conflictos", style = MaterialTheme.typography.titleMedium)
            Text("Si una persona quedó registrada dos veces, elige el registro que se conserva. El otro queda rechazado y ambos se guardan en el historial.")
            OutlinedButton(enabled = !busy, modifier = Modifier.fillMaxWidth(), onClick = { runRequest { loadConflicts() } }) {
                ActionLabel("Consultar conflictos", Icons.Default.Refresh)
            }
            val items = conflicts
            if (items != null && items.length() == 0) {
                Admonition(AdmonitionKind.Success, "Sin conflictos") { Text("No hay conflictos pendientes en esta reunión.") }
            }
            if (items != null) for (index in 0 until items.length()) {
                val conflict = items.getJSONObject(index)
                ConflictCard(conflict, busy, state, onDone = { focusManager.clearFocus() }) { keepId, resolution ->
                    runRequest {
                        withContext(Dispatchers.IO) {
                            api.post(
                                "/api/v1/attendance/conflicts/${conflict.getInt("id")}/resolve/",
                                JSONObject().put("keep_record_id", keepId).put("resolution", resolution),
                            )
                        }
                        loadConflicts()
                        onNotice("Conflicto resuelto.")
                    }
                }
            }
        }
    }
}

@Composable
private fun ConflictCard(
    conflict: JSONObject,
    busy: Boolean,
    state: OfflineAttendanceState,
    onDone: () -> Unit,
    onResolve: (String, String) -> Unit,
) {
    val id = conflict.getInt("id")
    val records = conflict.getJSONArray("records")
    ElevatedCard(Modifier.fillMaxWidth()) {
        Column(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Icon(Icons.Default.Warning, null, tint = MaterialTheme.colorScheme.error)
                Text(conflict.getString("participant_name"), fontWeight = FontWeight.Bold)
            }
            for (recordIndex in 0 until records.length()) {
                val record = records.getJSONObject(recordIndex)
                val recordId = record.getString("id")
                Row(
                    Modifier.fillMaxWidth().heightIn(min = 48.dp).clickable(enabled = !busy) { state.keepChoices[id] = recordId },
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    RadioButton(selected = state.keepChoices[id] == recordId, enabled = !busy, onClick = { state.keepChoices[id] = recordId })
                    Column {
                        Text(record.getString("recorded_at").replace('T', ' ').take(19))
                        Text(
                            "${record.getString("method")} · ${record.getString("device_id")} · Registró: " +
                                record.optString("operator_label").ifBlank { "sin identificar" },
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                }
            }
            OutlinedTextField(
                value = state.resolutions[id].orEmpty(),
                onValueChange = { state.resolutions[id] = it.take(500) },
                label = { Text("Motivo de la resolución") },
                modifier = Modifier.fillMaxWidth(),
                singleLine = true,
                keyboardOptions = KeyboardOptions(imeAction = ImeAction.Done),
                keyboardActions = KeyboardActions(onDone = { onDone() }),
            )
            val keepId = state.keepChoices[id]
            val resolution = state.resolutions[id].orEmpty().trim()
            Button(
                enabled = !busy && keepId != null && resolution.isNotEmpty(),
                modifier = Modifier.fillMaxWidth(),
                onClick = { onResolve(keepId!!, resolution) },
            ) { ActionLabel("Conservar el registro elegido", Icons.Default.Check) }
        }
    }
}
