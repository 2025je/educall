package org.educall.attendance

import android.Manifest
import android.content.pm.PackageManager
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.camera.core.CameraSelector
import androidx.camera.core.ImageAnalysis
import androidx.camera.core.Preview
import androidx.camera.lifecycle.ProcessCameraProvider
import androidx.camera.view.PreviewView
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.lifecycle.compose.LocalLifecycleOwner
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.core.content.ContextCompat
import androidx.room.Room
import com.google.mlkit.vision.barcode.BarcodeScanning
import com.google.mlkit.vision.barcode.common.Barcode
import com.google.mlkit.vision.common.InputImage
import java.util.concurrent.Executors
import java.util.concurrent.atomic.AtomicBoolean
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.flatMapLatest
import kotlinx.coroutines.flow.flowOf
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.educall.attendance.data.AttendanceDatabase
import org.educall.attendance.data.AttendanceDisplay
import org.educall.attendance.data.AttendancePackageImporter
import org.educall.attendance.data.AttendanceRepository
import org.educall.attendance.data.AttendanceResultsExporter
import org.educall.attendance.data.LocalMeeting
import org.educall.attendance.data.LocalParticipant

class MainActivity : ComponentActivity() {
    private val database by lazy {
        Room.databaseBuilder(applicationContext, AttendanceDatabase::class.java, "attendance.db").build()
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val repository = AttendanceRepository(applicationContext, database)
        setContent { AttendanceScreen(repository) }
    }
}

@Composable
@OptIn(ExperimentalCoroutinesApi::class)
private fun AttendanceScreen(repository: AttendanceRepository) {
    val scope = rememberCoroutineScope()
    val context = LocalContext.current
    val meetings by repository.meetings.collectAsState(initial = emptyList())
    val selectedId by repository.currentMeetingId.collectAsState(initial = null)
    val operator by repository.operatorLabel.collectAsState(initial = "")
    val selectedMeeting = meetings.firstOrNull { it.id == selectedId }
    var pendingMeeting by remember { mutableStateOf<LocalMeeting?>(null) }
    var selectedParticipant by remember { mutableStateOf<Pair<LocalParticipant, String>?>(null) }
    var query by remember { mutableStateOf("") }
    var notice by remember { mutableStateOf("Importa un paquete firmado antes de iniciar el registro.") }
    var operatorInput by remember { mutableStateOf(operator) }
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
            notice = "Validando firma y contenido del paquete…"
            try {
                val (meeting, count) = withContext(Dispatchers.IO) {
                    val (meeting, participants) = AttendancePackageImporter.read(
                        context.contentResolver, uri, BuildConfig.ATTENDANCE_PUBLIC_KEY_BASE64
                    )
                    repository.importPackage(meeting, participants)
                    meeting to participants.size
                }
                notice = "Paquete válido: ${meeting.name}. $count participantes importados. Elige explícitamente la reunión de trabajo."
            } catch (error: Exception) {
                notice = error.message ?: "No se pudo importar el paquete."
            }
        }
    }
    val exportLauncher = rememberLauncherForActivityResult(
        ActivityResultContracts.CreateDocument("application/vnd.educall.attendance-results+zip")
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
                notice = "Resultados exportados. Las asistencias locales se conservaron."
            } catch (error: Exception) {
                notice = error.message ?: "No se pudo exportar."
            }
        }
    }
    val cameraPermission = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { granted ->
        if (!granted) notice = "Se necesita permiso de cámara para escanear QR. La búsqueda manual sigue disponible."
    }

    MaterialTheme {
        Scaffold(
            topBar = {
                Surface(tonalElevation = 4.dp) {
                    Text(
                        "Reunión actual: ${selectedMeeting?.name ?: "sin seleccionar"}",
                        modifier = Modifier.fillMaxWidth().padding(16.dp),
                        style = MaterialTheme.typography.titleMedium,
                    )
                }
            },
        ) { padding ->
            LazyColumn(
                modifier = Modifier.fillMaxSize().padding(padding).padding(16.dp),
                verticalArrangement = Arrangement.spacedBy(12.dp),
            ) {
                item {
                    Text("EduCall · Asistencia offline", style = MaterialTheme.typography.headlineSmall)
                    Text(notice, color = MaterialTheme.colorScheme.primary)
                }
                item {
                    Card(Modifier.fillMaxWidth()) {
                        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                            Text("Reunión actual", style = MaterialTheme.typography.titleMedium)
                            Text(selectedMeeting?.let { "${it.number.toString().padStart(2, '0')} · ${it.name}" }
                                ?: "Ninguna seleccionada")
                            if (selectedId != null && selectedMeeting == null) {
                                Text("La reunión guardada ya no está disponible. Elige otra reunión explícitamente.")
                            }
                            Button(onClick = { pendingMeeting = null; importLauncher.launch(arrayOf("application/vnd.educall.attendance+zip", "application/zip")) }) {
                                Text("Importar paquete firmado")
                            }
                            meetings.forEach { meeting ->
                                OutlinedButton(
                                    onClick = { pendingMeeting = meeting },
                                    modifier = Modifier.fillMaxWidth(),
                                ) { Text("Seleccionar ${meeting.number.toString().padStart(2, '0')} · ${meeting.name}") }
                            }
                            if (meetings.isNotEmpty() && selectedMeeting == null) {
                                Text("Debes seleccionar y confirmar una reunión antes de registrar asistencias.")
                            }
                        }
                    }
                }
                item {
                    Card(Modifier.fillMaxWidth()) {
                        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                            Text("Operador (opcional)", style = MaterialTheme.typography.titleMedium)
                            OutlinedTextField(
                                value = operatorInput,
                                onValueChange = { operatorInput = it },
                                label = { Text("Identificador") },
                                singleLine = true,
                                modifier = Modifier.fillMaxWidth(),
                            )
                            OutlinedButton(onClick = {
                                scope.launch {
                                    try {
                                        repository.setOperatorLabel(operatorInput)
                                        notice = "Identificador de operador guardado en este dispositivo."
                                    } catch (error: Exception) {
                                        notice = error.message ?: "No se pudo guardar el identificador."
                                    }
                                }
                            }) { Text("Guardar identificador") }
                        }
                    }
                }
                item {
                    Card(Modifier.fillMaxWidth()) {
                        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                            Text("Registro", style = MaterialTheme.typography.titleMedium)
                            if (selectedMeeting != null) {
                                if (ContextCompat.checkSelfPermission(context, Manifest.permission.CAMERA) == PackageManager.PERMISSION_GRANTED) {
                                    QrCamera(onCode = { code ->
                                        scope.launch {
                                            val participant = repository.participantByCode(selectedMeeting.id, code)
                                            if (participant == null) notice = "El código no pertenece al paquete de la reunión actual."
                                            else selectedParticipant = participant to "QR"
                                        }
                                    })
                                } else {
                                    OutlinedButton(onClick = { cameraPermission.launch(Manifest.permission.CAMERA) }) {
                                        Text("Permitir cámara para escanear QR")
                                    }
                                }
                                OutlinedTextField(
                                    value = query,
                                    onValueChange = { query = it },
                                    label = { Text("Buscar nombre, teléfono o código") },
                                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Text),
                                    modifier = Modifier.fillMaxWidth(),
                                )
                                searchResults.forEach { participant ->
                                    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                                        Text("${participant.name} · ${participant.phone}", Modifier.weight(1f))
                                        TextButton(onClick = { selectedParticipant = participant to "MANUAL" }) { Text("Registrar") }
                                    }
                                }
                                Button(onClick = { exportLauncher.launch("${selectedMeeting.number.toString().padStart(2, '0')}-attendance.attendance-results") }) {
                                    Text("Exportar ${attendance.size} asistencias")
                                }
                            } else {
                                Text("Selecciona una reunión para habilitar búsqueda y registro.")
                            }
                        }
                    }
                }
                item {
                    selectedMeeting?.let { meeting ->
                        Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
                            Text(
                                "Invitados ${meeting.invitedCount} · Confirmados ${meeting.confirmedCount} · Incluidos en el paquete $packageRosterCount",
                                style = MaterialTheme.typography.titleMedium,
                            )
                            Text(
                                "Asistencias ${attendance.size} · QR ${attendance.count { it.method == "QR" }} · Manual ${attendance.count { it.method == "MANUAL" }} · Pendientes de exportar ${attendance.count { it.exportedAt == null }} · Excepciones ${attendance.count { !it.exceptionNote.isNullOrBlank() }}",
                            )
                        }
                    }
                }
                items(attendance, key = { it.id }) { record ->
                    AttendanceRow(record, meetings)
                }
            }
        }
    }

    pendingMeeting?.let { meeting ->
        AlertDialog(
            onDismissRequest = { pendingMeeting = null },
            title = { Text("Cambiar reunión actual") },
            text = { Text("Confirmas trabajar en «${meeting.name}»? Las asistencias existentes no se modificarán.") },
            confirmButton = {
                TextButton(onClick = {
                    scope.launch {
                        try {
                            repository.selectMeeting(meeting.id)
                            notice = "Reunión actual cambiada a ${meeting.name}."
                            pendingMeeting = null
                        } catch (error: Exception) {
                            notice = error.message ?: "No se pudo cambiar la reunión actual."
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
            title = { Text("Confirmar asistencia") },
            text = {
                Column {
                    Text(participant.name)
                    Text("Reunión efectiva: ${selectedMeeting?.name ?: "sin seleccionar"}")
                    if (crossOrigin) Text(
                        if (selectedMeeting?.allowCrossMeetingAttendance == true)
                            "Aviso: fue convocado para ${participant.originMeetingName ?: "otra reunión"}. Confirma que se permite el acceso."
                        else "Acceso bloqueado: la reunión no permite participantes de ${participant.originMeetingName ?: "otro origen"}.",
                    )
                    Text("Método: $method")
                }
            },
            confirmButton = {
                TextButton(
                    enabled = !crossOrigin || selectedMeeting?.allowCrossMeetingAttendance == true,
                    onClick = {
                    val meeting = selectedMeeting
                    if (meeting == null) {
                        notice = "No hay reunión actual seleccionada."
                    } else {
                        scope.launch {
                            try {
                                repository.register(participant.id, meeting.id, method)
                                notice = "Asistencia de ${participant.name} registrada en ${meeting.name}."
                                selectedParticipant = null
                            } catch (error: Exception) {
                                notice = error.message ?: "No se pudo registrar la asistencia."
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
private fun AttendanceRow(record: AttendanceDisplay, meetings: List<LocalMeeting>) {
    Card(Modifier.fillMaxWidth()) {
        Column(Modifier.padding(12.dp)) {
            Text(record.participantName)
            Text("ID: ${record.participantId}")
            Text("Origen: ${record.originMeetingName ?: "Sin reunión de origen"} · Efectiva: ${meetings.firstOrNull { it.id == record.effectiveMeetingId }?.name ?: record.effectiveMeetingId}")
            Text("${record.recordedAt} · ${record.method} · UUID ${record.id}")
            Text(if (record.exportedAt == null) "Pendiente de exportar" else "Exportado ${record.exportedAt}")
            if (record.exceptionNote.isNotBlank()) Text("Excepción: ${record.exceptionNote}")
        }
    }
}

@Composable
private fun QrCamera(onCode: (String) -> Unit) {
    val lifecycleOwner = LocalLifecycleOwner.current
    val executor = remember { Executors.newSingleThreadExecutor() }
    val scanner = remember { BarcodeScanning.getClient() }
    val delivered = remember { AtomicBoolean(false) }
    AndroidView(
        modifier = Modifier.fillMaxWidth().height(260.dp),
        factory = { viewContext ->
            val previewView = PreviewView(viewContext)
            val providerFuture = ProcessCameraProvider.getInstance(viewContext)
            providerFuture.addListener({
                val provider = providerFuture.get()
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
            scanner.close()
            executor.shutdown()
        }
    }
}
