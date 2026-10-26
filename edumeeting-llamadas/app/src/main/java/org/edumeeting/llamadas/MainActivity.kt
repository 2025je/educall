package org.edumeeting.llamadas

import org.edumeeting.ui.*
import android.content.Intent
import android.net.Uri
import android.os.Bundle
import androidx.activity.compose.BackHandler
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.BorderStroke
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
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.ui.focus.FocusDirection
import androidx.compose.ui.platform.LocalFocusManager
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardCapitalization
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
    val purpose: String = PHASE_INVITATION,
    val queueType: String = "",
    val scheduleId: String? = null,
    val scheduleLabel: String = "",
    val schedules: List<ScheduleOption> = emptyList(),
)

private data class PersonInfo(
    val id: String,
    val name: String,
    val phone: String,
    val originId: String?,
    val doNotContact: Boolean,
    val authorized: Boolean,
    val invitationStatus: String,
    val scheduleId: String? = null,
    val scheduleLabel: String = "",
    val confirmation: String = "",
)

private data class MessageDraft(val logId: Int, val text: String, val url: String)


@OptIn(ExperimentalMaterial3Api::class, ExperimentalLayoutApi::class)
@Composable
private fun DialScreen() {
    val context = LocalContext.current
    val focusManager = LocalFocusManager.current
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
    var isSuperuser by remember { mutableStateOf(false) }
    val superuserState = remember(api) { SuperuserState() }
    var canManage by remember { mutableStateOf(false) }
    var canRegister by remember { mutableStateOf(false) }
    var canOperate by remember { mutableStateOf(false) }
    var meetingName by remember { mutableStateOf("") }
    var meetingLocation by remember { mutableStateOf("") }
    var meetingSchedules by remember { mutableStateOf(listOf(ScheduleDraft())) }
    var meetingQueue by remember { mutableStateOf(QueueSettings()) }
    var meetingPhase by remember { mutableStateOf(PHASE_INVITATION) }
    var activePhase by remember { mutableStateOf(PHASE_INVITATION) }
    var schedulesByMeeting by remember { mutableStateOf<Map<String, List<ScheduleOption>>>(emptyMap()) }
    var queueTypes by remember { mutableStateOf(QUEUE_TYPE_LABELS.keys.toSet()) }
    var callSchedule by remember { mutableStateOf<String?>(null) }
    var callFollowUp by remember { mutableStateOf("") }
    var nextAvailableLabel by remember { mutableStateOf("") }
    var inboundSchedule by remember { mutableStateOf<String?>(null) }
    var managedMeetings by remember { mutableStateOf<List<ManagedMeeting>>(emptyList()) }
    var destination by remember { mutableStateOf(DialDestination.Home) }
    var expandedPersonId by remember { mutableStateOf<String?>(null) }
    val roleWorkspaceState = remember(activeMeetingId, api) { RoleWorkspaceState() }
    var editingMeetingId by remember { mutableStateOf<String?>(null) }
    val preferences = remember { DialPreferences(context) }
    var preferencesLoaded by remember { mutableStateOf(false) }
    val drawerState = rememberDrawerState(DrawerValue.Closed)
    val snackbarHostState = remember { SnackbarHostState() }

    LaunchedEffect(preferences) {
        try {
            serverUrl = preferences.load().serverUrl
            preferences.legacyDarkMode()?.let { dark ->
                ThemePreferences(context).adoptLegacy(if (dark) ThemeMode.Dark else ThemeMode.Light)
                preferences.clearLegacyDarkMode()
            }
        } catch (error: IOException) {
            notice = "No se pudieron leer las preferencias: ${error.message}"
            snackbarHostState.showNotice(notice, AdmonitionKind.Danger)
        } finally {
            preferencesLoaded = true
        }
    }

    fun clearMeetingForm() {
        editingMeetingId = null
        meetingName = ""
        meetingLocation = ""
        meetingSchedules = listOf(ScheduleDraft())
        meetingQueue = QueueSettings()
        meetingPhase = PHASE_INVITATION
    }

    suspend fun loadMeetings(sessionApi: DjangoSessionApi) {
        val payload = withContext(Dispatchers.IO) { sessionApi.get("/api/v1/meetings/") }
        canCreateMeetings = payload.getBoolean("can_create")
        meetingTimezone = payload.getString("timezone")
        val managed = payload.optJSONArray("managed_meetings")
        managedMeetings = if (managed == null) emptyList() else (0 until managed.length()).map { index ->
            parseManagedMeeting(managed.getJSONObject(index))
        }
        val array = payload.getJSONArray("meetings")
        val meetings = (0 until array.length()).map { array.getJSONObject(it) }
        meetingList = meetings.map { meeting ->
            val phase = PHASE_LABELS[meeting.optString("call_phase")]?.substringBefore(" ·")
            meeting.getString("id") to listOfNotNull(meeting.getString("name"), phase).joinToString(" · ")
        }
        val session = withContext(Dispatchers.IO) { sessionApi.get("/api/v1/session/") }
        signedInUsername = session.getString("username")
        val selected = session.optJSONObject("meeting")
        activeMeetingId = selected?.getString("id")
        val activeMeeting = meetings.firstOrNull { it.getString("id") == activeMeetingId }
        activePhase = activeMeeting?.optString("call_phase")?.ifBlank { null } ?: PHASE_INVITATION
        schedulesByMeeting = meetings.associate { it.getString("id") to scheduleOptions(it) }
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
            isSuperuser = false
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
            val body = JSONObject()
            if (activePhase == PHASE_CONFIRMATION) body.put("types", org.json.JSONArray(queueTypes.toList()))
            val payload = withContext(Dispatchers.IO) {
                api!!.post("/api/v1/calls/next/", body)
            }
            payload.optString("call_phase").takeIf { it.isNotBlank() }?.let { activePhase = it }
            nextAvailableLabel = payload.optString("next_available_label").takeIf { it.isNotBlank() && it != "null" }.orEmpty()
            val raw = payload.optJSONObject("task")
            callQueueEmpty = raw == null
            callTask = raw?.let {
                val person = it.getJSONObject("participant")
                val taskMeeting = it.getJSONObject("meeting")
                CallTaskInfo(
                    purpose = it.optString("purpose", PHASE_INVITATION).ifBlank { PHASE_INVITATION },
                    queueType = it.optString("queue_type"),
                    scheduleId = person.optString("schedule_id").takeIf { id -> id.isNotBlank() && id != "null" },
                    scheduleLabel = person.optString("schedule_label").takeIf { label -> label != "null" }.orEmpty(),
                    schedules = parseScheduleOptions(taskMeeting.optJSONArray("schedules")),
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
            notice = when {
                callTask != null -> "Llamada asignada. Registra el resultado al terminar."
                nextAvailableLabel.isNotBlank() -> "No hay llamadas ahora. La próxima estará disponible a las $nextAvailableLabel."
                else -> "No hay llamadas disponibles en este momento."
            }
            callNotes = ""
            callSchedule = callTask?.scheduleId
            callFollowUp = ""
        }
    }

    val destinations = buildList {
        add(DialDestination.Home)
        if (isSuperuser) {
            add(DialDestination.Statistics)
            add(DialDestination.Users)
            return@buildList
        }
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
                    scheduleId = item.optString("schedule_id").takeIf { it.isNotBlank() && it != "null" },
                    scheduleLabel = item.optString("schedule_label").takeIf { it != "null" }.orEmpty(),
                    confirmation = item.optString("attendance_confirmation").takeIf { it != "null" }.orEmpty(),
                )
            }
            results = if (page == 1) found else (results + found).distinctBy { it.id }
            notice = "${results.size} participante(s) encontrados."
        }
    }

    EduMeetingTheme { theme ->
        ModalNavigationDrawer(
            drawerState = drawerState,
            gesturesEnabled = api != null,
            drawerContent = {
                ModalDrawerSheet(modifier = Modifier.widthIn(max = 340.dp), drawerContainerColor = MaterialTheme.colorScheme.surface) {
                    Column(Modifier.verticalScroll(rememberScrollState()).padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                        Icon(Icons.Default.Call, null, Modifier.padding(top = 16.dp).size(36.dp), tint = MaterialTheme.colorScheme.primary)
                        Text("EduMeeting Llamadas", style = MaterialTheme.typography.headlineSmall, fontWeight = FontWeight.Bold)
                        Text("Usuario: $signedInUsername", style = MaterialTheme.typography.bodyMedium)
                        Text(
                            if (isSuperuser) "Superusuario: usuarios y estadísticas" else "Reunión activa: $activeMeetingName",
                            style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
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
                        Text(
                            "Apariencia",
                            style = MaterialTheme.typography.labelMedium,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                            modifier = Modifier.padding(start = 16.dp),
                        )
                        NavigationDrawerItem(
                            label = { Text(if (theme.dark) "Tema claro" else "Tema oscuro") },
                            icon = { ThemeGlyph(theme.dark) },
                            selected = false,
                            shape = RoundedCornerShape(12.dp),
                            onClick = theme.toggle,
                        )
                        NavigationDrawerItem(
                            label = { Text("Tema según el sistema", fontWeight = if (theme.followsSystem) FontWeight.Bold else FontWeight.Normal) },
                            icon = { Icon(Icons.Default.Settings, null) },
                            selected = theme.followsSystem,
                            shape = RoundedCornerShape(12.dp),
                            colors = NavigationDrawerItemDefaults.colors(
                                selectedContainerColor = MaterialTheme.colorScheme.primary.copy(alpha = 0.10f),
                                selectedIconColor = MaterialTheme.colorScheme.primary,
                                selectedTextColor = MaterialTheme.colorScheme.primary,
                                unselectedContainerColor = MaterialTheme.colorScheme.surface,
                            ),
                            onClick = theme.followSystem,
                        )
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
                                    Text(
                                        if (isSuperuser) "Superusuario" else "Reunión activa: $activeMeetingName",
                                        style = MaterialTheme.typography.bodySmall, maxLines = 1, overflow = TextOverflow.Ellipsis,
                                    )
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
                                IconButton(onClick = theme.toggle) {
                                    ThemeGlyph(theme.dark, if (theme.dark) "Activar tema claro" else "Activar tema oscuro")
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
                                    val canLogin = preferencesLoaded && !busy && username.isNotBlank() && password.isNotBlank()
                                    val submitLogin = {
                                        focusManager.clearFocus()
                                        runRequest {
                                            val sessionApi = withContext(Dispatchers.IO) { DjangoSessionApi(serverUrl).also { it.login(username, password) } }
                                            val account = withContext(Dispatchers.IO) { sessionApi.get("/api/v1/session/") }
                                            try {
                                                preferences.setServerUrl(serverUrl)
                                            } catch (error: IOException) {
                                                scope.launch {
                                                    snackbarHostState.showNotice("No se pudo guardar la URL: ${error.message}", AdmonitionKind.Danger)
                                                }
                                            }
                                            if (account.optBoolean("is_superuser")) {
                                                signedInUsername = account.getString("username")
                                                isSuperuser = true
                                                api = sessionApi
                                                password = ""
                                                notice = "Sesión de superusuario: gestiona usuarios y consulta estadísticas."
                                                return@runRequest
                                            }
                                            api = sessionApi
                                            password = ""
                                            loadMeetings(sessionApi)
                                            notice = "Sesión iniciada. Las acciones se validan con los permisos de tu cuenta."
                                        }
                                    }
                                    FormTextField(
                                        value = serverUrl, onValueChange = { serverUrl = it }, label = "URL HTTPS del servidor",
                                        enabled = preferencesLoaded && !busy, leadingIcon = Icons.Default.Lock,
                                        keyboardType = KeyboardType.Uri, modifier = Modifier.fillMaxWidth(),
                                    )
                                    FormTextField(
                                        value = username, onValueChange = { username = it }, label = "Usuario",
                                        leadingIcon = Icons.Default.Person, modifier = Modifier.fillMaxWidth(),
                                    )
                                    PasswordField(
                                        value = password, onValueChange = { password = it },
                                        imeAction = ImeAction.Go, onSubmit = { if (canLogin) submitLogin() },
                                        modifier = Modifier.fillMaxWidth(),
                                    )
                                    Button(
                                        enabled = canLogin,
                                        onClick = { submitLogin() }, modifier = Modifier.fillMaxWidth().heightIn(min = 52.dp),
                                    ) { ActionLabel(if (busy) "Conectando…" else "Iniciar sesión", Icons.Default.Lock) }
                                    Text("Usa HTTPS con certificado válido. Las credenciales no se guardan en el dispositivo.", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                                }
                            }
                            TextButton(onClick = theme.toggle) {
                                ThemeGlyph(theme.dark)
                                Spacer(Modifier.width(8.dp))
                                Text(if (theme.dark) "Tema claro" else "Tema oscuro")
                            }
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
                            DialDestination.Home -> if (isSuperuser) item {
                                SuperuserHome(username = signedInUsername, navigate = { destination = it })
                            } else item {
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
                                    EmptyState(
                                        Icons.Default.DateRange,
                                        "Sin reuniones disponibles",
                                        "Solicita una asignación o crea una reunión si eres administrador.",
                                        actionLabel = if (canCreateMeetings) "Crear reunión" else null,
                                        actionIcon = Icons.Default.Add,
                                        onAction = { destination = DialDestination.Manage },
                                    )
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
                                        if (editing == null) "Crear reunión nueva" else "Editar reunión «${editing.name}»",
                                        style = MaterialTheme.typography.titleMedium,
                                    )
                                    Text(
                                        if (editing == null) "Serás su único administrador. Luego selecciónala para asignar usuarios y ver estadísticas."
                                        else "Los cambios se aplican a todos los usuarios asignados."
                                    )
                                    OutlinedButton(enabled = !busy, onClick = { clearMeetingForm() }) { ActionLabel("Nueva reunión", Icons.Default.Add) }
                                    Text("Zona horaria del servidor: $meetingTimezone", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                                    FormTextField(
                                        value = meetingName, onValueChange = { meetingName = it },
                                        label = "Nombre de la reunión", leadingIcon = Icons.Default.Edit,
                                        capitalization = KeyboardCapitalization.Sentences,
                                        modifier = Modifier.fillMaxWidth(),
                                    )
                                    FormTextField(
                                        value = meetingLocation, onValueChange = { meetingLocation = it },
                                        label = "Lugar (opcional)", leadingIcon = Icons.Default.Place,
                                        capitalization = KeyboardCapitalization.Sentences,
                                        imeAction = ImeAction.Done, modifier = Modifier.fillMaxWidth(),
                                    )
                                    ScheduleListEditor(meetingSchedules, enabled = !busy, onChange = { meetingSchedules = it })
                                    if (editing != null) CallPhaseSelector(meetingPhase, enabled = !busy, onChange = { meetingPhase = it })
                                    QueueSettingsEditor(meetingQueue, enabled = !busy, onChange = { meetingQueue = it })
                                    val problem = scheduleProblem(meetingSchedules)
                                    if (problem != null) Text(problem, color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.bodySmall)
                                    if (!meetingQueue.valid) Text("Revisa las reglas de la cola: hay valores fuera de rango.", color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.bodySmall)
                                    Button(
                                        enabled = !busy && meetingName.isNotBlank() && problem == null && meetingQueue.valid,
                                        onClick = {
                                            runRequest {
                                                val body = meetingRequestBody(
                                                    meetingName, meetingLocation, meetingSchedules, meetingQueue,
                                                    callPhase = if (editing == null) null else meetingPhase,
                                                )
                                                val path = if (editing == null) "/api/v1/meetings/" else "/api/v1/meetings/${editing.id}/"
                                                withContext(Dispatchers.IO) { api!!.post(path, body) }
                                                notice = when {
                                                    editing == null -> "Reunión creada sin participantes."
                                                    editing.callPhase != meetingPhase && meetingPhase == PHASE_CONFIRMATION ->
                                                        "Reunión en fase 2: se generaron las llamadas de confirmación."
                                                    else -> "Reunión actualizada."
                                                }
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
                                                    Text(meeting.name, Modifier.weight(1f), style = MaterialTheme.typography.titleMedium)
                                                    Icon(if (meeting.active) Icons.Default.CheckCircle else Icons.Default.Close, if (meeting.active) "Activa" else "Inactiva", tint = MaterialTheme.colorScheme.onSurfaceVariant)
                                                }
                                                Text(PHASE_LABELS[meeting.callPhase] ?: meeting.callPhase, style = MaterialTheme.typography.labelLarge, color = MaterialTheme.colorScheme.primary)
                                                meeting.schedules.forEach { schedule ->
                                                    Text(
                                                        "• ${schedule.day} ${schedule.time}" +
                                                            (schedule.location.takeIf { it.isNotBlank() }?.let { " · $it" } ?: "") +
                                                            " · ${schedule.participantCount} asignado(s)",
                                                        style = MaterialTheme.typography.bodyMedium,
                                                    )
                                                }
                                                Text(meeting.location.ifBlank { "Sin lugar" }, color = MaterialTheme.colorScheme.onSurfaceVariant)
                                                Text(if (meeting.active) "Activa" else "Inactiva", style = MaterialTheme.typography.labelLarge)
                                                HorizontalDivider()
                                                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.End) {
                                                    TextButton(enabled = !busy, onClick = {
                                                        editingMeetingId = meeting.id
                                                        meetingName = meeting.name
                                                        meetingLocation = meeting.location
                                                        meetingSchedules = meeting.schedules.ifEmpty { listOf(ScheduleDraft()) }
                                                        meetingQueue = meeting.queue
                                                        meetingPhase = meeting.callPhase
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
                            DialDestination.Statistics -> if (isSuperuser) item {
                                SuperuserStatistics(api = api!!, busy = busy, runRequest = ::runRequest, state = superuserState)
                            }
                            DialDestination.Users -> if (isSuperuser) item {
                                SuperuserAccounts(
                                    api = api!!, busy = busy, runRequest = ::runRequest,
                                    onNotice = { notice = it }, state = superuserState,
                                )
                            }
                            DialDestination.Register, DialDestination.Assignments -> item {
                                if (activeMeetingId == null) EmptyState(
                                    Icons.Default.DateRange,
                                    "Selecciona una reunión",
                                    "Elige una reunión antes de continuar.",
                                    actionLabel = "Ver reuniones",
                                    actionIcon = Icons.Default.DateRange,
                                    onAction = { destination = DialDestination.Meetings },
                                ) else key(activeMeetingId) {
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
                                    Surface(shape = RoundedCornerShape(8.dp), color = MaterialTheme.colorScheme.primary.copy(alpha = 0.10f)) {
                                        Text(PHASE_LABELS[activePhase] ?: activePhase, Modifier.padding(horizontal = 10.dp, vertical = 4.dp), color = MaterialTheme.colorScheme.primary, fontWeight = FontWeight.Bold)
                                    }
                                    if (activePhase == PHASE_CONFIRMATION && callTask == null) {
                                        Text(
                                            "Confirma la asistencia de quienes aceptaron (puedes cambiar su horario) o llama a quienes nunca respondieron.",
                                            style = MaterialTheme.typography.bodyMedium,
                                        )
                                        QueueTypeSelector(queueTypes, enabled = !busy, onChange = { queueTypes = it })
                                    }
                                    Button(enabled = !busy && callTask == null && (activePhase != PHASE_CONFIRMATION || queueTypes.isNotEmpty()), modifier = Modifier.fillMaxWidth().heightIn(min = 56.dp), onClick = ::requestNextCall) {
                                        ActionLabel(if (busy) "Consultando…" else "Solicitar siguiente llamada", Icons.Default.Call)
                                    }
                                    if (callTask == null) EmptyState(
                                        Icons.Default.Call,
                                        if (callQueueEmpty) "No hay llamadas disponibles" else "Listo para llamar",
                                        when {
                                            !callQueueEmpty -> "Solicita una llamada y registra el resultado al terminar."
                                            nextAvailableLabel.isNotBlank() -> "La próxima estará disponible a las $nextAvailableLabel."
                                            else -> "La cola está vacía por ahora. Puedes volver a consultar."
                                        },
                                        actionLabel = if (callQueueEmpty) "Volver a consultar" else null,
                                        actionIcon = Icons.Default.Refresh,
                                        onAction = ::requestNextCall,
                                        actionEnabled = !busy,
                                    )
                                    callTask?.let { task ->
                                        OutlinedCard(Modifier.fillMaxWidth()) {
                                            Column(Modifier.padding(20.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
                                                Icon(Icons.Default.AccountCircle, null, Modifier.size(48.dp), tint = MaterialTheme.colorScheme.primary)
                                                Text(task.name, style = MaterialTheme.typography.headlineSmall, fontWeight = FontWeight.Bold)
                                                Text(task.phone.ifBlank { "Sin teléfono" }, style = MaterialTheme.typography.titleLarge)
                                                Text("Reunión: ${task.meeting}")
                                                Text("Origen: ${task.origin}", color = MaterialTheme.colorScheme.onSurfaceVariant)
                                                val confirming = task.purpose == PHASE_CONFIRMATION
                                                Text(
                                                    when {
                                                        confirming -> "Confirmar asistencia" + (task.scheduleLabel.takeIf { it.isNotBlank() }?.let { " · Horario actual: $it" } ?: "")
                                                        task.queueType == "never_answered" -> "Invitación · nunca respondió"
                                                        task.queueType == "follow_up" -> "Invitación · seguimiento"
                                                        else -> "Invitación"
                                                    },
                                                    fontWeight = FontWeight.Bold, color = MaterialTheme.colorScheme.primary,
                                                )
                                                if (task.phone.isNotBlank()) Button(onClick = {
                                                    context.startActivity(Intent(Intent.ACTION_DIAL, Uri.parse("tel:${Uri.encode(task.phone)}")))
                                                }, modifier = Modifier.fillMaxWidth().heightIn(min = 56.dp)) { ActionLabel("Llamar", Icons.Default.Call) }
                                                if (task.history.isNotEmpty()) {
                                                    HorizontalDivider()
                                                    Text("Historial", fontWeight = FontWeight.Bold)
                                                    task.history.forEach { Text(it, style = MaterialTheme.typography.bodySmall) }
                                                }
                                                OutlinedTextField(value = callNotes, onValueChange = { callNotes = it }, label = { Text("Notas de la llamada") }, leadingIcon = { Icon(Icons.Default.Edit, null) }, modifier = Modifier.fillMaxWidth())
                                                SchedulePicker(
                                                    options = task.schedules, selected = callSchedule, enabled = !busy,
                                                    title = if (confirming) "Horario (cámbialo si la persona lo pide)" else "Horario al que asistirá (obligatorio para «Aceptó»)",
                                                    onSelect = { callSchedule = it },
                                                )
                                                FollowUpPicker(callFollowUp, enabled = !busy, onChange = { callFollowUp = it })
                                                Text("Resultado de la llamada", fontWeight = FontWeight.Bold)
                                                OutcomeGrid(
                                                    options = if (confirming) CONFIRMATION_OUTCOMES else INVITATION_OUTCOMES,
                                                    enabled = !busy,
                                                ) { outcome ->
                                                    val needsSchedule = outcome == "accepted" || (outcome == "confirmed" && task.scheduleId == null)
                                                    if (needsSchedule && callSchedule == null) {
                                                        notice = "Elige el horario al que asistirá antes de registrar «${(INVITATION_OUTCOMES + CONFIRMATION_OUTCOMES).toMap()[outcome]}»."
                                                        scope.launch { snackbarHostState.showNotice(notice, AdmonitionKind.Warning) }
                                                        return@OutcomeGrid
                                                    }
                                                    runRequest {
                                                        val body = JSONObject().put("outcome", outcome).put("notes", callNotes)
                                                        if (outcome == "accepted" || (outcome == "confirmed" && callSchedule != null && callSchedule != task.scheduleId)) {
                                                            body.put("schedule_id", callSchedule)
                                                        }
                                                        if (outcome == "follow_up" && callFollowUp.isNotBlank()) body.put("follow_up_at", callFollowUp)
                                                        val response = withContext(Dispatchers.IO) {
                                                            api!!.post("/api/v1/calls/${task.id}/result/", body)
                                                        }
                                                        notice = response.optString("code").takeIf { it.isNotBlank() && outcome == "accepted" }?.let { "Aceptación registrada. Código: $it" }
                                                            ?: when (outcome) {
                                                                "confirmed" -> "Asistencia confirmada."
                                                                "will_not_attend" -> "Registrado: no asistirá."
                                                                else -> "Resultado de llamada guardado."
                                                            }
                                                        callTask = null
                                                        callQueueEmpty = false
                                                        callSchedule = null
                                                        callFollowUp = ""
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
                                        FormTextField(
                                            value = query, onValueChange = { query = it }, label = "Nombre o teléfono",
                                            supportingText = "Deja vacío para listar participantes",
                                            leadingIcon = Icons.Default.Search, clearable = true, clearDescription = "Limpiar búsqueda",
                                            imeAction = ImeAction.Search, onSubmit = { if (!busy) searchPeople(1) },
                                            modifier = Modifier.fillMaxWidth(),
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
                                    OutlinedCard(onClick = { expandedPersonId = if (expanded) null else person.id; inboundSchedule = null }, modifier = Modifier.fillMaxWidth()) {
                                        ListItem(
                                            headlineContent = { Text(person.name, fontWeight = FontWeight.Bold) },
                                            supportingContent = {
                                                Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
                                                    Text(person.phone.ifBlank { "Sin teléfono" })
                                                    Surface(shape = RoundedCornerShape(6.dp), color = if (person.doNotContact) MaterialTheme.colorScheme.errorContainer else MaterialTheme.colorScheme.surfaceVariant) {
                                                        Text(if (person.doNotContact) "NO CONTACTAR" else INVITATION_STATUS_LABELS[person.invitationStatus] ?: person.invitationStatus.ifBlank { "Sin invitación" }, Modifier.padding(horizontal = 8.dp, vertical = 4.dp), style = MaterialTheme.typography.labelSmall)
                                                    }
                                                    if (person.invitationStatus == "accepted") {
                                                        Text(
                                                            "Horario: ${person.scheduleLabel.ifBlank { "sin asignar" }} · ${CONFIRMATION_LABELS[person.confirmation] ?: "Sin confirmar"}",
                                                            style = MaterialTheme.typography.bodySmall,
                                                        )
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
                                                val options = schedulesByMeeting[person.originId].orEmpty()
                                                val accepted = person.invitationStatus == "accepted"
                                                val chosen = inboundSchedule?.takeIf { id -> options.any { it.id == id } } ?: person.scheduleId
                                                SchedulePicker(
                                                    options = options, selected = chosen, enabled = !busy,
                                                    title = if (accepted) "Horario" else "Horario (obligatorio para «Aceptó»)",
                                                    onSelect = { inboundSchedule = it },
                                                )
                                                if (accepted && chosen != null && chosen != person.scheduleId) {
                                                    Button(enabled = !busy, modifier = Modifier.fillMaxWidth(), onClick = {
                                                        runRequest {
                                                            val response = withContext(Dispatchers.IO) {
                                                                api!!.post("/api/v1/participants/${person.id}/schedule/", JSONObject().put("schedule_id", chosen))
                                                            }
                                                            val label = response.optString("schedule_label")
                                                            results = results.map { if (it.id == person.id) it.copy(scheduleId = chosen, scheduleLabel = label) else it }
                                                            inboundSchedule = null
                                                            notice = "Horario cambiado: $label"
                                                        }
                                                    }) { ActionLabel("Cambiar horario", Icons.Default.DateRange) }
                                                }
                                                Text("Registrar contacto entrante", fontWeight = FontWeight.Bold)
                                                val inboundOptions = buildList {
                                                    add("contacted" to "Contactado")
                                                    if (accepted) { add("confirmed" to "Confirmó"); add("will_not_attend" to "No asistirá") }
                                                    else { add("accepted" to "Aceptó"); add("declined" to "Rechazó") }
                                                    add("follow_up" to "Seguimiento"); add("do_not_contact" to "No contactar"); add("other" to "Otro")
                                                }
                                                OutcomeGrid(inboundOptions, !busy) { outcome ->
                                                    if ((outcome == "accepted" || (outcome == "confirmed" && person.scheduleId == null)) && chosen == null) {
                                                        notice = "Elige el horario antes de registrar el resultado."
                                                        scope.launch { snackbarHostState.showNotice(notice, AdmonitionKind.Warning) }
                                                        return@OutcomeGrid
                                                    }
                                                    runRequest {
                                                        val body = JSONObject().put("participant_id", person.id).put("outcome", outcome)
                                                        if (outcome == "accepted" || (outcome == "confirmed" && chosen != null && chosen != person.scheduleId)) {
                                                            body.put("schedule_id", chosen)
                                                        }
                                                        val response = withContext(Dispatchers.IO) {
                                                            api!!.post("/api/v1/calls/inbound/", body)
                                                        }
                                                        inboundSchedule = null
                                                        notice = response.optString("code").takeIf { it.isNotBlank() && outcome == "accepted" }?.let { "Aceptación registrada. Código: $it" }
                                                            ?: "Contacto entrante registrado."
                                                        val label = options.firstOrNull { it.id == chosen }?.label.orEmpty()
                                                        results = results.map { item ->
                                                            if (item.id != person.id) item else when (outcome) {
                                                                "accepted" -> item.copy(invitationStatus = "accepted", scheduleId = chosen, scheduleLabel = label, confirmation = "pending")
                                                                "declined" -> item.copy(invitationStatus = "declined")
                                                                "confirmed" -> item.copy(confirmation = "confirmed", scheduleId = chosen, scheduleLabel = label)
                                                                "will_not_attend" -> item.copy(confirmation = "will_not_attend")
                                                                "do_not_contact" -> item.copy(doNotContact = true)
                                                                else -> item
                                                            }
                                                        }
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
