package org.edumeeting.llamadas

import android.content.Intent
import android.net.Uri
import android.os.Bundle
import androidx.activity.compose.BackHandler
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.*
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.automirrored.filled.ExitToApp
import androidx.compose.material.icons.automirrored.filled.Send
import androidx.compose.material3.*
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.ui.text.input.VisualTransformation
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.DrawerValue
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalDrawerSheet
import androidx.compose.material3.ModalNavigationDrawer
import androidx.compose.material3.NavigationDrawerItem
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.material3.rememberDrawerState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.key
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONObject
import java.io.IOException

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

private data class ManagedMeeting(
    val id: String,
    val number: Int,
    val name: String,
    val startsAtLocal: String,
    val location: String,
    val active: Boolean,
)

@OptIn(ExperimentalMaterial3Api::class, ExperimentalLayoutApi::class)
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
    var callQueueEmpty by remember { mutableStateOf(false) }
    var callNotes by remember { mutableStateOf("") }
    var query by remember { mutableStateOf("") }
    var nextSearchPage by remember { mutableStateOf<Int?>(null) }
    var lastSearchQuery by remember { mutableStateOf("") }
    var results by remember { mutableStateOf<List<PersonInfo>>(emptyList()) }
    var templates by remember { mutableStateOf<List<Pair<Int, String>>>(emptyList()) }
    var templateId by remember { mutableStateOf<Int?>(null) }
    var draft by remember { mutableStateOf<MessageDraft?>(null) }
    var canCreateMeetings by remember { mutableStateOf(false) }
    var meetingTimezone by remember { mutableStateOf("") }
    var meetingList by remember { mutableStateOf<List<Pair<String, String>>>(emptyList()) }
    var activeMeetingName by remember { mutableStateOf("Sin seleccionar") }
    var activeMeetingId by remember { mutableStateOf<String?>(null) }
    var signedInUsername by remember { mutableStateOf("") }
    var canManage by remember { mutableStateOf(false) }
    var canRegister by remember { mutableStateOf(false) }
    var canOperate by remember { mutableStateOf(false) }
    var meetingNumber by remember { mutableStateOf("") }
    var meetingName by remember { mutableStateOf("") }
    var meetingDay by remember { mutableStateOf("") }
    var meetingTime by remember { mutableStateOf("") }
    var meetingLocation by remember { mutableStateOf("") }
    var managedMeetings by remember { mutableStateOf<List<ManagedMeeting>>(emptyList()) }
    var destination by remember { mutableStateOf(DialDestination.Home) }
    var passwordVisible by remember { mutableStateOf(false) }
    var expandedPersonId by remember { mutableStateOf<String?>(null) }
    val roleWorkspaceState = remember(activeMeetingId, api) { RoleWorkspaceState() }
    var editingMeetingId by remember { mutableStateOf<String?>(null) }
    val preferences = remember { DialPreferences(context) }
    var preferencesLoaded by remember { mutableStateOf(false) }
    val systemDark = isSystemInDarkTheme()
    var darkMode by remember { mutableStateOf(systemDark) }
    val drawerState = rememberDrawerState(DrawerValue.Closed)
    val snackbarHostState = remember { SnackbarHostState() }

    LaunchedEffect(preferences) {
        try {
            val settings = preferences.load()
            darkMode = settings.darkMode ?: systemDark
            serverUrl = settings.serverUrl
        } catch (error: IOException) {
            notice = "No se pudieron leer las preferencias: ${error.message}"
            snackbarHostState.showNotice(notice, AdmonitionKind.Danger)
        } finally {
            preferencesLoaded = true
        }
    }

    fun setDarkMode(enabled: Boolean) {
        if (!preferencesLoaded) return
        scope.launch {
            try {
                preferences.setDarkMode(enabled)
                darkMode = enabled
            } catch (error: IOException) {
                snackbarHostState.showNotice("No se pudo guardar el tema: ${error.message}", AdmonitionKind.Danger)
            }
        }
    }

    fun clearMeetingForm() {
        editingMeetingId = null
        meetingNumber = ""
        meetingName = ""
        meetingDay = ""
        meetingTime = ""
        meetingLocation = ""
    }

    suspend fun loadMeetings(sessionApi: DjangoSessionApi) {
        val payload = withContext(Dispatchers.IO) { sessionApi.get("/api/v1/meetings/") }
        canCreateMeetings = payload.getBoolean("can_create")
        meetingTimezone = payload.getString("timezone")
        val managed = payload.optJSONArray("managed_meetings")
        managedMeetings = if (managed == null) emptyList() else (0 until managed.length()).map { index ->
            val meeting = managed.getJSONObject(index)
            ManagedMeeting(
                id = meeting.getString("id"), number = meeting.getInt("number"),
                name = meeting.getString("name"), startsAtLocal = meeting.getString("starts_at_local"),
                location = meeting.optString("location"), active = meeting.getBoolean("active"),
            )
        }
        val array = payload.getJSONArray("meetings")
        meetingList = (0 until array.length()).map { index ->
            val meeting = array.getJSONObject(index)
            meeting.getString("id") to "${meeting.getInt("number")} · ${meeting.getString("name")}"
        }
        val session = withContext(Dispatchers.IO) { sessionApi.get("/api/v1/session/") }
        signedInUsername = session.getString("username")
        val selected = session.optJSONObject("meeting")
        activeMeetingId = selected?.getString("id")
        sessionApi.meetingId = activeMeetingId
        activeMeetingName = selected?.getString("name") ?: "Sin seleccionar"
        canManage = session.getBoolean("can_manage")
        canRegister = session.getBoolean("can_register")
        canOperate = session.getBoolean("can_operate")
        templates = if (canOperate) {
            withContext(Dispatchers.IO) {
                val array = sessionApi.get("/api/v1/whatsapp/templates/").getJSONArray("templates")
                (0 until array.length()).map { index ->
                    val item = array.getJSONObject(index)
                    item.getInt("id") to item.getString("name")
                }
            }
        } else emptyList()
        templateId = templates.firstOrNull()?.first
    }

    fun runRequest(action: suspend () -> Unit) {
        if (busy) return
        scope.launch {
            busy = true
            val previousNotice = notice
            try {
                action()
                if (notice != previousNotice) {
                    val message = notice
                    launch { snackbarHostState.showNotice(message, AdmonitionKind.Success) }
                }
            } catch (error: Exception) {
                notice = error.message ?: "No se pudo completar la operación."
                val message = notice
                launch { snackbarHostState.showNotice(message, AdmonitionKind.Danger) }
            } finally {
                busy = false
            }
        }
    }

    fun selectMeeting(id: String) {
        runRequest {
            withContext(Dispatchers.IO) {
                api!!.post("/api/v1/meetings/select/", JSONObject().put("meeting_id", id))
            }
            api!!.meetingId = id
            callTask = null
            callQueueEmpty = false
            callNotes = ""
            results = emptyList()
            query = ""
            nextSearchPage = null
            draft = null
            destination = DialDestination.Home
            loadMeetings(api!!)
            notice = "Reunión activa: $activeMeetingName"
        }
    }

    fun refreshSession() {
        runRequest {
            api!!.meetingId = null
            callTask = null
            callQueueEmpty = false
            results = emptyList()
            draft = null
            loadMeetings(api!!)
            notice = "Reuniones y permisos actualizados."
        }
    }

    fun logout() {
        runRequest {
            withContext(Dispatchers.IO) { api!!.logout() }
            api = null
            callTask = null
            callQueueEmpty = false
            results = emptyList()
            draft = null
            canCreateMeetings = false
            meetingList = emptyList()
            activeMeetingId = null
            activeMeetingName = "Sin seleccionar"
            signedInUsername = ""
            canManage = false
            canRegister = false
            canOperate = false
            managedMeetings = emptyList()
            destination = DialDestination.Home
            clearMeetingForm()
            notice = "Sesión cerrada."
        }
    }

    fun closeDrawerThen(action: () -> Unit) {
        scope.launch { drawerState.close() }
        action()
    }


    fun requestNextCall() {
        runRequest {
            val payload = withContext(Dispatchers.IO) {
                api!!.post("/api/v1/calls/next/", JSONObject())
            }
            val raw = payload.optJSONObject("task")
            callQueueEmpty = raw == null
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
    }

    val destinations = buildList {
        add(DialDestination.Home)
        add(DialDestination.Meetings)
        if (canOperate) { add(DialDestination.Calls); add(DialDestination.Search) }
        if (canRegister) add(DialDestination.Register)
        if (canManage) add(DialDestination.Assignments)
        if (canCreateMeetings) add(DialDestination.Manage)
    }
    LaunchedEffect(api, destinations) {
        if (api == null || destination !in destinations) destination = DialDestination.Home
    }
    BackHandler(enabled = api != null || drawerState.isOpen) {
        if (drawerState.isOpen) scope.launch { drawerState.close() }
        else destination = DialDestination.Home
    }

    fun searchPeople(page: Int) {
        runRequest {
            val payload = withContext(Dispatchers.IO) {
                api!!.get("/api/v1/participants/search/?q=${Uri.encode(query.trim())}&page=$page")
            }
            nextSearchPage = if (payload.isNull("next_page")) null else payload.getInt("next_page")
            lastSearchQuery = query
            val array = payload.getJSONArray("results")
            val found = (0 until array.length()).map { index ->
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
            results = if (page == 1) found else (results + found).distinctBy { it.id }
            notice = "${results.size} participante(s) encontrados."
        }
    }

    DialTheme(dark = darkMode) {
        ModalNavigationDrawer(
            drawerState = drawerState,
            gesturesEnabled = api != null,
            drawerContent = {
                ModalDrawerSheet(modifier = Modifier.widthIn(max = 340.dp), drawerContainerColor = MaterialTheme.colorScheme.surface) {
                    Column(Modifier.verticalScroll(rememberScrollState()).padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                        Icon(Icons.Default.Call, null, Modifier.padding(top = 16.dp).size(36.dp), tint = MaterialTheme.colorScheme.primary)
                        Text("EduMeeting Llamadas", style = MaterialTheme.typography.headlineSmall, fontWeight = FontWeight.Bold)
                        Text("Usuario: $signedInUsername", style = MaterialTheme.typography.bodyMedium)
                        Text("Reunión activa: $activeMeetingName", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                        HorizontalDivider(Modifier.padding(vertical = 12.dp))
                        if (api != null) destinations.forEach { screen ->
                            NavigationDrawerItem(
                                label = { Text(screen.title, fontWeight = if (destination == screen) FontWeight.Bold else FontWeight.Normal) },
                                icon = { Icon(screen.icon, null) },
                                selected = destination == screen,
                                shape = RoundedCornerShape(12.dp),
                                colors = NavigationDrawerItemDefaults.colors(
                                    selectedContainerColor = MaterialTheme.colorScheme.primary.copy(alpha = 0.10f),
                                    selectedIconColor = MaterialTheme.colorScheme.primary,
                                    selectedTextColor = MaterialTheme.colorScheme.primary,
                                    unselectedContainerColor = MaterialTheme.colorScheme.surface,
                                ),
                                onClick = { closeDrawerThen { destination = screen } },
                            )
                        }
                        HorizontalDivider(Modifier.padding(vertical = 8.dp))
                        Row(Modifier.fillMaxWidth().padding(horizontal = 12.dp), verticalAlignment = Alignment.CenterVertically) {
                            Icon(Icons.Default.Settings, null)
                            Text("Modo oscuro", Modifier.weight(1f).padding(start = 12.dp))
                            Switch(checked = darkMode, onCheckedChange = ::setDarkMode)
                        }
                        if (api != null) NavigationDrawerItem(
                            label = { Text("Cerrar sesión") },
                            icon = { Icon(Icons.AutoMirrored.Filled.ExitToApp, null) },
                            selected = false, onClick = { closeDrawerThen { logout() } },
                            colors = NavigationDrawerItemDefaults.colors(unselectedTextColor = MaterialTheme.colorScheme.error, unselectedIconColor = MaterialTheme.colorScheme.error),
                        )
                    }
                }
            },
        ) {
            Scaffold(
                snackbarHost = { NoticeSnackbarHost(snackbarHostState) },
                topBar = {
                    if (api != null) Column {
                        TopAppBar(
                            title = {
                                Column {
                                    Text(destination.title, fontWeight = FontWeight.Bold, maxLines = 1, overflow = TextOverflow.Ellipsis)
                                    Text("Reunión activa: $activeMeetingName", style = MaterialTheme.typography.bodySmall, maxLines = 1, overflow = TextOverflow.Ellipsis)
                                }
                            },
                            navigationIcon = {
                                IconButton(onClick = {
                                    if (destination == DialDestination.Home) scope.launch { drawerState.open() }
                                    else destination = DialDestination.Home
                                }) {
                                    Icon(if (destination == DialDestination.Home) Icons.Default.Menu else Icons.AutoMirrored.Filled.ArrowBack,
                                        if (destination == DialDestination.Home) "Abrir menú" else "Volver a Inicio")
                                }
                            },
                            actions = {
                                IconButton(onClick = { setDarkMode(!darkMode) }) {
                                    Icon(Icons.Default.Settings, if (darkMode) "Activar modo claro" else "Activar modo oscuro")
                                }
                            },
                            colors = TopAppBarDefaults.topAppBarColors(containerColor = MaterialTheme.colorScheme.surface, titleContentColor = MaterialTheme.colorScheme.onSurface),
                        )
                        HorizontalDivider(thickness = 1.dp, color = MaterialTheme.colorScheme.outlineVariant)
                    }
                },
            ) { insets ->
                if (api == null) {
                    Box(Modifier.fillMaxSize().padding(insets).imePadding(), contentAlignment = Alignment.Center) {
                        Column(
                            Modifier.widthIn(max = 480.dp).verticalScroll(rememberScrollState()).padding(24.dp),
                            verticalArrangement = Arrangement.spacedBy(20.dp),
                            horizontalAlignment = Alignment.CenterHorizontally,
                        ) {
                            Surface(shape = RoundedCornerShape(20.dp), color = MaterialTheme.colorScheme.primary.copy(alpha = 0.10f)) {
                                Icon(Icons.Default.Call, null, Modifier.padding(20.dp).size(48.dp), tint = MaterialTheme.colorScheme.primary)
                            }
                            Text("EduMeeting Llamadas", style = MaterialTheme.typography.headlineLarge)
                            Text("Conecta con tu comunidad", color = MaterialTheme.colorScheme.onSurfaceVariant)
                            OutlinedCard(Modifier.fillMaxWidth()) {
                                Column(Modifier.padding(20.dp), verticalArrangement = Arrangement.spacedBy(16.dp)) {
                                    Text("Iniciar sesión", style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold)
                                    OutlinedTextField(
                                        value = serverUrl, onValueChange = { serverUrl = it }, label = { Text("URL HTTPS del servidor") },
                                        enabled = preferencesLoaded && !busy,
                                        leadingIcon = { Icon(Icons.Default.Lock, null) }, singleLine = true,
                                        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Uri), modifier = Modifier.fillMaxWidth(),
                                    )
                                    OutlinedTextField(
                                        value = username, onValueChange = { username = it }, label = { Text("Usuario") },
                                        leadingIcon = { Icon(Icons.Default.Person, null) }, singleLine = true, modifier = Modifier.fillMaxWidth(),
                                    )
                                    OutlinedTextField(
                                        value = password, onValueChange = { password = it }, label = { Text("Contraseña") },
                                        leadingIcon = { Icon(Icons.Default.Lock, null) }, singleLine = true,
                                        trailingIcon = { IconButton(onClick = { passwordVisible = !passwordVisible }) {
                                            Icon(if (passwordVisible) Icons.Default.Lock else Icons.Default.Face, if (passwordVisible) "Ocultar contraseña" else "Mostrar contraseña")
                                        } },
                                        visualTransformation = if (passwordVisible) VisualTransformation.None else PasswordVisualTransformation(),
                                        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password), modifier = Modifier.fillMaxWidth(),
                                    )
                                    Button(
                                        enabled = preferencesLoaded && !busy && username.isNotBlank() && password.isNotBlank(),
                                        onClick = {
                                            runRequest {
                                                val sessionApi = withContext(Dispatchers.IO) { DjangoSessionApi(serverUrl).also { it.login(username, password) } }
                                                try {
                                                    preferences.setServerUrl(serverUrl)
                                                } catch (error: IOException) {
                                                    scope.launch {
                                                        snackbarHostState.showNotice("No se pudo guardar la URL: ${error.message}", AdmonitionKind.Danger)
                                                    }
                                                }
                                                api = sessionApi
                                                password = ""
                                                passwordVisible = false
                                                loadMeetings(sessionApi)
                                                notice = "Sesión iniciada. Las acciones se validan con los permisos de tu cuenta."
                                            }
                                        }, modifier = Modifier.fillMaxWidth().heightIn(min = 52.dp),
                                    ) { ActionLabel(if (busy) "Conectando…" else "Iniciar sesión", Icons.Default.Lock) }
                                    Text("Usa HTTPS con certificado válido. Las credenciales no se guardan en el dispositivo.", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                                }
                            }
                            TextButton(onClick = { setDarkMode(!darkMode) }) { ActionLabel(if (darkMode) "Modo claro" else "Modo oscuro", Icons.Default.Settings) }
                        }
                    }
                } else key(destination) {
                    LazyColumn(
                        modifier = Modifier.fillMaxSize().padding(insets).imePadding(),
                        verticalArrangement = Arrangement.spacedBy(16.dp),
                        contentPadding = PaddingValues(16.dp),
                    ) {
                        if (busy) item { LinearProgressIndicator(Modifier.fillMaxWidth()) }
                        when (destination) {
                            DialDestination.Home -> item {
                                WorkspaceHome(
                                    username = signedInUsername, meeting = activeMeetingName,
                                    roles = buildList {
                                        if (canCreateMeetings || canManage) add("Administrador de reuniones")
                                        if (canRegister) add("Registrador de participantes")
                                        if (canOperate) add("Operador de llamadas")
                                        if (isEmpty()) add("Sin rol en la reunión activa")
                                    },
                                    destinations = destinations, navigate = { destination = it },
                                )
                            }
                            DialDestination.Meetings -> {
                                item {
                                    Text("Tus reuniones", style = MaterialTheme.typography.headlineLarge)
                                    Text("Toca una tarjeta para trabajar en esa reunión.", color = MaterialTheme.colorScheme.onSurfaceVariant)
                                    OutlinedButton(enabled = !busy, onClick = ::refreshSession, modifier = Modifier.padding(top = 12.dp)) { ActionLabel("Actualizar", Icons.Default.Refresh) }
                                }
                                if (meetingList.isEmpty()) item {
                                    EmptyState(Icons.Default.DateRange, "Sin reuniones disponibles", "Solicita una asignación o crea una reunión si eres administrador.") {
                                        if (canCreateMeetings) Button(onClick = { destination = DialDestination.Manage }) { ActionLabel("Crear reunión", Icons.Default.Add) }
                                    }
                                }
                                items(meetingList, key = { it.first }) { (id, label) ->
                                    val selected = id == activeMeetingId
                                    OutlinedCard(
                                        onClick = { if (!busy && !selected) selectMeeting(id) },
                                        modifier = Modifier.fillMaxWidth(),
                                        border = BorderStroke(1.dp, if (selected) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.outline),
                                        colors = CardDefaults.outlinedCardColors(containerColor = if (selected) MaterialTheme.colorScheme.primary.copy(alpha = 0.07f) else MaterialTheme.colorScheme.surface),
                                    ) {
                                        ListItem(
                                            headlineContent = { Text(label, fontWeight = FontWeight.Bold) },
                                            supportingContent = { Text(if (selected) "Reunión activa" else "Toca para seleccionar") },
                                            leadingContent = { Icon(Icons.Default.DateRange, null, tint = MaterialTheme.colorScheme.primary) },
                                            trailingContent = { if (selected) Icon(Icons.Default.CheckCircle, "Seleccionada", tint = MaterialTheme.colorScheme.primary) },
                                            colors = ListItemDefaults.colors(containerColor = Color.Transparent),
                                        )
                                    }
                                }
                            }
                            DialDestination.Manage -> if (canCreateMeetings) item {
                                DocSection("Gestionar reuniones") {
                                    val editing = managedMeetings.firstOrNull { it.id == editingMeetingId }
                                    Text(
                                        if (editing == null) "Crear reunión nueva" else "Editar reunión ${editing.number}",
                                        style = MaterialTheme.typography.titleMedium,
                                    )
                                    Text(
                                        if (editing == null) "Serás su único administrador. Luego selecciónala para asignar usuarios y ver estadísticas."
                                        else "Los cambios se aplican a todos los usuarios asignados."
                                    )
                                    OutlinedButton(enabled = !busy, onClick = { clearMeetingForm() }) { ActionLabel("Nueva reunión", Icons.Default.Add) }
                                    Text("Zona horaria del servidor: $meetingTimezone", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                                    OutlinedTextField(
                                        value = meetingNumber, onValueChange = { meetingNumber = it },
                                        label = { Text("Número (1–99, único por día)") }, singleLine = true,
                                        leadingIcon = { Icon(Icons.Default.Info, null) },
                                        supportingText = { Text("Puede repetirse en reuniones de otra fecha.") },
                                        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                                        modifier = Modifier.fillMaxWidth(),
                                    )
                                    OutlinedTextField(
                                        value = meetingName, onValueChange = { meetingName = it },
                                        label = { Text("Nombre de la reunión") }, singleLine = true,
                                        leadingIcon = { Icon(Icons.Default.Edit, null) },
                                        modifier = Modifier.fillMaxWidth(),
                                    )
                                    MeetingDateTimePickers(
                                        day = meetingDay, time = meetingTime, enabled = !busy,
                                        onDayChange = { meetingDay = it }, onTimeChange = { meetingTime = it },
                                    )
                                    AttendanceCodePreview(number = meetingNumber, day = meetingDay)
                                    OutlinedTextField(
                                        value = meetingLocation, onValueChange = { meetingLocation = it },
                                        label = { Text("Lugar (opcional)") }, singleLine = true,
                                        leadingIcon = { Icon(Icons.Default.Place, null) },
                                        modifier = Modifier.fillMaxWidth(),
                                    )
                                    Button(
                                        enabled = !busy && (meetingNumber.toIntOrNull() ?: 0) in 1..99 &&
                                            meetingName.isNotBlank() && meetingDay.isNotBlank() && meetingTime.isNotBlank(),
                                        onClick = {
                                            runRequest {
                                                val body = JSONObject()
                                                    .put("number", meetingNumber)
                                                    .put("name", meetingName)
                                                    .put("starts_at", "$meetingDay $meetingTime")
                                                    .put("location", meetingLocation)
                                                val path = if (editing == null) "/api/v1/meetings/" else "/api/v1/meetings/${editing.id}/"
                                                withContext(Dispatchers.IO) { api!!.post(path, body) }
                                                notice = if (editing == null) "Reunión creada sin participantes." else "Reunión actualizada."
                                                clearMeetingForm()
                                                loadMeetings(api!!)
                                            }
                                        },
                                        modifier = Modifier.fillMaxWidth(),
                                    ) { ActionLabel(if (editing == null) "Crear reunión" else "Guardar cambios", if (editing == null) Icons.Default.Add else Icons.Default.Check) }
                                    if (editing != null) {
                                        OutlinedButton(enabled = !busy, onClick = { clearMeetingForm() }) {
                                            ActionLabel("Cancelar edición", Icons.Default.Close)
                                        }
                                    }
                                    HorizontalDivider(Modifier.padding(vertical = 12.dp))
                                    Text("Mis reuniones", style = MaterialTheme.typography.titleLarge)
                                    if (managedMeetings.isEmpty()) EmptyState(Icons.Default.DateRange, "Aún no hay reuniones", "Completa el formulario para crear la primera reunión.")
                                    managedMeetings.forEach { meeting ->
                                        OutlinedCard(Modifier.fillMaxWidth()) {
                                            Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                                                Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                                                    Icon(Icons.Default.DateRange, null, tint = MaterialTheme.colorScheme.primary)
                                                    Text("${meeting.number} · ${meeting.name}", Modifier.weight(1f), style = MaterialTheme.typography.titleMedium)
                                                    Icon(if (meeting.active) Icons.Default.CheckCircle else Icons.Default.Close, if (meeting.active) "Activa" else "Inactiva", tint = MaterialTheme.colorScheme.onSurfaceVariant)
                                                }
                                                Text(meeting.startsAtLocal, style = MaterialTheme.typography.bodyMedium)
                                                Text(meeting.location.ifBlank { "Sin lugar" }, color = MaterialTheme.colorScheme.onSurfaceVariant)
                                                Text(if (meeting.active) "Activa" else "Inactiva", style = MaterialTheme.typography.labelLarge)
                                                HorizontalDivider()
                                                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.End) {
                                                    TextButton(enabled = !busy, onClick = {
                                                        editingMeetingId = meeting.id
                                                        meetingNumber = meeting.number.toString()
                                                        meetingName = meeting.name
                                                        meetingDay = meeting.startsAtLocal.substringBefore(" ")
                                                        meetingTime = meeting.startsAtLocal.substringAfter(" ", "")
                                                        meetingLocation = meeting.location
                                                    }) { ActionLabel("Editar", Icons.Default.Edit) }
                                                    TextButton(enabled = !busy, onClick = {
                                                        runRequest {
                                                            withContext(Dispatchers.IO) {
                                                                api!!.post("/api/v1/meetings/${meeting.id}/", JSONObject().put("active", !meeting.active))
                                                            }
                                                            notice = if (meeting.active) "Reunión desactivada." else "Reunión activada."
                                                            if (editingMeetingId == meeting.id) clearMeetingForm()
                                                            loadMeetings(api!!)
                                                        }
                                                    }) { ActionLabel(if (meeting.active) "Desactivar" else "Activar", if (meeting.active) Icons.Default.Close else Icons.Default.CheckCircle) }
                                                }
                                            }
                                        }
                                    }
                                }
                            }
                            DialDestination.Register, DialDestination.Assignments -> item {
                                if (activeMeetingId == null) EmptyState(Icons.Default.DateRange, "Selecciona una reunión", "Elige una reunión antes de continuar.") {
                                    Button(onClick = { destination = DialDestination.Meetings }) { ActionLabel("Ver reuniones", Icons.Default.DateRange) }
                                } else key(activeMeetingId) {
                                    RoleWorkspace(
                                        api = api!!, canManage = canManage && destination == DialDestination.Assignments,
                                        canRegister = canRegister && destination == DialDestination.Register,
                                        busy = busy, runRequest = ::runRequest, onNotice = { notice = it }, state = roleWorkspaceState,
                                    )
                                }
                            }
                            DialDestination.Calls -> if (canOperate) item {
                                Column(verticalArrangement = Arrangement.spacedBy(16.dp)) {
                                    Text("Una conversación a la vez", style = MaterialTheme.typography.headlineLarge)
                                    Button(enabled = !busy && callTask == null, modifier = Modifier.fillMaxWidth().heightIn(min = 56.dp), onClick = ::requestNextCall) {
                                        ActionLabel(if (busy) "Consultando…" else "Solicitar siguiente llamada", Icons.Default.Call)
                                    }
                                    if (callTask == null) EmptyState(
                                        Icons.Default.Call,
                                        if (callQueueEmpty) "No hay llamadas disponibles" else "Listo para llamar",
                                        if (callQueueEmpty) "La cola está vacía por ahora. Puedes volver a consultar." else "Solicita una llamada y registra el resultado al terminar.",
                                    ) {
                                        if (callQueueEmpty) OutlinedButton(enabled = !busy, onClick = ::requestNextCall) { ActionLabel("Volver a consultar", Icons.Default.Refresh) }
                                    }
                                    callTask?.let { task ->
                                        OutlinedCard(Modifier.fillMaxWidth()) {
                                            Column(Modifier.padding(20.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
                                                Icon(Icons.Default.AccountCircle, null, Modifier.size(48.dp), tint = MaterialTheme.colorScheme.primary)
                                                Text(task.name, style = MaterialTheme.typography.headlineSmall, fontWeight = FontWeight.Bold)
                                                Text(task.phone.ifBlank { "Sin teléfono" }, style = MaterialTheme.typography.titleLarge)
                                                Text("Reunión: ${task.meeting}")
                                                Text("Origen: ${task.origin}", color = MaterialTheme.colorScheme.onSurfaceVariant)
                                                if (task.phone.isNotBlank()) Button(onClick = {
                                                    context.startActivity(Intent(Intent.ACTION_DIAL, Uri.parse("tel:${Uri.encode(task.phone)}")))
                                                }, modifier = Modifier.fillMaxWidth().heightIn(min = 56.dp)) { ActionLabel("Llamar", Icons.Default.Call) }
                                                if (task.history.isNotEmpty()) {
                                                    HorizontalDivider()
                                                    Text("Historial", fontWeight = FontWeight.Bold)
                                                    task.history.forEach { Text(it, style = MaterialTheme.typography.bodySmall) }
                                                }
                                                OutlinedTextField(value = callNotes, onValueChange = { callNotes = it }, label = { Text("Notas de la llamada") }, leadingIcon = { Icon(Icons.Default.Edit, null) }, modifier = Modifier.fillMaxWidth())
                                                Text("Resultado de la llamada", fontWeight = FontWeight.Bold)
                                                OutcomeGrid(
                                                    options = listOf("accepted" to "Aceptó", "declined" to "Rechazó", "contacted" to "Contactado", "no_answer" to "No contesta", "follow_up" to "Seguimiento", "do_not_contact" to "No contactar", "other" to "Otro"),
                                                    enabled = !busy,
                                                ) { outcome ->
                                                    runRequest {
                                                        val response = withContext(Dispatchers.IO) {
                                                            api!!.post("/api/v1/calls/${task.id}/result/", JSONObject().put("outcome", outcome).put("notes", callNotes))
                                                        }
                                                        notice = response.optString("code").takeIf { it.isNotBlank() }?.let { "Aceptación registrada. Código: $it" } ?: "Resultado de llamada guardado."
                                                        callTask = null
                                                        callQueueEmpty = false
                                                    }
                                                }
                                            }
                                        }
                                    }
                                }
                            }
                            DialDestination.Search -> if (canOperate) {
                                item {
                                    Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
                                        OutlinedTextField(
                                            value = query, onValueChange = { query = it }, label = { Text("Nombre o teléfono") },
                                            supportingText = { Text("Deja vacío para listar participantes") },
                                            leadingIcon = { Icon(Icons.Default.Search, null) },
                                            trailingIcon = { if (query.isNotEmpty()) IconButton(onClick = { query = "" }) { Icon(Icons.Default.Clear, "Limpiar búsqueda") } },
                                            singleLine = true, modifier = Modifier.fillMaxWidth(),
                                        )
                                        Button(enabled = !busy, onClick = { searchPeople(1) }, modifier = Modifier.fillMaxWidth()) { ActionLabel("Buscar participantes", Icons.Default.Search) }
                                        if (templates.isNotEmpty()) {
                                            Text("Plantilla de WhatsApp", style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.Bold)
                                            FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                                                templates.forEach { (id, name) ->
                                                    FilterChip(selected = templateId == id, onClick = { templateId = id }, label = { Text(name) }, leadingIcon = { Icon(if (templateId == id) Icons.Default.Check else Icons.Default.Share, null, Modifier.size(18.dp)) }, modifier = Modifier.heightIn(min = 48.dp))
                                                }
                                            }
                                        }
                                    }
                                }
                                if (results.isEmpty()) item { EmptyState(Icons.Default.Search, "Sin resultados", "Busca por nombre o teléfono, o deja el campo vacío para ver la lista.") }
                                items(results, key = { it.id }) { person ->
                                    val expanded = expandedPersonId == person.id
                                    OutlinedCard(onClick = { expandedPersonId = if (expanded) null else person.id }, modifier = Modifier.fillMaxWidth()) {
                                        ListItem(
                                            headlineContent = { Text(person.name, fontWeight = FontWeight.Bold) },
                                            supportingContent = {
                                                Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
                                                    Text(person.phone.ifBlank { "Sin teléfono" })
                                                    Surface(shape = RoundedCornerShape(6.dp), color = if (person.doNotContact) MaterialTheme.colorScheme.errorContainer else MaterialTheme.colorScheme.surfaceVariant) {
                                                        Text(if (person.doNotContact) "NO CONTACTAR" else person.invitationStatus.ifBlank { "Sin invitación" }, Modifier.padding(horizontal = 8.dp, vertical = 4.dp), style = MaterialTheme.typography.labelSmall)
                                                    }
                                                    Text(if (expanded) "Ocultar opciones" else "Ver opciones", style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.primary)
                                                }
                                            },
                                            leadingContent = {
                                                Surface(shape = CircleShape, color = MaterialTheme.colorScheme.primary.copy(alpha = 0.10f)) {
                                                    Text(person.name.split(" ").filter { it.isNotBlank() }.take(2).map { it.first().uppercaseChar() }.joinToString(""), Modifier.padding(12.dp), fontWeight = FontWeight.Bold, color = MaterialTheme.colorScheme.primary)
                                                }
                                            },
                                            trailingContent = {
                                                IconButton(enabled = person.phone.isNotBlank() && person.authorized && !person.doNotContact, onClick = {
                                                    context.startActivity(Intent(Intent.ACTION_DIAL, Uri.parse("tel:${Uri.encode(person.phone)}")))
                                                }) { Icon(Icons.Default.Call, "Llamar a ${person.name}", tint = if (person.authorized && !person.doNotContact) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.onSurfaceVariant) }
                                            },
                                            colors = ListItemDefaults.colors(containerColor = Color.Transparent),
                                        )
                                        if (expanded) Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
                                            HorizontalDivider()
                                            if (person.originId != null) {
                                                Text("Registrar contacto entrante", fontWeight = FontWeight.Bold)
                                                OutcomeGrid(listOf("contacted" to "Contactado", "accepted" to "Aceptó", "declined" to "Rechazó", "follow_up" to "Seguimiento", "do_not_contact" to "No contactar", "other" to "Otro"), !busy) { outcome ->
                                                    runRequest {
                                                        val response = withContext(Dispatchers.IO) {
                                                            api!!.post("/api/v1/calls/inbound/", JSONObject().put("participant_id", person.id).put("outcome", outcome))
                                                        }
                                                        notice = response.optString("code").takeIf(String::isNotBlank)?.let { "Aceptación registrada. Código: $it" } ?: "Contacto entrante registrado."
                                                    }
                                                }
                                            }
                                            if (!person.doNotContact && person.authorized && person.phone.isNotBlank() && templateId != null) {
                                                OutlinedButton(enabled = !busy, onClick = {
                                                    runRequest {
                                                        val response = withContext(Dispatchers.IO) {
                                                            api!!.post("/api/v1/whatsapp/prepare/", JSONObject().put("participant_id", person.id).put("template_id", templateId!!))
                                                        }
                                                        draft = MessageDraft(response.getInt("log_id"), response.getString("message"), response.getString("whatsapp_url"))
                                                        notice = "Mensaje preparado. Revísalo antes de abrir WhatsApp."
                                                    }
                                                }, modifier = Modifier.fillMaxWidth()) { ActionLabel("Preparar WhatsApp", Icons.Default.Share) }
                                            }
                                        }
                                    }
                                }
                                nextSearchPage?.let { page -> item {
                                    OutlinedButton(enabled = !busy && query == lastSearchQuery, onClick = { searchPeople(page) }, modifier = Modifier.fillMaxWidth()) { ActionLabel("Ver más participantes", Icons.Default.Add) }
                                } }
                            }
                        }
                    }
                }
            }
            if (api != null && canOperate) draft?.let { message ->
                AlertDialog(
                    onDismissRequest = { if (!busy) draft = null },
                    icon = { Icon(Icons.AutoMirrored.Filled.Send, null) },
                    title = { Text("Revisa el mensaje") },
                    text = {
                        Column(Modifier.verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(12.dp)) {
                            Text(message.text)
                            Button(enabled = !busy, onClick = {
                                runRequest {
                                    withContext(Dispatchers.IO) { api!!.post("/api/v1/whatsapp/${message.logId}/status/", JSONObject().put("status", "link_opened")) }
                                    context.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(message.url)))
                                    notice = "WhatsApp abierto. Confirma el envío cuando lo hayas enviado."
                                }
                            }, modifier = Modifier.fillMaxWidth()) { ActionLabel("Abrir WhatsApp", Icons.Default.Share) }
                        }
                    },
                    confirmButton = {
                        TextButton(enabled = !busy, onClick = {
                            runRequest {
                                withContext(Dispatchers.IO) { api!!.post("/api/v1/whatsapp/${message.logId}/status/", JSONObject().put("status", "sent")) }
                                draft = null
                                notice = "Envío confirmado."
                            }
                        }) { ActionLabel("Confirmar envío", Icons.Default.Check) }
                    },
                    dismissButton = { TextButton(enabled = !busy, onClick = { draft = null }) { Text("Cerrar") } },
                )
            }
        }
    }
}
