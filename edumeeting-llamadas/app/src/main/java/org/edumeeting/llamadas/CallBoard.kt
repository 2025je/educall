package org.edumeeting.llamadas

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.compose.LocalLifecycleOwner
import androidx.lifecycle.repeatOnLifecycle
import java.time.Duration
import java.time.Instant
import java.time.OffsetDateTime
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import kotlin.coroutines.cancellation.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.withContext
import org.edumeeting.ui.EmptyState
import org.edumeeting.ui.StatCard
import org.json.JSONObject

internal data class OperatorCallState(
    val username: String,
    val fullName: String,
    val state: String,
    val stateLabel: String,
    val participant: String?,
    val callStatus: String?,
    val since: Instant?,
    val lastOutcome: String?,
    val lastParticipant: String?,
    val lastAt: Instant?,
    val attempts: Int,
    val attemptsLast24h: Int,
    val accepted: Int,
)

internal data class CallBoard(
    val meetingName: String,
    val onCall: Int,
    val queue: Map<String, Int>,
    val operators: List<OperatorCallState>,
    val lastEventId: Long,
    val callPhase: String = PHASE_INVITATION,
)

private fun JSONObject.instant(name: String): Instant = OffsetDateTime.parse(getString(name)).toInstant()

internal fun parseCallBoard(json: JSONObject): CallBoard {
    val queue = json.getJSONObject("queue")
    val operators = json.getJSONArray("operators")
    return CallBoard(
        meetingName = json.getString("meeting_name"),
        onCall = json.getInt("on_call"),
        queue = listOf("pending", "scheduled", "follow_up", "in_progress", "completed", "exhausted", "to_confirm")
            .associateWith { queue.optInt(it) },
        callPhase = json.optString("call_phase", PHASE_INVITATION).ifBlank { PHASE_INVITATION },
        operators = (0 until operators.length()).map { index ->
            val item = operators.getJSONObject(index)
            val call = item.optJSONObject("current_call")
            val last = item.optJSONObject("last_attempt")
            OperatorCallState(
                username = item.getString("username"),
                fullName = item.optString("full_name"),
                state = item.getString("state"),
                stateLabel = item.getString("state_label"),
                participant = call?.getString("participant"),
                callStatus = call?.getString("status_label"),
                since = call?.instant("since"),
                lastOutcome = last?.getString("outcome_label"),
                lastParticipant = last?.getString("participant"),
                lastAt = last?.instant("at"),
                attempts = item.getInt("call_attempts"),
                attemptsLast24h = item.getInt("attempts_last_24h"),
                accepted = item.getInt("accepted"),
            )
        },
        lastEventId = json.optLong("last_event_id"),
    )
}

internal fun elapsedLabel(since: Instant, now: Instant): String {
    val seconds = Duration.between(since, now).seconds.coerceAtLeast(0)
    val minutes = seconds / 60
    return if (minutes > 0) "$minutes min ${seconds % 60} s" else "$seconds s"
}

private val clockFormat = DateTimeFormatter.ofPattern("HH:mm").withZone(ZoneId.systemDefault())

/** Live view of the operators' calls for the meeting administrator; refreshes on every "calls" event. */
@Composable
internal fun LiveCallBoard(api: DjangoSessionApi) {
    var board by remember { mutableStateOf<CallBoard?>(null) }
    var live by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }
    var updatedAt by remember { mutableStateOf<Instant?>(null) }
    var now by remember { mutableStateOf(Instant.now()) }
    val lifecycle = LocalLifecycleOwner.current.lifecycle

    LaunchedEffect(api, lifecycle) {
        lifecycle.repeatOnLifecycle(Lifecycle.State.STARTED) {
            var failures = 0
            while (true) {
                val snapshot = try {
                    withContext(Dispatchers.IO) { parseCallBoard(api.get("/api/v1/meetings/call-board/")) }
                } catch (cancelled: CancellationException) {
                    throw cancelled
                } catch (failure: Exception) {
                    live = false
                    error = failure.message ?: "No se pudo consultar el estado de las llamadas."
                    failures++
                    delay(minOf(30_000L, 3_000L * failures))
                    continue
                }
                failures = 0
                board = snapshot
                error = null
                updatedAt = Instant.now()
                // The stream closes every ~25 s, which also refreshes leases that expire without an event.
                try {
                    live = true
                    api.awaitEvent("calls", snapshot.lastEventId)
                } catch (cancelled: CancellationException) {
                    throw cancelled
                } catch (_: Exception) {
                    live = false
                    delay(10_000)
                }
            }
        }
    }
    LaunchedEffect(board?.onCall) {
        while (board?.onCall?.let { it > 0 } == true) {
            now = Instant.now()
            delay(1_000)
        }
    }

    OutlinedCard(Modifier.fillMaxWidth()) {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Icon(Icons.Default.Call, null, tint = MaterialTheme.colorScheme.primary)
                Text("Llamadas en tiempo real", style = MaterialTheme.typography.titleLarge, modifier = Modifier.weight(1f))
                StatusPill(if (live) "En vivo" else "Reconectando", highlighted = live)
            }
            val status = error ?: updatedAt?.let { "Actualizado a las ${DateTimeFormatter.ofPattern("HH:mm:ss").withZone(ZoneId.systemDefault()).format(it)}" }
            Text(
                status ?: "Consultando el estado de los operadores…",
                color = if (error != null) MaterialTheme.colorScheme.error else MaterialTheme.colorScheme.onSurfaceVariant,
                style = MaterialTheme.typography.bodySmall,
            )
            val current = board ?: return@Column
            Text(PHASE_LABELS[current.callPhase] ?: current.callPhase, style = MaterialTheme.typography.labelLarge, color = MaterialTheme.colorScheme.primary)
            val stats = buildList {
                add(Triple("En llamada", "${current.onCall}/${current.operators.size}", Icons.Default.Call))
                add(Triple("Pendientes", current.queue.getValue("pending").toString(), Icons.Default.DateRange))
                add(Triple("Reintentos", current.queue.getValue("scheduled").toString(), Icons.Default.Refresh))
                add(Triple("Seguimiento", current.queue.getValue("follow_up").toString(), Icons.Default.Info))
                if (current.callPhase == PHASE_CONFIRMATION) add(Triple("Por confirmar", current.queue.getValue("to_confirm").toString(), Icons.Default.CheckCircle))
                add(Triple("Agotadas", current.queue.getValue("exhausted").toString(), Icons.Default.Close))
            }
            stats.chunked(2).forEach { row ->
                Row(horizontalArrangement = Arrangement.spacedBy(12.dp), modifier = Modifier.height(IntrinsicSize.Min)) {
                    row.forEach { (label, value, icon) -> StatCard(icon, value, label, Modifier.weight(1f).fillMaxHeight()) }
                    if (row.size == 1) Spacer(Modifier.weight(1f))
                }
            }
            if (current.operators.isEmpty()) {
                EmptyState(Icons.Default.Person, "Sin operadores", "Asigna operadores a esta reunión para seguir sus llamadas.")
            }
            current.operators.forEach { operator ->
                HorizontalDivider()
                ListItem(
                    leadingContent = {
                        Icon(
                            if (operator.state == "on_call") Icons.Default.Call else Icons.Default.AccountCircle, null,
                            tint = if (operator.state == "on_call") MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    },
                    headlineContent = {
                        Text(operator.fullName.ifBlank { operator.username }, fontWeight = FontWeight.Bold)
                    },
                    supportingContent = {
                        Column(verticalArrangement = Arrangement.spacedBy(2.dp)) {
                            if (operator.participant != null) {
                                Text("Llamando a ${operator.participant}")
                                operator.since?.let { Text("${operator.callStatus} · hace ${elapsedLabel(it, now)}", style = MaterialTheme.typography.bodySmall) }
                            }
                            val last = operator.lastOutcome?.let { outcome ->
                                "Último: $outcome · ${operator.lastParticipant} · ${operator.lastAt?.let(clockFormat::format).orEmpty()}"
                            } ?: "Sin intentos registrados"
                            Text(last, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                            Text(
                                "Intentos 24 h: ${operator.attemptsLast24h} (total ${operator.attempts}) · Aceptadas: ${operator.accepted}",
                                style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant,
                            )
                        }
                    },
                    trailingContent = { StatusPill(operator.stateLabel, highlighted = operator.state == "on_call") },
                    colors = ListItemDefaults.colors(containerColor = MaterialTheme.colorScheme.surface),
                )
            }
        }
    }
}

@Composable
private fun StatusPill(text: String, highlighted: Boolean) {
    Surface(
        shape = RoundedCornerShape(50),
        color = if (highlighted) MaterialTheme.colorScheme.primary.copy(alpha = 0.14f) else MaterialTheme.colorScheme.surfaceVariant,
        contentColor = if (highlighted) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.onSurfaceVariant,
    ) {
        Text(text, style = MaterialTheme.typography.labelMedium, modifier = Modifier.padding(horizontal = 10.dp, vertical = 4.dp))
    }
}
