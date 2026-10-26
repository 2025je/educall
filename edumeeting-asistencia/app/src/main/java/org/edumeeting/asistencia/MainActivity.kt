package org.edumeeting.asistencia

import android.Manifest
import android.content.pm.PackageManager
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.BackHandler
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.camera.core.CameraSelector
import androidx.camera.core.ImageAnalysis
import androidx.camera.core.Preview
import androidx.camera.lifecycle.ProcessCameraProvider
import androidx.camera.view.PreviewView
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyListScope
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.ui.platform.LocalFocusManager
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.automirrored.filled.KeyboardArrowRight
import androidx.compose.material.icons.automirrored.filled.List
import androidx.compose.material.icons.automirrored.filled.Send
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Check
import androidx.compose.material.icons.filled.CheckCircle
import androidx.compose.material.icons.filled.Clear
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.DateRange
import androidx.compose.material.icons.filled.Done
import androidx.compose.material.icons.filled.Edit
import androidx.compose.material.icons.filled.Face
import androidx.compose.material.icons.filled.Home
import androidx.compose.material.icons.filled.Info
import androidx.compose.material.icons.filled.Lock
import androidx.compose.material.icons.filled.Menu
import androidx.compose.material.icons.filled.Person
import androidx.compose.material.icons.filled.Search
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material.icons.filled.Share
import androidx.compose.material.icons.filled.Warning
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.DrawerValue
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.ExtendedFloatingActionButton
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.ListItem
import androidx.compose.material3.ListItemDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalDrawerSheet
import androidx.compose.material3.ModalNavigationDrawer
import androidx.compose.material3.NavigationDrawerItem
import androidx.compose.material3.NavigationDrawerItemDefaults
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.material3.rememberDrawerState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.core.content.ContextCompat
import androidx.lifecycle.compose.LocalLifecycleOwner
import androidx.room.Room
import com.google.mlkit.vision.barcode.BarcodeScanning
import com.google.mlkit.vision.barcode.common.Barcode
import com.google.mlkit.vision.common.InputImage
import java.util.concurrent.Executors
import java.util.concurrent.atomic.AtomicBoolean
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.flow.flatMapLatest
import kotlinx.coroutines.flow.flowOf
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.edumeeting.asistencia.data.AttendanceDatabase
import org.edumeeting.asistencia.data.AttendanceDisplay
import org.edumeeting.asistencia.data.AttendancePackageImporter
import org.edumeeting.asistencia.data.AttendanceRepository
import org.edumeeting.asistencia.data.AttendanceResultsExporter
import org.edumeeting.asistencia.data.LocalMeeting
import org.edumeeting.asistencia.data.LocalParticipant

class MainActivity : ComponentActivity() {
    private val database by lazy {
        Room.databaseBuilder(applicationContext, AttendanceDatabase::class.java, "attendance.db").build()
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val repository = AttendanceRepository(applicationContext, database)
        setContent {
            EduMeetingTheme { theme ->
                AttendanceApp(repository, theme)
            }
        }
    }
}

enum class AppScreen(val title: String, val icon: ImageVector) {
    Inicio("Inicio", Icons.Default.Home),
    Importar("Importar paquete", Icons.Default.Add),
    Reunion("Reunión", Icons.Default.DateRange),
    Operador("Operador", Icons.Default.Person),
    Registrar("Registrar asistencia", Icons.Default.CheckCircle),
    Exportar("Exportar", Icons.Default.Share),
}

private fun LocalMeeting.label(): String = "${number.toString().padStart(2, '0')} · $name"

private fun LocalMeeting.details(): String =
    listOf(startsAt, location).filter { it.isNotBlank() }.joinToString(" · ")

@Composable
@OptIn(ExperimentalCoroutinesApi::class, ExperimentalMaterial3Api::class)
private fun AttendanceApp(repository: AttendanceRepository, theme: ThemeState) {
    val scope = rememberCoroutineScope()
    val context = LocalContext.current
    val meetings by repository.meetings.collectAsState(initial = emptyList())
    val selectedId by repository.currentMeetingId.collectAsState(initial = null)
    val operator by repository.operatorLabel.collectAsState(initial = "")
    val selectedMeeting = meetings.firstOrNull { it.id == selectedId }
    var pendingMeeting by remember { mutableStateOf<LocalMeeting?>(null) }
    var selectedParticipant by remember { mutableStateOf<Pair<LocalParticipant, String>?>(null) }
    var query by rememberSaveable { mutableStateOf("") }
    var screen by rememberSaveable { mutableStateOf(AppScreen.Inicio) }
    var scanning by rememberSaveable { mutableStateOf(false) }
    var cameraGranted by remember {
        mutableStateOf(ContextCompat.checkSelfPermission(context, Manifest.permission.CAMERA) == PackageManager.PERMISSION_GRANTED)
    }
    val snackbarHostState = remember { SnackbarHostState() }
    fun showNotice(message: String, kind: AdmonitionKind) {
        scope.launch { snackbarHostState.showNotice(message, kind) }
    }
    val drawerState = rememberDrawerState(DrawerValue.Closed)
    fun navigate(target: AppScreen) {
        screen = target
        scope.launch { drawerState.close() }
    }
    var operatorInput by remember { mutableStateOf("") }
    LaunchedEffect(operator) { operatorInput = operator }
    LaunchedEffect(screen) { if (screen != AppScreen.Registrar) scanning = false }
    val currentIdFlow = repository.currentMeetingId
    val searchResults by remember(query) {
        currentIdFlow.distinctUntilChanged().flatMapLatest { id ->
            if (id == null || query.isBlank()) flowOf(emptyList()) else repository.search(id, query.trim())
        }
    }.collectAsState(initial = emptyList())
    val attendance by remember(selectedId) {
        if (selectedId == null) flowOf(emptyList()) else repository.attendance(selectedId!!)
    }.collectAsState(initial = emptyList())
    val packageRosterCount by remember(selectedId) {
        if (selectedId == null) flowOf(0) else repository.participantCount(selectedId!!)
    }.collectAsState(initial = 0)

    val importLauncher = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocument()) { uri ->
        if (uri != null) scope.launch {
            showNotice("Validando firma y contenido del paquete…", AdmonitionKind.Info)
            try {
                val (meeting, count) = withContext(Dispatchers.IO) {
                    val (meeting, participants) = AttendancePackageImporter.read(
                        context.contentResolver, uri, BuildConfig.ATTENDANCE_PUBLIC_KEY_BASE64
                    )
                    repository.importPackage(meeting, participants)
                    meeting to participants.size
                }
                showNotice("Paquete válido: ${meeting.name}. $count participantes importados. Elige explícitamente la reunión de trabajo.", AdmonitionKind.Success)
                screen = AppScreen.Reunion
            } catch (error: Exception) {
                showNotice(error.message ?: "No se pudo importar el paquete.", AdmonitionKind.Danger)
            }
        }
    }
    fun launchImport() {
        pendingMeeting = null
        importLauncher.launch(arrayOf("application/vnd.edumeeting.attendance+zip", "application/zip"))
    }
    val exportLauncher = rememberLauncherForActivityResult(
        ActivityResultContracts.CreateDocument("application/vnd.edumeeting.attendance-results+zip")
    ) { uri ->
        if (uri != null && selectedMeeting != null) scope.launch {
            try {
                withContext(Dispatchers.IO) {
                    val records = repository.attendanceForExport(selectedMeeting.id)
                    AttendanceResultsExporter.write(
                        context.contentResolver, uri, selectedMeeting, records
                    )
                    repository.markExported(records.map { it.id })
                }
                showNotice("Resultados exportados. Las asistencias locales se conservaron.", AdmonitionKind.Success)
            } catch (error: Exception) {
                showNotice(error.message ?: "No se pudo exportar.", AdmonitionKind.Danger)
            }
        }
    }
    val cameraPermission = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { granted ->
        cameraGranted = granted
        if (granted) scanning = true
        else showNotice("Se necesita permiso de cámara para escanear QR. La búsqueda manual sigue disponible.", AdmonitionKind.Warning)
    }
    fun toggleScanner() {
        if (scanning) scanning = false
        else if (cameraGranted) scanning = true
        else cameraPermission.launch(Manifest.permission.CAMERA)
    }

    BackHandler(enabled = drawerState.isOpen || screen != AppScreen.Inicio) {
        if (drawerState.isOpen) scope.launch { drawerState.close() } else screen = AppScreen.Inicio
    }

    ModalNavigationDrawer(
        drawerState = drawerState,
        drawerContent = {
            AppDrawer(
                current = screen,
                selectedMeeting = selectedMeeting,
                theme = theme,
                onNavigate = ::navigate,
            )
        },
    ) {
        Scaffold(
            containerColor = MaterialTheme.colorScheme.background,
            snackbarHost = { NoticeSnackbarHost(snackbarHostState) },
            topBar = {
                Column {
                    TopAppBar(
                        title = {
                            Column {
                                Text(
                                    screen.title,
                                    style = MaterialTheme.typography.titleLarge,
                                    maxLines = 1,
                                    overflow = TextOverflow.Ellipsis,
                                )
                                Text(
                                    selectedMeeting?.label() ?: "Reunión sin seleccionar",
                                    style = MaterialTheme.typography.bodySmall,
                                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                                    maxLines = 1,
                                    overflow = TextOverflow.Ellipsis,
                                )
                            }
                        },
                        navigationIcon = {
                            if (screen == AppScreen.Inicio) {
                                IconButton(onClick = { scope.launch { drawerState.open() } }) {
                                    Icon(Icons.Default.Menu, contentDescription = "Abrir navegación")
                                }
                            } else {
                                IconButton(onClick = { screen = AppScreen.Inicio }) {
                                    Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "Volver a Inicio")
                                }
                            }
                        },
                        actions = {
                            IconButton(
                                onClick = theme.toggle,
                                modifier = Modifier.semantics {
                                    contentDescription = if (theme.dark) "Activar tema claro" else "Activar tema oscuro"
                                },
                            ) { ThemeGlyph(theme.dark) }
                        },
                        colors = TopAppBarDefaults.topAppBarColors(
                            containerColor = MaterialTheme.colorScheme.surface,
                            scrolledContainerColor = MaterialTheme.colorScheme.surface,
                            titleContentColor = MaterialTheme.colorScheme.onSurface,
                            navigationIconContentColor = MaterialTheme.colorScheme.onSurface,
                            actionIconContentColor = MaterialTheme.colorScheme.onSurface,
                        ),
                    )
                    HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
                }
            },
            floatingActionButton = {
                if (screen == AppScreen.Registrar && selectedMeeting != null) {
                    ExtendedFloatingActionButton(
                        onClick = ::toggleScanner,
                        icon = { Icon(if (scanning) Icons.Default.Close else Icons.Default.Search, contentDescription = null) },
                        text = { Text(if (scanning) "Cerrar cámara" else "Escanear QR") },
                        shape = RoundedCornerShape(16.dp),
                        containerColor = MaterialTheme.colorScheme.primary,
                        contentColor = MaterialTheme.colorScheme.onPrimary,
                    )
                }
            },
        ) { padding ->
            val modifier = Modifier.fillMaxSize().padding(padding)
            when (screen) {
                AppScreen.Inicio -> HomeScreen(
                    modifier = modifier,
                    meetings = meetings,
                    selectedId = selectedId,
                    selectedMeeting = selectedMeeting,
                    participants = packageRosterCount,
                    registered = attendance.size,
                    pending = attendance.count { it.exportedAt == null },
                    operator = operator,
                    onNavigate = ::navigate,
                    onImport = ::launchImport,
                )
                AppScreen.Importar -> ImportScreen(
                    modifier = modifier,
                    meetingsCount = meetings.size,
                    onImport = ::launchImport,
                    onShowMeetings = { screen = AppScreen.Reunion },
                )
                AppScreen.Reunion -> MeetingScreen(
                    modifier = modifier,
                    meetings = meetings,
                    selectedId = selectedId,
                    selectedMeeting = selectedMeeting,
                    onPick = { meeting -> if (meeting.id != selectedMeeting?.id) pendingMeeting = meeting },
                    onImport = ::launchImport,
                )
                AppScreen.Operador -> OperatorScreen(
                    modifier = modifier,
                    operator = operator,
                    value = operatorInput,
                    onValueChange = { operatorInput = it },
                    onSave = {
                        scope.launch {
                            try {
                                repository.setOperatorLabel(operatorInput)
                                showNotice("Identificador de operador guardado en este dispositivo.", AdmonitionKind.Success)
                            } catch (error: Exception) {
                                showNotice(error.message ?: "No se pudo guardar el identificador.", AdmonitionKind.Danger)
                            }
                        }
                    },
                )
                AppScreen.Registrar -> RegisterScreen(
                    modifier = modifier,
                    meeting = selectedMeeting,
                    registered = attendance.size,
                    query = query,
                    onQueryChange = { query = it },
                    results = searchResults,
                    scanning = scanning,
                    cameraGranted = cameraGranted,
                    onRequestCamera = { cameraPermission.launch(Manifest.permission.CAMERA) },
                    onCode = { code ->
                        val meeting = selectedMeeting
                        if (meeting != null) scope.launch {
                            val participant = repository.participantByCode(meeting.id, code)
                            if (participant == null) showNotice("El código no pertenece al paquete de la reunión actual.", AdmonitionKind.Danger)
                            else selectedParticipant = participant to "QR"
                        }
                    },
                    onRegister = { selectedParticipant = it to "MANUAL" },
                    onChooseMeeting = { screen = AppScreen.Reunion },
                )
                AppScreen.Exportar -> ExportScreen(
                    modifier = modifier,
                    meeting = selectedMeeting,
                    meetings = meetings,
                    attendance = attendance,
                    packageRosterCount = packageRosterCount,
                    onExport = { meeting ->
                        exportLauncher.launch("${meeting.number.toString().padStart(2, '0')}-attendance.attendance-results")
                    },
                    onChooseMeeting = { screen = AppScreen.Reunion },
                )
            }
        }
    }

    pendingMeeting?.let { meeting ->
        AlertDialog(
            onDismissRequest = { pendingMeeting = null },
            icon = { Icon(Icons.Default.DateRange, contentDescription = null) },
            title = { Text("Cambiar reunión actual") },
            text = { Text("¿Confirmas trabajar en «${meeting.name}»? Las asistencias existentes no se modificarán.") },
            confirmButton = {
                TextButton(onClick = {
                    scope.launch {
                        try {
                            repository.selectMeeting(meeting.id)
                            showNotice("Reunión actual cambiada a ${meeting.name}.", AdmonitionKind.Success)
                            pendingMeeting = null
                        } catch (error: Exception) {
                            showNotice(error.message ?: "No se pudo cambiar la reunión actual.", AdmonitionKind.Danger)
                        }
                    }
                }) { Text("Confirmar cambio") }
            },
            dismissButton = { TextButton(onClick = { pendingMeeting = null }) { Text("Cancelar") } },
        )
    }

    selectedParticipant?.let { (participant, method) ->
        val crossOrigin = participant.originMeetingId != null && participant.originMeetingId != selectedMeeting?.id
        AlertDialog(
            onDismissRequest = { selectedParticipant = null },
            icon = { Icon(Icons.Default.CheckCircle, contentDescription = null) },
            title = { Text("Confirmar asistencia") },
            text = {
                Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                        InitialsAvatar(participant.name)
                        Column {
                            Text(participant.name, style = MaterialTheme.typography.titleMedium)
                            Text(
                                participant.code,
                                style = MaterialTheme.typography.bodySmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                            )
                        }
                    }
                    Text("Reunión efectiva: ${selectedMeeting?.name ?: "sin seleccionar"}")
                    if (crossOrigin) Admonition(
                        if (selectedMeeting?.allowCrossMeetingAttendance == true)
                            "Aviso: fue convocado para ${participant.originMeetingName ?: "otra reunión"}. Confirma que se permite el acceso."
                        else "Acceso bloqueado: la reunión no permite participantes de ${participant.originMeetingName ?: "otro origen"}.",
                        if (selectedMeeting?.allowCrossMeetingAttendance == true) AdmonitionKind.Warning else AdmonitionKind.Danger,
                    )
                    Text("Método: $method", color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
            },
            confirmButton = {
                TextButton(
                    enabled = !crossOrigin || selectedMeeting?.allowCrossMeetingAttendance == true,
                    onClick = {
                        val meeting = selectedMeeting
                        if (meeting == null) {
                            showNotice("No hay reunión actual seleccionada.", AdmonitionKind.Danger)
                        } else {
                            scope.launch {
                                try {
                                    repository.register(participant.id, meeting.id, method)
                                    showNotice("Asistencia de ${participant.name} registrada en ${meeting.name}.", AdmonitionKind.Success)
                                    selectedParticipant = null
                                } catch (error: Exception) {
                                    showNotice(error.message ?: "No se pudo registrar la asistencia.", AdmonitionKind.Danger)
                                }
                            }
                        }
                    },
                ) { Text("Registrar en reunión actual") }
            },
            dismissButton = { TextButton(onClick = { selectedParticipant = null }) { Text("Cancelar") } },
        )
    }
}

@Composable
private fun ThemeGlyph(dark: Boolean) {
    Text(if (dark) "☀" else "☾", style = MaterialTheme.typography.titleLarge)
}

@Composable
private fun AppDrawer(
    current: AppScreen,
    selectedMeeting: LocalMeeting?,
    theme: ThemeState,
    onNavigate: (AppScreen) -> Unit,
) {
    ModalDrawerSheet(
        drawerContainerColor = MaterialTheme.colorScheme.surface,
        drawerContentColor = MaterialTheme.colorScheme.onSurface,
        drawerShape = RoundedCornerShape(topEnd = 16.dp, bottomEnd = 16.dp),
    ) {
        Column(Modifier.fillMaxHeight()) {
            Column(Modifier.padding(start = 20.dp, end = 20.dp, top = 24.dp, bottom = 16.dp)) {
                Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                    IconBadge(Icons.Default.CheckCircle, size = 40)
                    Column {
                        Text("EduMeeting Asistencia", style = MaterialTheme.typography.titleLarge)
                        Text(
                            "Asistencia offline",
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                }
                Spacer(Modifier.height(16.dp))
                Surface(
                    shape = RoundedCornerShape(10.dp),
                    color = MaterialTheme.colorScheme.surfaceVariant,
                    modifier = Modifier.fillMaxWidth(),
                ) {
                    Row(
                        Modifier.padding(12.dp),
                        verticalAlignment = Alignment.CenterVertically,
                        horizontalArrangement = Arrangement.spacedBy(10.dp),
                    ) {
                        Icon(
                            Icons.Default.DateRange,
                            contentDescription = null,
                            tint = MaterialTheme.colorScheme.primary,
                            modifier = Modifier.size(18.dp),
                        )
                        Column {
                            Text(
                                "Reunión actual",
                                style = MaterialTheme.typography.labelSmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                            )
                            Text(
                                selectedMeeting?.label() ?: "Sin seleccionar",
                                style = MaterialTheme.typography.bodyMedium,
                                fontWeight = FontWeight.SemiBold,
                                maxLines = 2,
                                overflow = TextOverflow.Ellipsis,
                            )
                        }
                    }
                }
            }
            HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
            Column(
                Modifier.weight(1f).verticalScroll(rememberScrollState()).padding(12.dp),
                verticalArrangement = Arrangement.spacedBy(2.dp),
            ) {
                AppScreen.entries.forEach { target ->
                    DrawerEntry(
                        label = target.title,
                        selected = target == current,
                        onClick = { onNavigate(target) },
                    ) { Icon(target.icon, contentDescription = null) }
                }
            }
            HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
            Column(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(2.dp)) {
                Text(
                    "Apariencia",
                    style = MaterialTheme.typography.labelMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier.padding(start = 16.dp, top = 4.dp, bottom = 4.dp),
                )
                DrawerEntry(
                    label = if (theme.dark) "Tema claro" else "Tema oscuro",
                    selected = false,
                    onClick = theme.toggle,
                ) { ThemeGlyph(theme.dark) }
                DrawerEntry(
                    label = "Tema según el sistema",
                    selected = theme.followsSystem,
                    onClick = theme.followSystem,
                ) { Icon(Icons.Default.Settings, contentDescription = null) }
            }
        }
    }
}

@Composable
private fun DrawerEntry(label: String, selected: Boolean, onClick: () -> Unit, icon: @Composable () -> Unit) {
    val accent = MaterialTheme.colorScheme.primary
    NavigationDrawerItem(
        label = { Text(label, fontWeight = if (selected) FontWeight.Bold else FontWeight.Normal) },
        icon = icon,
        selected = selected,
        onClick = onClick,
        shape = RoundedCornerShape(10.dp),
        colors = NavigationDrawerItemDefaults.colors(
            selectedContainerColor = accent.copy(alpha = 0.10f),
            selectedIconColor = accent,
            selectedTextColor = accent,
            unselectedContainerColor = Color.Transparent,
            unselectedIconColor = MaterialTheme.colorScheme.onSurfaceVariant,
            unselectedTextColor = MaterialTheme.colorScheme.onSurface,
        ),
    )
}

@Composable
private fun ScreenList(
    modifier: Modifier,
    bottomPadding: Int = 24,
    content: LazyListScope.() -> Unit,
) {
    LazyColumn(
        modifier = modifier,
        contentPadding = PaddingValues(start = 16.dp, end = 16.dp, top = 20.dp, bottom = bottomPadding.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp),
        content = content,
    )
}

private data class QuickAction(val screen: AppScreen, val description: String, val action: String)

@Composable
private fun HomeScreen(
    modifier: Modifier,
    meetings: List<LocalMeeting>,
    selectedId: String?,
    selectedMeeting: LocalMeeting?,
    participants: Int,
    registered: Int,
    pending: Int,
    operator: String,
    onNavigate: (AppScreen) -> Unit,
    onImport: () -> Unit,
) {
    val actions = listOf(
        QuickAction(AppScreen.Registrar, "Escanea el QR o busca por nombre, teléfono o código.", "Registrar"),
        QuickAction(AppScreen.Reunion, "Elige y confirma la reunión de trabajo.", "Elegir"),
        QuickAction(AppScreen.Importar, "Carga un paquete firmado con reuniones y participantes.", "Importar"),
        QuickAction(AppScreen.Exportar, "Genera el archivo de resultados de la reunión.", "Exportar"),
        QuickAction(AppScreen.Operador, "Identifica a quien registra en este dispositivo.", "Configurar"),
    )
    ScreenList(modifier) {
        item {
            ScreenHeader("Asistencia offline", "Registra asistencias sin conexión a partir de un paquete firmado.")
        }
        item {
            if (selectedMeeting != null) {
                OutlinedPanel(
                    onClick = { onNavigate(AppScreen.Reunion) },
                    borderColor = MaterialTheme.colorScheme.primary.copy(alpha = 0.35f),
                    containerColor = MaterialTheme.colorScheme.primary.copy(alpha = 0.06f),
                ) {
                    Row(
                        Modifier.padding(16.dp),
                        verticalAlignment = Alignment.CenterVertically,
                        horizontalArrangement = Arrangement.spacedBy(12.dp),
                    ) {
                        IconBadge(Icons.Default.DateRange, size = 44)
                        Column(Modifier.weight(1f)) {
                            Text(
                                "Reunión actual",
                                style = MaterialTheme.typography.labelMedium,
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                            )
                            Text(selectedMeeting.label(), style = MaterialTheme.typography.titleMedium)
                            val details = selectedMeeting.details()
                            if (details.isNotBlank()) Text(
                                details,
                                style = MaterialTheme.typography.bodySmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                            )
                        }
                        Icon(
                            Icons.AutoMirrored.Filled.KeyboardArrowRight,
                            contentDescription = "Cambiar reunión",
                            tint = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                }
            } else {
                Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
                    if (meetings.isEmpty()) {
                        Admonition("Importa un paquete firmado antes de iniciar el registro.")
                        PrimaryButton("Importar paquete", Icons.Default.Add, onImport, Modifier.fillMaxWidth())
                    } else {
                        if (selectedId != null) {
                            Admonition("La reunión guardada ya no está disponible. Elige otra reunión explícitamente.", AdmonitionKind.Warning)
                        } else {
                            Admonition("Debes seleccionar y confirmar una reunión antes de registrar asistencias.", AdmonitionKind.Warning)
                        }
                        PrimaryButton("Elegir reunión", Icons.Default.DateRange, { onNavigate(AppScreen.Reunion) }, Modifier.fillMaxWidth())
                    }
                }
            }
        }
        item {
            Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                StatCard(Icons.Default.Person, participants.toString(), "Participantes en el paquete", Modifier.weight(1f))
                StatCard(Icons.Default.CheckCircle, registered.toString(), "Asistencias registradas", Modifier.weight(1f))
                StatCard(Icons.AutoMirrored.Filled.Send, pending.toString(), "Pendientes de exportar", Modifier.weight(1f))
            }
        }
        item { SectionHeading("Acciones rápidas") }
        items(actions.chunked(2)) { row ->
            Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                row.forEach { action ->
                    GridCard(
                        icon = action.screen.icon,
                        title = action.screen.title,
                        description = action.description,
                        action = action.action,
                        onClick = { onNavigate(action.screen) },
                        modifier = Modifier.weight(1f),
                    )
                }
                if (row.size == 1) Spacer(Modifier.weight(1f))
            }
        }
        item {
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Icon(
                    Icons.Default.Person,
                    contentDescription = null,
                    tint = MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier.size(18.dp),
                )
                Text(
                    if (operator.isBlank()) "Operador sin identificar" else "Operador: $operator",
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        }
    }
}

@Composable
private fun StepRow(icon: ImageVector, text: String) {
    Row(
        Modifier.fillMaxWidth().heightIn(min = 48.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        IconBadge(icon, size = 32)
        Text(text, style = MaterialTheme.typography.bodyLarge, modifier = Modifier.weight(1f))
    }
}

@Composable
private fun ImportScreen(
    modifier: Modifier,
    meetingsCount: Int,
    onImport: () -> Unit,
    onShowMeetings: () -> Unit,
) {
    ScreenList(modifier) {
        item {
            ScreenHeader("Importar paquete", "Carga el paquete firmado que preparó la coordinación para esta jornada.")
        }
        item {
            OutlinedPanel {
                Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    SectionHeading("Qué sucede al importar")
                    HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
                    StepRow(Icons.Default.Lock, "Se valida la firma y el contenido del paquete.")
                    StepRow(Icons.AutoMirrored.Filled.List, "Se guardan las reuniones y participantes en el dispositivo.")
                    StepRow(Icons.Default.DateRange, "Después eliges explícitamente la reunión de trabajo.")
                }
            }
        }
        item {
            PrimaryButton("Seleccionar paquete firmado", Icons.Default.Add, onImport, Modifier.fillMaxWidth())
        }
        item {
            if (meetingsCount > 0) {
                Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
                    Admonition(
                        if (meetingsCount == 1) "Hay 1 reunión disponible en este dispositivo."
                        else "Hay $meetingsCount reuniones disponibles en este dispositivo.",
                        AdmonitionKind.Info,
                    )
                    SecondaryButton("Ver reuniones", Icons.Default.DateRange, onShowMeetings, Modifier.fillMaxWidth())
                }
            } else {
                Admonition("Importa un paquete firmado antes de iniciar el registro.")
            }
        }
    }
}

@Composable
private fun MeetingScreen(
    modifier: Modifier,
    meetings: List<LocalMeeting>,
    selectedId: String?,
    selectedMeeting: LocalMeeting?,
    onPick: (LocalMeeting) -> Unit,
    onImport: () -> Unit,
) {
    ScreenList(modifier) {
        if (meetings.isEmpty()) {
            item {
                EmptyState(
                    icon = Icons.Default.DateRange,
                    title = "Sin reuniones",
                    message = "Importa un paquete firmado para ver sus reuniones.",
                    actionLabel = "Importar paquete",
                    actionIcon = Icons.Default.Add,
                    onAction = onImport,
                )
            }
            return@ScreenList
        }
        item {
            ScreenHeader("Reunión de trabajo", "Toca una reunión para trabajar en ella. Se pedirá confirmación.")
        }
        if (selectedId != null && selectedMeeting == null) item {
            Admonition("La reunión guardada ya no está disponible. Elige otra reunión explícitamente.", AdmonitionKind.Warning)
        }
        if (selectedMeeting == null) item {
            Admonition("Debes seleccionar y confirmar una reunión antes de registrar asistencias.", AdmonitionKind.Warning)
        }
        items(meetings, key = { it.id }) { meeting ->
            MeetingItem(meeting, meeting.id == selectedMeeting?.id) { onPick(meeting) }
        }
    }
}

@Composable
private fun MeetingItem(meeting: LocalMeeting, selected: Boolean, onClick: () -> Unit) {
    val accent = MaterialTheme.colorScheme.primary
    OutlinedPanel(
        onClick = onClick,
        borderColor = if (selected) accent.copy(alpha = 0.6f) else MaterialTheme.colorScheme.outline,
        containerColor = if (selected) accent.copy(alpha = 0.06f) else MaterialTheme.colorScheme.surface,
    ) {
        ListItem(
            colors = ListItemDefaults.colors(containerColor = Color.Transparent),
            leadingContent = {
                Box(
                    Modifier.size(40.dp).background(accent.copy(alpha = 0.12f), RoundedCornerShape(10.dp)),
                    contentAlignment = Alignment.Center,
                ) {
                    Text(
                        meeting.number.toString().padStart(2, '0'),
                        color = accent,
                        fontWeight = FontWeight.Bold,
                        style = MaterialTheme.typography.labelLarge,
                    )
                }
            },
            headlineContent = {
                Text(
                    meeting.name,
                    fontWeight = FontWeight.Bold,
                    color = if (selected) accent else MaterialTheme.colorScheme.onSurface,
                )
            },
            supportingContent = {
                val details = meeting.details()
                Text(
                    buildString {
                        if (details.isNotBlank()) append(details).append('\n')
                        append("Invitados ${meeting.invitedCount} · Confirmados ${meeting.confirmedCount}")
                    },
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            },
            trailingContent = {
                if (selected) Icon(Icons.Default.CheckCircle, contentDescription = "Seleccionada", tint = accent)
                else Icon(
                    Icons.AutoMirrored.Filled.KeyboardArrowRight,
                    contentDescription = null,
                    tint = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            },
        )
    }
}

@Composable
private fun OperatorScreen(
    modifier: Modifier,
    operator: String,
    value: String,
    onValueChange: (String) -> Unit,
    onSave: () -> Unit,
) {
    val focusManager = LocalFocusManager.current
    ScreenList(modifier) {
        item {
            ScreenHeader("Operador", "Identifica a quien registra asistencias en este dispositivo. Es opcional.")
        }
        item {
            OutlinedTextField(
                value = value,
                onValueChange = onValueChange,
                label = { Text("Identificador") },
                leadingIcon = { Icon(Icons.Default.Person, contentDescription = null) },
                trailingIcon = {
                    if (value.isNotEmpty()) IconButton(onClick = { onValueChange("") }) {
                        Icon(Icons.Default.Clear, contentDescription = "Borrar identificador")
                    }
                },
                supportingText = { Text("Se guarda en este dispositivo y acompaña cada asistencia.") },
                singleLine = true,
                shape = RoundedCornerShape(12.dp),
                keyboardOptions = KeyboardOptions(imeAction = ImeAction.Done),
                keyboardActions = KeyboardActions(onDone = {
                    focusManager.clearFocus()
                    onSave()
                }),
                modifier = Modifier.fillMaxWidth(),
            )
        }
        item {
            PrimaryButton("Guardar identificador", Icons.Default.Check, onSave, Modifier.fillMaxWidth())
        }
        item {
            Admonition(
                if (operator.isBlank()) "Aún no hay un identificador guardado." else "Operador actual: $operator",
                if (operator.isBlank()) AdmonitionKind.Note else AdmonitionKind.Info,
            )
        }
    }
}

@Composable
private fun RegisterScreen(
    modifier: Modifier,
    meeting: LocalMeeting?,
    registered: Int,
    query: String,
    onQueryChange: (String) -> Unit,
    results: List<LocalParticipant>,
    scanning: Boolean,
    cameraGranted: Boolean,
    onRequestCamera: () -> Unit,
    onCode: (String) -> Unit,
    onRegister: (LocalParticipant) -> Unit,
    onChooseMeeting: () -> Unit,
) {
    val focusManager = LocalFocusManager.current
    if (meeting == null) {
        ScreenList(modifier) {
            item {
                EmptyState(
                    icon = Icons.Default.DateRange,
                    title = "Sin reunión seleccionada",
                    message = "Selecciona una reunión para habilitar búsqueda y registro.",
                    actionLabel = "Elegir reunión",
                    actionIcon = Icons.Default.DateRange,
                    onAction = onChooseMeeting,
                )
            }
        }
        return
    }
    ScreenList(modifier, bottomPadding = 96) {
        item {
            Surface(
                shape = RoundedCornerShape(10.dp),
                color = MaterialTheme.colorScheme.surfaceVariant,
                modifier = Modifier.fillMaxWidth(),
            ) {
                Row(
                    Modifier.padding(horizontal = 12.dp, vertical = 10.dp),
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(10.dp),
                ) {
                    Icon(Icons.Default.CheckCircle, contentDescription = null, tint = MaterialTheme.colorScheme.primary)
                    Text(
                        "$registered asistencias registradas en ${meeting.name}",
                        style = MaterialTheme.typography.bodyMedium,
                        modifier = Modifier.weight(1f),
                    )
                }
            }
        }
        if (scanning) item {
            if (cameraGranted) {
                OutlinedPanel {
                    Column {
                        QrCamera(
                            onCode = onCode,
                            modifier = Modifier.fillMaxWidth().height(280.dp)
                                .clip(RoundedCornerShape(topStart = 12.dp, topEnd = 12.dp)),
                        )
                        Row(
                            Modifier.padding(12.dp),
                            verticalAlignment = Alignment.CenterVertically,
                            horizontalArrangement = Arrangement.spacedBy(8.dp),
                        ) {
                            Icon(
                                Icons.Default.Info,
                                contentDescription = null,
                                tint = MaterialTheme.colorScheme.primary,
                                modifier = Modifier.size(18.dp),
                            )
                            Text(
                                "Apunta la cámara al código QR del participante.",
                                style = MaterialTheme.typography.bodyMedium,
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                            )
                        }
                    }
                }
            } else {
                Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
                    Admonition("Se necesita permiso de cámara para escanear QR. La búsqueda manual sigue disponible.", AdmonitionKind.Warning)
                    SecondaryButton("Permitir cámara para escanear QR", Icons.Default.Lock, onRequestCamera, Modifier.fillMaxWidth())
                }
            }
        }
        item {
            OutlinedTextField(
                value = query,
                onValueChange = onQueryChange,
                placeholder = { Text("Nombre, teléfono o código") },
                label = { Text("Buscar participante") },
                leadingIcon = { Icon(Icons.Default.Search, contentDescription = null) },
                trailingIcon = {
                    if (query.isNotEmpty()) IconButton(onClick = { onQueryChange("") }) {
                        Icon(Icons.Default.Clear, contentDescription = "Limpiar búsqueda")
                    }
                },
                singleLine = true,
                shape = RoundedCornerShape(12.dp),
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Text, imeAction = ImeAction.Search),
                keyboardActions = KeyboardActions(onSearch = { focusManager.clearFocus() }),
                modifier = Modifier.fillMaxWidth(),
            )
        }
        when {
            query.isBlank() -> item {
                Row(
                    Modifier.padding(horizontal = 4.dp),
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    Icon(
                        Icons.Default.Info,
                        contentDescription = null,
                        tint = MaterialTheme.colorScheme.onSurfaceVariant,
                        modifier = Modifier.size(18.dp),
                    )
                    Text(
                        "Escribe un nombre, teléfono o código (p. ej. JU-251026-07-001), o usa «Escanear QR».",
                        style = MaterialTheme.typography.bodyMedium,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            }
            results.isEmpty() -> item {
                EmptyState(
                    icon = Icons.Default.Search,
                    title = "Sin resultados",
                    message = "No hay participantes que coincidan con «${query.trim()}».",
                )
            }
            else -> items(results, key = { it.id }) { participant ->
                OutlinedPanel(onClick = { onRegister(participant) }) {
                    ListItem(
                        colors = ListItemDefaults.colors(containerColor = Color.Transparent),
                        leadingContent = { InitialsAvatar(participant.name) },
                        headlineContent = { Text(participant.name, fontWeight = FontWeight.SemiBold) },
                        supportingContent = {
                            Text(
                                listOf(participant.phone, participant.code).filter { it.isNotBlank() }.joinToString(" · "),
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                            )
                        },
                        trailingContent = {
                            Button(
                                onClick = { onRegister(participant) },
                                shape = RoundedCornerShape(12.dp),
                                contentPadding = PaddingValues(horizontal = 12.dp),
                                modifier = Modifier.heightIn(min = 48.dp),
                            ) {
                                Icon(Icons.Default.Check, contentDescription = null, modifier = Modifier.size(18.dp))
                                Spacer(Modifier.width(6.dp))
                                Text("Registrar")
                            }
                        },
                    )
                }
            }
        }
    }
}

@Composable
private fun ExportScreen(
    modifier: Modifier,
    meeting: LocalMeeting?,
    meetings: List<LocalMeeting>,
    attendance: List<AttendanceDisplay>,
    packageRosterCount: Int,
    onExport: (LocalMeeting) -> Unit,
    onChooseMeeting: () -> Unit,
) {
    ScreenList(modifier) {
        if (meeting == null) {
            item {
                EmptyState(
                    icon = Icons.Default.Share,
                    title = "Nada que exportar",
                    message = "Selecciona una reunión para exportar sus asistencias.",
                    actionLabel = "Elegir reunión",
                    actionIcon = Icons.Default.DateRange,
                    onAction = onChooseMeeting,
                )
            }
            return@ScreenList
        }
        item {
            ScreenHeader("Exportar resultados", "Genera el archivo de asistencias de ${meeting.label()}.")
        }
        val stats = listOf(
            Triple(Icons.Default.Person, meeting.invitedCount, "Invitados"),
            Triple(Icons.Default.Done, meeting.confirmedCount, "Confirmados"),
            Triple(Icons.AutoMirrored.Filled.List, packageRosterCount, "Incluidos en el paquete"),
            Triple(Icons.Default.CheckCircle, attendance.size, "Asistencias"),
            Triple(Icons.Default.Face, attendance.count { it.method == "QR" }, "Por QR"),
            Triple(Icons.Default.Edit, attendance.count { it.method == "MANUAL" }, "Manuales"),
            Triple(Icons.AutoMirrored.Filled.Send, attendance.count { it.exportedAt == null }, "Pendientes de exportar"),
            Triple(Icons.Default.Warning, attendance.count { !it.exceptionNote.isNullOrBlank() }, "Excepciones"),
        )
        items(stats.chunked(2)) { row ->
            Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                row.forEach { (icon, value, label) ->
                    StatCard(icon, value.toString(), label, Modifier.weight(1f))
                }
            }
        }
        item {
            PrimaryButton(
                "Exportar ${attendance.size} asistencias",
                Icons.Default.Share,
                { onExport(meeting) },
                Modifier.fillMaxWidth(),
            )
        }
        item { Admonition("Al exportar, las asistencias locales se conservan en el dispositivo.", AdmonitionKind.Info) }
        item { SectionHeading("Asistencias registradas") }
        if (attendance.isEmpty()) item {
            Text(
                "Aún no hay asistencias registradas en esta reunión.",
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
        items(attendance, key = { it.id }) { record ->
            AttendanceRow(record, meetings)
        }
    }
}

@Composable
private fun AttendanceRow(record: AttendanceDisplay, meetings: List<LocalMeeting>) {
    val exported = record.exportedAt != null
    OutlinedPanel {
        Column(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                InitialsAvatar(record.participantName)
                Column(Modifier.weight(1f)) {
                    Text(record.participantName, fontWeight = FontWeight.SemiBold)
                    Text(
                        "${record.recordedAt} · ${record.method}",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
                val statusColor = if (exported) AdmonitionKind.Success.color else AdmonitionKind.Info.color
                Icon(
                    if (exported) Icons.Default.CheckCircle else Icons.AutoMirrored.Filled.Send,
                    contentDescription = if (exported) "Exportado" else "Pendiente de exportar",
                    tint = statusColor,
                    modifier = Modifier.size(20.dp),
                )
            }
            HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
            Text(
                "ID: ${record.participantId}\n" +
                    "Origen: ${record.originMeetingName ?: "Sin reunión de origen"} · Efectiva: ${meetings.firstOrNull { it.id == record.effectiveMeetingId }?.name ?: record.effectiveMeetingId}\n" +
                    "UUID ${record.id}",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            Text(
                if (exported) "Exportado ${record.exportedAt}" else "Pendiente de exportar",
                style = MaterialTheme.typography.labelMedium,
                color = if (exported) AdmonitionKind.Success.color else MaterialTheme.colorScheme.primary,
            )
            if (!record.exceptionNote.isNullOrBlank()) Admonition("Excepción: ${record.exceptionNote}", AdmonitionKind.Warning)
        }
    }
}

@Composable
private fun QrCamera(onCode: (String) -> Unit, modifier: Modifier = Modifier) {
    val lifecycleOwner = LocalLifecycleOwner.current
    val executor = remember { Executors.newSingleThreadExecutor() }
    val scanner = remember { BarcodeScanning.getClient() }
    val delivered = remember { AtomicBoolean(false) }
    var providerRef by remember { mutableStateOf<ProcessCameraProvider?>(null) }
    AndroidView(
        modifier = modifier,
        factory = { viewContext ->
            val previewView = PreviewView(viewContext)
            val providerFuture = ProcessCameraProvider.getInstance(viewContext)
            providerFuture.addListener({
                val provider = providerFuture.get()
                providerRef = provider
                val preview = Preview.Builder().build().also { it.surfaceProvider = previewView.surfaceProvider }
                val analysis = ImageAnalysis.Builder()
                    .setBackpressureStrategy(ImageAnalysis.STRATEGY_KEEP_ONLY_LATEST)
                    .build()
                analysis.setAnalyzer(executor) { proxy ->
                    val mediaImage = proxy.image
                    if (mediaImage == null || delivered.get()) {
                        proxy.close()
                    } else {
                        scanner.process(InputImage.fromMediaImage(mediaImage, proxy.imageInfo.rotationDegrees))
                            .addOnSuccessListener { barcodes ->
                                val value = barcodes.firstOrNull { it.format == Barcode.FORMAT_QR_CODE }?.rawValue
                                if (!value.isNullOrBlank() && delivered.compareAndSet(false, true)) {
                                    previewView.post { onCode(value) }
                                    previewView.postDelayed({ delivered.set(false) }, 1800)
                                }
                            }
                            .addOnCompleteListener { proxy.close() }
                    }
                }
                provider.unbindAll()
                provider.bindToLifecycle(lifecycleOwner, CameraSelector.DEFAULT_BACK_CAMERA, preview, analysis)
            }, ContextCompat.getMainExecutor(viewContext))
            previewView
        },
    )
    DisposableEffect(Unit) {
        onDispose {
            providerRef?.unbindAll()
            scanner.close()
            executor.shutdown()
        }
    }
}
