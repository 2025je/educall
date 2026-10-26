package org.edumeeting.llamadas

import org.edumeeting.ui.*
import android.app.DatePickerDialog
import android.app.TimePickerDialog
import android.text.format.DateFormat
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Check
import androidx.compose.material.icons.filled.DateRange
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.Notifications
import androidx.compose.material.icons.filled.Place
import androidx.compose.material3.FilterChip
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedCard
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardCapitalization
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import org.json.JSONArray
import org.json.JSONObject
import java.time.LocalDate
import java.time.LocalDateTime
import java.time.LocalTime
import java.time.format.DateTimeFormatter

/** Horario de una reunión tal como se edita en el formulario (fecha AAAA-MM-DD y hora HH:MM locales). */
internal data class ScheduleDraft(
    val id: String? = null,
    val day: String = "",
    val time: String = "",
    val location: String = "",
    val participantCount: Int = 0,
) {
    val complete: Boolean get() = day.isNotBlank() && time.isNotBlank()
}

/** Reglas de la cola configurables por el administrador. */
internal data class QueueSettings(
    val leaseMinutes: String = "10",
    val retryDelayMinutes: String = "15",
    val maxAttempts: String = "3",
    val followUpDelayMinutes: String = "60",
    val prioritizeFollowUps: Boolean = true,
) {
    val valid: Boolean
        get() = leaseMinutes.toIntOrNull() in 1..60 && retryDelayMinutes.toIntOrNull() in 1..1440 &&
            maxAttempts.toIntOrNull() in 1..20 && followUpDelayMinutes.toIntOrNull() in 0..10080
}

internal data class ManagedMeeting(
    val id: String,
    val name: String,
    val location: String,
    val active: Boolean,
    val callPhase: String,
    val schedules: List<ScheduleDraft>,
    val queue: QueueSettings,
)

/** Horario elegible para un participante: id y etiqueta legible ("dd/mm/AAAA HH:MM · lugar"). */
internal data class ScheduleOption(val id: String, val label: String)

internal const val PHASE_INVITATION = "invitation"
internal const val PHASE_CONFIRMATION = "confirmation"
internal val PHASE_LABELS = mapOf(PHASE_INVITATION to "Fase 1 · Invitación", PHASE_CONFIRMATION to "Fase 2 · Confirmación")

/** Tipos de número que el operador puede pedir a la cola durante la fase 2. */
internal val QUEUE_TYPE_LABELS = linkedMapOf(
    "confirm" to "Confirmar asistencia",
    "never_answered" to "Nunca respondieron",
    "new" to "Nuevos sin llamar",
    "follow_up" to "Seguimientos",
)

internal val INVITATION_OUTCOMES = listOf(
    "accepted" to "Aceptó", "declined" to "Rechazó", "contacted" to "Contactado", "no_answer" to "No contesta",
    "follow_up" to "Seguimiento", "do_not_contact" to "No contactar", "other" to "Otro",
)
internal val CONFIRMATION_OUTCOMES = listOf(
    "confirmed" to "Confirmó", "will_not_attend" to "No asistirá", "no_answer" to "No contesta", "follow_up" to "Seguimiento",
)
internal val INVITATION_STATUS_LABELS = mapOf(
    "not_invited" to "Sin invitar", "invited" to "Invitado", "accepted" to "Aceptó", "declined" to "Rechazó",
)
internal val CONFIRMATION_LABELS = mapOf(
    "pending" to "Sin confirmar", "confirmed" to "Confirmó asistencia", "will_not_attend" to "No asistirá",
)

internal fun parseScheduleDraft(item: JSONObject): ScheduleDraft {
    val local = item.optString("starts_at_local")
    return ScheduleDraft(
        id = item.optString("id").takeIf { it.isNotBlank() },
        day = local.substringBefore(" "),
        time = local.substringAfter(" ", ""),
        location = item.optString("location"),
        participantCount = item.optInt("participant_count"),
    )
}

internal fun parseManagedMeeting(item: JSONObject): ManagedMeeting {
    val schedules = item.optJSONArray("schedules") ?: JSONArray()
    return ManagedMeeting(
        id = item.getString("id"),
        name = item.getString("name"),
        location = item.optString("location"),
        active = item.optBoolean("active", true),
        callPhase = item.optString("call_phase", PHASE_INVITATION).ifBlank { PHASE_INVITATION },
        schedules = (0 until schedules.length()).map { parseScheduleDraft(schedules.getJSONObject(it)) },
        queue = QueueSettings(
            leaseMinutes = item.optInt("call_lease_minutes", 10).toString(),
            retryDelayMinutes = item.optInt("retry_delay_minutes", 15).toString(),
            maxAttempts = item.optInt("max_call_attempts", 3).toString(),
            followUpDelayMinutes = item.optInt("follow_up_delay_minutes", 60).toString(),
            prioritizeFollowUps = item.optBoolean("prioritize_follow_ups", true),
        ),
    )
}

/** Opciones de horario incluidas en una tarea de llamada (`task.meeting.schedules`). */
internal fun parseScheduleOptions(array: JSONArray?): List<ScheduleOption> =
    if (array == null) emptyList() else (0 until array.length()).map { index ->
        val item = array.getJSONObject(index)
        ScheduleOption(item.getString("id"), item.optString("label"))
    }

/** Opciones de horario a partir de los horarios de la reunión (`/api/v1/meetings/`). */
internal fun scheduleOptions(meeting: JSONObject): List<ScheduleOption> {
    val array = meeting.optJSONArray("schedules") ?: return emptyList()
    return (0 until array.length()).map { index ->
        val item = array.getJSONObject(index)
        ScheduleOption(item.getString("id"), item.optString("label").ifBlank { item.optString("starts_at_local") })
    }
}

internal fun meetingRequestBody(
    name: String,
    location: String,
    schedules: List<ScheduleDraft>,
    queue: QueueSettings,
    callPhase: String?,
): JSONObject {
    val items = JSONArray()
    schedules.filter { it.complete }.forEach { schedule ->
        items.put(JSONObject().apply {
            schedule.id?.let { put("id", it) }
            put("starts_at", "${schedule.day} ${schedule.time}")
            put("location", schedule.location)
        })
    }
    return JSONObject()
        .put("name", name)
        .put("location", location)
        .put("schedules", items)
        .put("call_lease_minutes", queue.leaseMinutes.toInt())
        .put("retry_delay_minutes", queue.retryDelayMinutes.toInt())
        .put("max_call_attempts", queue.maxAttempts.toInt())
        .put("follow_up_delay_minutes", queue.followUpDelayMinutes.toInt())
        .put("prioritize_follow_ups", queue.prioritizeFollowUps)
        .apply { callPhase?.let { put("call_phase", it) } }
}

/** Mensaje de error local; null cuando los horarios pueden enviarse. */
internal fun scheduleProblem(schedules: List<ScheduleDraft>): String? {
    val complete = schedules.filter { it.complete }
    if (complete.isEmpty()) return "Agrega al menos un horario con fecha y hora."
    if (schedules.any { !it.complete && (it.day.isNotBlank() || it.time.isNotBlank() || it.id != null) }) {
        return "Completa la fecha y la hora de cada horario."
    }
    if (complete.map { it.day to it.time }.toSet().size != complete.size) return "Hay dos horarios con la misma fecha y hora."
    return null
}

private val isoDay = DateTimeFormatter.ISO_LOCAL_DATE
private val isoTime = DateTimeFormatter.ofPattern("HH:mm")
private val shownDay = DateTimeFormatter.ofPattern("dd/MM/yyyy")

/** Lista editable de horarios de la reunión. Un horario con participantes no puede eliminarse. */
@Composable
internal fun ScheduleListEditor(
    schedules: List<ScheduleDraft>,
    enabled: Boolean,
    onChange: (List<ScheduleDraft>) -> Unit,
) {
    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Text("Horarios", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)
        Text(
            "El operador asigna a cada persona uno de estos horarios. Si un horario no indica lugar se usa el de la reunión.",
            style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        schedules.forEachIndexed { index, schedule ->
            OutlinedCard(Modifier.fillMaxWidth()) {
                Column(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Text("Horario ${index + 1}", Modifier.weight(1f), fontWeight = FontWeight.Bold)
                        if (schedule.participantCount > 0) {
                            Text("${schedule.participantCount} asignado(s)", style = MaterialTheme.typography.labelSmall)
                        }
                        IconButton(
                            enabled = enabled && schedules.size > 1 && schedule.participantCount == 0,
                            onClick = { onChange(schedules.filterIndexed { position, _ -> position != index }) },
                        ) { Icon(Icons.Default.Delete, "Eliminar horario ${index + 1}") }
                    }
                    MeetingDateTimePickers(
                        day = schedule.day, time = schedule.time, enabled = enabled,
                        onDayChange = { day -> onChange(schedules.mapIndexed { i, s -> if (i == index) s.copy(day = day) else s }) },
                        onTimeChange = { time -> onChange(schedules.mapIndexed { i, s -> if (i == index) s.copy(time = time) else s }) },
                    )
                    FormTextField(
                        value = schedule.location,
                        onValueChange = { value -> onChange(schedules.mapIndexed { i, s -> if (i == index) s.copy(location = value) else s }) },
                        label = "Lugar de este horario (opcional)", leadingIcon = Icons.Default.Place,
                        capitalization = KeyboardCapitalization.Sentences, imeAction = ImeAction.Done,
                        modifier = Modifier.fillMaxWidth(),
                    )
                }
            }
        }
        OutlinedButton(enabled = enabled, onClick = { onChange(schedules + ScheduleDraft()) }) {
            ActionLabel("Agregar horario", Icons.Default.Add)
        }
        Text(
            "Código de asistencia: iniciales del operador y su correlativo, por ejemplo JU-0001.",
            style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
    }
}

@Composable
internal fun QueueSettingsEditor(settings: QueueSettings, enabled: Boolean, onChange: (QueueSettings) -> Unit) {
    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Text("Reglas de la cola", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)
        val number = @Composable { value: String, label: String, help: String, update: (String) -> QueueSettings ->
            FormTextField(
                value = value, onValueChange = { onChange(update(digitsOnly(it, 5))) }, label = label, supportingText = help,
                leadingIcon = Icons.Default.Notifications, keyboardType = KeyboardType.Number, enabled = enabled,
                modifier = Modifier.fillMaxWidth(),
            )
        }
        number(settings.leaseMinutes, "Minutos para registrar el resultado", "1 a 60; luego la llamada vuelve a la cola.") { settings.copy(leaseMinutes = it) }
        number(settings.retryDelayMinutes, "Espera tras «No contesta» (min)", "1 a 1440.") { settings.copy(retryDelayMinutes = it) }
        number(settings.maxAttempts, "Intentos «No contesta» por fase", "1 a 20; al llegar al límite la llamada se agota.") { settings.copy(maxAttempts = it) }
        number(settings.followUpDelayMinutes, "Espera de un seguimiento sin hora (min)", "0 a 10080 (7 días).") { settings.copy(followUpDelayMinutes = it) }
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text("Priorizar seguimientos vencidos", Modifier.weight(1f))
            Switch(checked = settings.prioritizeFollowUps, enabled = enabled, onCheckedChange = { onChange(settings.copy(prioritizeFollowUps = it)) })
        }
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
internal fun CallPhaseSelector(phase: String, enabled: Boolean, onChange: (String) -> Unit) {
    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Text("Fase de llamadas", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)
        FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            PHASE_LABELS.forEach { (value, label) ->
                FilterChip(
                    selected = phase == value, enabled = enabled, onClick = { onChange(value) }, label = { Text(label) },
                    leadingIcon = { if (phase == value) Icon(Icons.Default.Check, null, Modifier.size(18.dp)) },
                    modifier = Modifier.heightIn(min = 48.dp),
                )
            }
        }
        Text(
            if (phase == PHASE_CONFIRMATION) {
                "Fase 2: se confirma la asistencia de quienes aceptaron y se vuelve a llamar a quienes nunca respondieron. " +
                    "Al pasar a esta fase se reinician los intentos «No contesta»."
            } else {
                "Fase 1: los operadores invitan y asignan el horario al que asistirá cada persona."
            },
            style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
    }
}

/** Selección de un horario de la reunión; [selected] es el id elegido. */
@OptIn(ExperimentalLayoutApi::class)
@Composable
internal fun SchedulePicker(
    options: List<ScheduleOption>,
    selected: String?,
    enabled: Boolean,
    title: String,
    onSelect: (String) -> Unit,
) {
    Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
        Text(title, fontWeight = FontWeight.Bold)
        if (options.isEmpty()) Text("La reunión no tiene horarios.", color = MaterialTheme.colorScheme.error)
        FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            options.forEach { option ->
                FilterChip(
                    selected = selected == option.id, enabled = enabled, onClick = { onSelect(option.id) },
                    label = { Text(option.label) },
                    leadingIcon = { Icon(if (selected == option.id) Icons.Default.Check else Icons.Default.DateRange, null, Modifier.size(18.dp)) },
                    modifier = Modifier.heightIn(min = 48.dp),
                )
            }
        }
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
internal fun QueueTypeSelector(selected: Set<String>, enabled: Boolean, onChange: (Set<String>) -> Unit) {
    Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
        Text("Números que quieres recibir", fontWeight = FontWeight.Bold)
        FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            QUEUE_TYPE_LABELS.forEach { (value, label) ->
                val checked = value in selected
                FilterChip(
                    selected = checked, enabled = enabled,
                    onClick = { onChange(if (checked) selected - value else selected + value) },
                    label = { Text(label) },
                    leadingIcon = { if (checked) Icon(Icons.Default.Check, null, Modifier.size(18.dp)) },
                    modifier = Modifier.heightIn(min = 48.dp),
                )
            }
        }
        if (selected.isEmpty()) Text("Elige al menos un tipo.", color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.bodySmall)
    }
}

/** Fecha y hora opcionales para agendar un seguimiento; devuelve "AAAA-MM-DD HH:MM" o vacío. */
@Composable
internal fun FollowUpPicker(value: String, enabled: Boolean, onChange: (String) -> Unit) {
    val context = LocalContext.current
    val current = runCatching { LocalDateTime.parse(value, DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm")) }.getOrNull()
    Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        OutlinedButton(enabled = enabled, modifier = Modifier.weight(1f), onClick = {
            val initial = current ?: LocalDateTime.now().plusHours(1).withMinute(0)
            DatePickerDialog(context, { _, year, month, day ->
                TimePickerDialog(context, { _, hour, minute ->
                    onChange(LocalDateTime.of(LocalDate.of(year, month + 1, day), LocalTime.of(hour, minute)).format(DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm")))
                }, initial.hour, initial.minute, DateFormat.is24HourFormat(context)).show()
            }, initial.year, initial.monthValue - 1, initial.dayOfMonth).show()
        }) {
            ActionLabel(current?.let { "Seguimiento: ${it.format(shownDay)} ${it.format(isoTime)}" } ?: "Hora del seguimiento (opcional)", Icons.Default.DateRange)
        }
        if (current != null) TextButton(enabled = enabled, onClick = { onChange("") }) { Text("Quitar") }
    }
}
