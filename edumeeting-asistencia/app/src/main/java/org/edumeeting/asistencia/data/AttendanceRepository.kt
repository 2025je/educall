package org.edumeeting.asistencia.data

import android.content.Context
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.intPreferencesKey
import androidx.datastore.preferences.core.longPreferencesKey
import androidx.datastore.preferences.core.stringPreferencesKey
import androidx.datastore.preferences.preferencesDataStore
import androidx.room.withTransaction
import java.time.Instant
import java.time.ZoneId
import java.util.UUID
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.withContext

private val Context.preferences by preferencesDataStore(name = "attendance")

/** Persona identificada con nombre + PIN para registrar en una reunión. */
data class Shift(val meetingId: String, val operator: String)

class AttendanceRepository(private val context: Context, private val database: AttendanceDatabase) {
    private val dao = database.attendanceDao()
    private val currentMeetingKey = stringPreferencesKey("current_meeting_id")
    private val operatorKey = stringPreferencesKey("operator_label")
    private val deviceKey = stringPreferencesKey("device_id")
    private val shiftMeetingKey = stringPreferencesKey("shift_meeting_id")
    private val failedAttemptsKey = intPreferencesKey("pin_failed_attempts")
    private val lockedUntilKey = longPreferencesKey("pin_locked_until")

    val meetings: Flow<List<LocalMeeting>> = dao.meetings()
    val currentMeetingId: Flow<String?> = context.preferences.data.map { it[currentMeetingKey] }
    val operatorLabel: Flow<String> = context.preferences.data.map { it[operatorKey] ?: "" }
    val shift: Flow<Shift?> = context.preferences.data.map { prefs ->
        val meetingId = prefs[shiftMeetingKey]
        val operator = prefs[operatorKey].orEmpty()
        if (meetingId != null && operator.isNotBlank()) Shift(meetingId, operator) else null
    }

    suspend fun startShift(meetingId: String, name: String, pin: String) {
        val operator = name.trim().replace(Regex("\\s+"), " ")
        require(operator.length in 3..128) { "Escribe tu nombre (mínimo 3 caracteres)." }
        val prefs = context.preferences.data.first()
        require(prefs[currentMeetingKey] == meetingId) { "Selecciona primero la reunión de trabajo." }
        val meeting = dao.meeting(meetingId) ?: error("La reunión no está disponible en este dispositivo.")
        require(meeting.pinHash.isNotBlank()) {
            "Esta reunión se importó sin PIN. Importa un paquete nuevo exportado por el administrador."
        }
        val now = System.currentTimeMillis()
        val lockedUntil = prefs[lockedUntilKey] ?: 0L
        check(now >= lockedUntil) {
            "Demasiados intentos fallidos. Espera ${(lockedUntil - now + 999) / 1000} segundos."
        }
        val valid = withContext(Dispatchers.Default) { AttendancePin.verify(pin.trim(), meeting.pinHash) }
        if (!valid) {
            context.preferences.edit {
                val attempts = (it[failedAttemptsKey] ?: 0) + 1
                if (attempts >= MAX_PIN_ATTEMPTS) {
                    it[lockedUntilKey] = now + PIN_LOCK_MILLIS
                    it.remove(failedAttemptsKey)
                } else {
                    it[failedAttemptsKey] = attempts
                }
            }
            error("PIN incorrecto.")
        }
        context.preferences.edit {
            it[operatorKey] = operator
            it[shiftMeetingKey] = meetingId
            it.remove(failedAttemptsKey)
            it.remove(lockedUntilKey)
        }
    }

    suspend fun endShift() {
        context.preferences.edit { it.remove(shiftMeetingKey) }
    }

    suspend fun requireShift(meetingId: String): String {
        val prefs = context.preferences.data.first()
        val operator = prefs[operatorKey].orEmpty()
        check(prefs[shiftMeetingKey] == meetingId && operator.isNotBlank()) {
            "Identifícate con tu nombre y el PIN de la reunión."
        }
        return operator
    }

    suspend fun selectMeeting(meetingId: String) {
        require(dao.meeting(meetingId) != null) { "La reunión seleccionada no está disponible localmente." }
        val previous = context.preferences.data.first()[currentMeetingKey]
        database.withTransaction {
            dao.auditSelection(
                MeetingSelectionAudit(
                    previousMeetingId = previous,
                    selectedMeetingId = meetingId,
                    operatorLabel = context.preferences.data.first()[operatorKey] ?: "",
                    changedAt = Instant.now().toString(),
                ),
            )
        }
        context.preferences.edit {
            it[currentMeetingKey] = meetingId
            if (it[shiftMeetingKey] != meetingId) it.remove(shiftMeetingKey)
        }
    }

    fun search(meetingId: String, query: String): Flow<List<LocalParticipant>> = dao.search(meetingId, query)

    suspend fun participantByCode(meetingId: String, code: String): LocalParticipant? =
        dao.byCode(meetingId, code.trim())

    suspend fun register(participantId: String, effectiveMeetingId: String, method: String) {
        require(method == "QR" || method == "MANUAL")
        val selectedMeeting = context.preferences.data.first()[currentMeetingKey]
        require(selectedMeeting == effectiveMeetingId) {
            "La reunión actual cambió. Confirma la asistencia en la reunión seleccionada."
        }
        val operator = requireShift(effectiveMeetingId)
        val meeting = dao.meeting(effectiveMeetingId) ?: error("La reunión efectiva ya no está disponible.")
        database.withTransaction {
            val participant = dao.participant(participantId, effectiveMeetingId)
                ?: error("El participante no pertenece a un paquete local válido.")
            require(
                participant.originMeetingId == null ||
                    participant.originMeetingId == effectiveMeetingId ||
                    meeting.allowCrossMeetingAttendance
            ) { "La reunión actual no permite asistentes convocados para otra reunión." }
            check(dao.attendance(participant.id, effectiveMeetingId) == null) {
                "La asistencia ya está registrada para esta reunión."
            }
            val deviceId = context.preferences.data.first()[deviceKey]
                ?: UUID.randomUUID().toString().also { id -> context.preferences.edit { it[deviceKey] = id } }
            dao.insertAttendance(
                LocalAttendance(
                    id = UUID.randomUUID().toString(),
                    participantId = participant.id,
                    participantName = participant.name,
                    originMeetingId = participant.originMeetingId,
                    originMeetingName = participant.originMeetingName,
                    effectiveMeetingId = effectiveMeetingId,
                    method = method,
                    recordedAt = Instant.now().toString(),
                    timezone = ZoneId.systemDefault().id,
                    deviceId = deviceId,
                    operatorLabel = operator,
                    sourcePackageId = meeting.packageId,
                    exceptionNote = if (participant.originMeetingId != null && participant.originMeetingId != effectiveMeetingId) {
                        "Asistencia en una reunión distinta a su origen"
                    } else "",
                ),
            )
        }
    }

    fun attendance(meetingId: String): Flow<List<AttendanceDisplay>> = dao.attendanceForMeeting(meetingId)
    fun participantCount(meetingId: String): Flow<Int> = dao.participantCount(meetingId)
    fun pendingExportTotal(): Flow<Int> = dao.pendingExportTotal()
    suspend fun attendanceForExport(meetingId: String) = dao.attendanceForExport(meetingId)
    suspend fun markExported(ids: List<String>) {
        if (ids.isNotEmpty()) dao.markExported(ids, Instant.now().toString())
    }

    suspend fun importPackage(meeting: LocalMeeting, participants: List<LocalParticipant>) {
        val previous = dao.meeting(meeting.id)
        database.withTransaction {
            dao.putMeeting(meeting)
            dao.putParticipants(participants)
        }
        // Si el PIN cambió, quien estaba identificado debe volver a escribirlo.
        if (previous != null && previous.pinHash != meeting.pinHash) {
            context.preferences.edit { if (it[shiftMeetingKey] == meeting.id) it.remove(shiftMeetingKey) }
        }
    }

    private companion object {
        const val MAX_PIN_ATTEMPTS = 5
        const val PIN_LOCK_MILLIS = 60_000L
    }
}
