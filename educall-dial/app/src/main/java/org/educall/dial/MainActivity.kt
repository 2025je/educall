package org.educall.dial

import android.content.Intent
import android.net.Uri
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONObject

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent { DialScreen() }
    }
}

private data class CallTaskInfo(
    val id: String,
    val name: String,
    val phone: String,
    val meeting: String,
    val origin: String,
    val history: List<String>,
)

private data class PersonInfo(
    val id: String,
    val name: String,
    val phone: String,
    val originId: String?,
    val doNotContact: Boolean,
    val authorized: Boolean,
    val invitationStatus: String,
)

private data class MessageDraft(val logId: Int, val text: String, val url: String)

@Composable
private fun DialScreen() {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    var serverUrl by remember { mutableStateOf("https://") }
    var username by remember { mutableStateOf("") }
    var password by remember { mutableStateOf("") }
    var api by remember { mutableStateOf<DjangoSessionApi?>(null) }
    var notice by remember { mutableStateOf("Conéctate al servidor para gestionar llamadas e invitaciones.") }
    var busy by remember { mutableStateOf(false) }
    var callTask by remember { mutableStateOf<CallTaskInfo?>(null) }
    var callNotes by remember { mutableStateOf("") }
    var query by remember { mutableStateOf("") }
    var results by remember { mutableStateOf<List<PersonInfo>>(emptyList()) }
    var templates by remember { mutableStateOf<List<Pair<Int, String>>>(emptyList()) }
    var templateId by remember { mutableStateOf<Int?>(null) }
    var draft by remember { mutableStateOf<MessageDraft?>(null) }

    fun runRequest(action: suspend () -> Unit) {
        if (busy) return
        scope.launch {
            busy = true
            try {
                action()
            } catch (error: Exception) {
                notice = error.message ?: "No se pudo completar la operación."
            } finally {
                busy = false
            }
        }
    }

    MaterialTheme {
        Scaffold { insets ->
            LazyColumn(
                modifier = Modifier.fillMaxSize().padding(insets).padding(16.dp),
                verticalArrangement = Arrangement.spacedBy(12.dp),
            ) {
                item {
                    Text("EduCall Dial", style = MaterialTheme.typography.headlineMedium)
                    Text(notice, color = MaterialTheme.colorScheme.primary)
                }
                if (api == null) {
                    item {
                        Card(Modifier.fillMaxWidth()) {
                            Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                                Text("Conexión segura al servidor", style = MaterialTheme.typography.titleMedium)
                                OutlinedTextField(
                                    value = serverUrl,
                                    onValueChange = { serverUrl = it },
                                    label = { Text("URL HTTPS del servidor") },
                                    singleLine = true,
                                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Uri),
                                    modifier = Modifier.fillMaxWidth(),
                                )
                                OutlinedTextField(
                                    value = username,
                                    onValueChange = { username = it },
                                    label = { Text("Usuario") },
                                    singleLine = true,
                                    modifier = Modifier.fillMaxWidth(),
                                )
                                OutlinedTextField(
                                    value = password,
                                    onValueChange = { password = it },
                                    label = { Text("Contraseña") },
                                    singleLine = true,
                                    visualTransformation = PasswordVisualTransformation(),
                                    modifier = Modifier.fillMaxWidth(),
                                )
                                Button(
                                    enabled = !busy && username.isNotBlank() && password.isNotBlank(),
                                    onClick = {
                                        runRequest {
                                            val sessionApi = withContext(Dispatchers.IO) {
                                                DjangoSessionApi(serverUrl).also { it.login(username, password) }
                                            }
                                            api = sessionApi
                                            password = ""
                                            templates = withContext(Dispatchers.IO) {
                                                val json = sessionApi.get("/api/v1/whatsapp/templates/")
                                                json.getJSONArray("templates").let { array ->
                                                    (0 until array.length()).map { index ->
                                                        val item = array.getJSONObject(index)
                                                        item.getInt("id") to item.getString("name")
                                                    }
                                                }
                                            }
                                            templateId = templates.firstOrNull()?.first
                                            notice = "Sesión iniciada. Las acciones se validan con los permisos de tu cuenta."
                                        }
                                    },
                                    modifier = Modifier.fillMaxWidth(),
                                ) { Text(if (busy) "Conectando…" else "Iniciar sesión") }
                                Text("Usa HTTPS con certificado válido. Las credenciales no se guardan en el dispositivo.")
                            }
                        }
                    }
                } else {
                    item {
                        OutlinedButton(enabled = !busy, onClick = {
                            runRequest {
                                withContext(Dispatchers.IO) { api!!.logout() }
                                api = null
                                callTask = null
                                results = emptyList()
                                draft = null
                                notice = "Sesión cerrada."
                            }
                        }) { Text("Cerrar sesión") }
                    }
                    item {
                        Card(Modifier.fillMaxWidth()) {
                            Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                                Text("Llamadas salientes", style = MaterialTheme.typography.titleMedium)
                                Button(
                                    enabled = !busy && callTask == null,
                                    onClick = {
                                        runRequest {
                                            val payload = withContext(Dispatchers.IO) {
                                                api!!.post("/api/v1/calls/next/", JSONObject())
                                            }
                                            val raw = payload.optJSONObject("task")
                                            callTask = raw?.let {
                                                val person = it.getJSONObject("participant")
                                                CallTaskInfo(
                                                    id = it.getString("id"),
                                                    name = person.getString("name"),
                                                    phone = person.optString("phone"),
                                                    meeting = it.getJSONObject("meeting").getString("name"),
                                                    origin = person.optJSONObject("origin_meeting")?.optString("name")
                                                        ?: "Sin reunión de origen",
                                                    history = it.optJSONArray("history")?.let { history ->
                                                        (0 until history.length()).map { index ->
                                                            val entry = history.getJSONObject(index)
                                                            "${entry.optString("created_at")} · ${entry.optString("operator")} · ${entry.optString("outcome")} ${entry.optString("notes")}"
                                                        }
                                                    }.orEmpty(),
                                                )
                                            }
                                            notice = if (callTask == null) "No hay llamadas disponibles en este momento."
                                            else "Llamada asignada. Registra el resultado al terminar."
                                            callNotes = ""
                                        }
                                    },
                                    modifier = Modifier.fillMaxWidth(),
                                ) { Text(if (busy) "Consultando…" else "Solicitar siguiente llamada") }
                                callTask?.let { task ->
                                    Text(task.name, style = MaterialTheme.typography.titleLarge)
                                    Text("${task.phone.ifBlank { "Sin teléfono" }} · ${task.meeting}")
                                    Text("Origen: ${task.origin}")
                                    task.history.forEach { Text(it, style = MaterialTheme.typography.bodySmall) }
                                    OutlinedTextField(
                                        value = callNotes,
                                        onValueChange = { callNotes = it },
                                        label = { Text("Notas de la llamada") },
                                        modifier = Modifier.fillMaxWidth(),
                                    )
                                    if (task.phone.isNotBlank()) {
                                        OutlinedButton(onClick = {
                                            context.startActivity(Intent(Intent.ACTION_DIAL, Uri.parse("tel:${Uri.encode(task.phone)}")))
                                        }) { Text("Llamar ${task.phone}") }
                                    }
                                    listOf(
                                        "accepted" to "Aceptó",
                                        "declined" to "Rechazó",
                                        "contacted" to "Contactado",
                                        "no_answer" to "No contesta",
                                        "follow_up" to "Seguimiento",
                                        "do_not_contact" to "No volver a contactar",
                                        "other" to "Otro",
                                    ).forEach { (outcome, label) ->
                                        OutlinedButton(
                                            enabled = !busy,
                                            onClick = {
                                                runRequest {
                                                    val response = withContext(Dispatchers.IO) {
                                                        api!!.post(
                                                            "/api/v1/calls/${task.id}/result/",
                                                            JSONObject().put("outcome", outcome).put("notes", callNotes),
                                                        )
                                                    }
                                                    notice = response.optString("code").takeIf { it.isNotBlank() }
                                                        ?.let { "Aceptación registrada. Código: $it" }
                                                        ?: "Resultado de llamada guardado."
                                                    callTask = null
                                                }
                                            },
                                            modifier = Modifier.fillMaxWidth(),
                                        ) { Text(label) }
                                    }
                                }
                            }
                        }
                    }
                    item {
                        Card(Modifier.fillMaxWidth()) {
                            Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                                Text("Búsqueda y llamadas entrantes", style = MaterialTheme.typography.titleMedium)
                                OutlinedTextField(
                                    value = query,
                                    onValueChange = { query = it },
                                    label = { Text("Nombre o teléfono") },
                                    modifier = Modifier.fillMaxWidth(),
                                )
                                Button(enabled = !busy, onClick = {
                                    runRequest {
                                        val payload = withContext(Dispatchers.IO) {
                                            api!!.get("/api/v1/participants/search/?q=${Uri.encode(query.trim())}")
                                        }
                                        val array = payload.getJSONArray("results")
                                        results = (0 until array.length()).map { index ->
                                            val item = array.getJSONObject(index)
                                            PersonInfo(
                                                id = item.getString("id"),
                                                name = item.getString("name"),
                                                phone = item.optString("phone"),
                                                originId = item.opt("origin_meeting")
                                                    ?.takeIf { it != JSONObject.NULL }
                                                    ?.toString(),
                                                doNotContact = item.optBoolean("do_not_contact"),
                                                authorized = item.optBoolean("contact_authorized"),
                                                invitationStatus = item.optString("invitation_status"),
                                            )
                                        }
                                        notice = "${results.size} participante(s) encontrados."
                                    }
                                }, modifier = Modifier.fillMaxWidth()) { Text("Buscar participantes") }
                                templates.takeIf { it.isNotEmpty() }?.let { options ->
                                    options.forEach { (id, name) ->
                                        OutlinedButton(
                                            onClick = { templateId = id },
                                            modifier = Modifier.fillMaxWidth(),
                                        ) { Text(if (templateId == id) "✓ $name" else name) }
                                    }
                                }
                            }
                        }
                    }
                    items(results, key = { it.id }) { person ->
                        Card(Modifier.fillMaxWidth()) {
                            Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                                Text(person.name, style = MaterialTheme.typography.titleMedium)
                                Text("${person.phone.ifBlank { "Sin teléfono" }} · Invitación: ${person.invitationStatus}")
                                if (person.doNotContact) Text("NO CONTACTAR", color = MaterialTheme.colorScheme.error)
                                if (person.phone.isNotBlank()) {
                                    OutlinedButton(onClick = {
                                        context.startActivity(Intent(Intent.ACTION_DIAL, Uri.parse("tel:${Uri.encode(person.phone)}")))
                                    }) { Text("Llamar") }
                                }
                                if (person.originId != null) {
                                    listOf(
                                        "contacted" to "Contacto entrante · Contactado",
                                        "accepted" to "Contacto entrante · Aceptó",
                                        "declined" to "Contacto entrante · Rechazó",
                                        "follow_up" to "Contacto entrante · Seguimiento",
                                        "do_not_contact" to "Contacto entrante · No contactar",
                                        "other" to "Contacto entrante · Otro",
                                    ).forEach { (outcome, label) ->
                                        OutlinedButton(
                                            enabled = !busy,
                                            onClick = {
                                                runRequest {
                                                    val response = withContext(Dispatchers.IO) {
                                                        api!!.post(
                                                            "/api/v1/calls/inbound/",
                                                            JSONObject().put("participant_id", person.id).put("outcome", outcome),
                                                        )
                                                    }
                                                    notice = response.optString("code").takeIf(String::isNotBlank)
                                                        ?.let { "Aceptación registrada. Código: $it" }
                                                        ?: "Contacto entrante registrado."
                                                }
                                            },
                                            modifier = Modifier.fillMaxWidth(),
                                        ) { Text(label) }
                                    }
                                }
                                if (!person.doNotContact && person.authorized && person.phone.isNotBlank() && templateId != null) {
                                    OutlinedButton(
                                        enabled = !busy,
                                        onClick = {
                                            runRequest {
                                                val response = withContext(Dispatchers.IO) {
                                                    api!!.post(
                                                        "/api/v1/whatsapp/prepare/",
                                                        JSONObject()
                                                            .put("participant_id", person.id)
                                                            .put("template_id", templateId!!),
                                                    )
                                                }
                                                draft = MessageDraft(
                                                    logId = response.getInt("log_id"),
                                                    text = response.getString("message"),
                                                    url = response.getString("whatsapp_url"),
                                                )
                                                notice = "Mensaje preparado. Revísalo antes de abrir WhatsApp."
                                            }
                                        },
                                        modifier = Modifier.fillMaxWidth(),
                                    ) { Text("Preparar invitación por WhatsApp") }
                                }
                            }
                        }
                    }
                    draft?.let { message ->
                        item {
                            Card(Modifier.fillMaxWidth()) {
                                Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                                    Text("Revisa el mensaje", style = MaterialTheme.typography.titleMedium)
                                    Text(message.text)
                                    Button(enabled = !busy, onClick = {
                                        runRequest {
                                            withContext(Dispatchers.IO) {
                                                api!!.post(
                                                    "/api/v1/whatsapp/${message.logId}/status/",
                                                    JSONObject().put("status", "link_opened"),
                                                )
                                            }
                                            context.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(message.url)))
                                            notice = "WhatsApp abierto. Confirma el envío cuando lo hayas enviado."
                                        }
                                    }, modifier = Modifier.fillMaxWidth()) { Text("Abrir WhatsApp") }
                                    OutlinedButton(enabled = !busy, onClick = {
                                        runRequest {
                                            withContext(Dispatchers.IO) {
                                                api!!.post(
                                                    "/api/v1/whatsapp/${message.logId}/status/",
                                                    JSONObject().put("status", "sent"),
                                                )
                                            }
                                            draft = null
                                            notice = "Envío confirmado."
                                        }
                                    }, modifier = Modifier.fillMaxWidth()) { Text("Confirmar que se envió") }
                                    OutlinedButton(onClick = { draft = null }) { Text("Cerrar") }
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}
