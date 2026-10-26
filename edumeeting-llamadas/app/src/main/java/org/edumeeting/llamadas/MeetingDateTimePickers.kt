package org.edumeeting.llamadas

import android.app.DatePickerDialog
import android.app.TimePickerDialog
import android.text.format.DateFormat
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.DateRange
import androidx.compose.material.icons.filled.Notifications
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import java.time.LocalDate
import java.time.LocalTime
import java.time.format.DateTimeFormatter

private val isoDay = DateTimeFormatter.ISO_LOCAL_DATE
private val isoTime = DateTimeFormatter.ofPattern("HH:mm")
private val shownDay = DateTimeFormatter.ofPattern("dd/MM/yyyy")

/** Fecha (AAAA-MM-DD) y hora (HH:MM) en campos separados, elegidas con calendario y reloj. */
@Composable
internal fun MeetingDateTimePickers(
    day: String,
    time: String,
    enabled: Boolean,
    onDayChange: (String) -> Unit,
    onTimeChange: (String) -> Unit,
) {
    val context = LocalContext.current
    val selectedDay = runCatching { LocalDate.parse(day, isoDay) }.getOrNull()
    val selectedTime = runCatching { LocalTime.parse(time, isoTime) }.getOrNull()
    Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
        Text("Fecha y hora de la reunión")
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.fillMaxWidth()) {
            OutlinedButton(
                enabled = enabled,
                modifier = Modifier.weight(1f),
                onClick = {
                    val initial = selectedDay ?: LocalDate.now()
                    DatePickerDialog(
                        context,
                        { _, year, month, dayOfMonth -> onDayChange(LocalDate.of(year, month + 1, dayOfMonth).format(isoDay)) },
                        initial.year, initial.monthValue - 1, initial.dayOfMonth,
                    ).show()
                },
            ) { ActionLabel(selectedDay?.format(shownDay) ?: "Elegir fecha", Icons.Default.DateRange) }
            OutlinedButton(
                enabled = enabled,
                modifier = Modifier.weight(1f),
                onClick = {
                    val initial = selectedTime ?: LocalTime.of(LocalTime.now().hour, 0)
                    TimePickerDialog(
                        context,
                        { _, hour, minute -> onTimeChange(LocalTime.of(hour, minute).format(isoTime)) },
                        initial.hour, initial.minute, DateFormat.is24HourFormat(context),
                    ).show()
                },
            ) { ActionLabel(selectedTime?.format(isoTime) ?: "Elegir hora", Icons.Default.Notifications) }
        }
    }
}

private val codeDay = DateTimeFormatter.ofPattern("ddMMyy")

/** Formato del servidor: iniciales-DDMMAA-NN-secuencia. */
internal fun previewAttendanceCode(number: String, day: String): Pair<String, String> {
    val n = number.trim().toIntOrNull()?.takeIf { it in 1..99 }
    val nn = n?.let { "%02d".format(it) } ?: "NN"
    val date = runCatching { LocalDate.parse(day, isoDay).format(codeDay) }.getOrNull() ?: "DDMMAA"
    return "JU-$date-$nn-001" to "$date = fecha (día, mes, año) · $nn = número de reunión"
}

@Composable
internal fun AttendanceCodePreview(number: String, day: String) {
    val (code, dateAndNumber) = previewAttendanceCode(number, day)
    Admonition(AdmonitionKind.Example, "Vista previa del código de asistencia") {
        CodeText(code)
        Text(
            "JU = iniciales del operador · $dateAndNumber · 001 = orden del invitado",
            style = MaterialTheme.typography.bodySmall,
        )
        Text(
            "El número no puede repetirse el mismo día; en otra fecha sí.",
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
    }
}
