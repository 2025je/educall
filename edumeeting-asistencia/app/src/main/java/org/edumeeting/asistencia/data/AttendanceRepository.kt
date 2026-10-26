package org.edumeeting.asistencia.data

import android.content.Context
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.stringPreferencesKey
import androidx.datastore.preferences.preferencesDataStore
import androidx.room.withTransaction
import java.time.Instant
import java.time.ZoneId
import java.util.UUID
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.map

private val Context.preferences by preferencesDataStore(name = "attendance")

class AttendanceRepository(private val context: Context, private val database: AttendanceDatabase) {
    private val dao = database.attendanceDao()
    private val currentMeetingKey = stringPreferencesKey("current_meeting_id")
    private val operatorKey = stringPreferencesKey("operator_label")
    private val deviceKey = stringPreferencesKey("device_id")

    val meetings: Flow<List<LocalMeeting>> = dao.meetings()
    val currentMeetingId: Flow<String?> = context.preferences.data.map { it[currentMeetingKey] }
    val operatorLabel: Flow<String> = context.preferences.data.map { it[operatorKey] ?: "" }

    suspend fun setOperatorLabel(value: String) {
        context.preferences.edit { it[operatorKey] = value.trim() }
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
        context.preferences.edit { it[currentMeetingKey] = meetingId }
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
            val operator = context.preferences.data.first()[operatorKey] ?: ""
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
    suspend fun attendanceForExport(meetingId: String) = dao.attendanceForExport(meetingId)
    suspend fun markExported(ids: List<String>) {
        if (ids.isNotEmpty()) dao.markExported(ids, Instant.now().toString())
    }

    suspend fun importPackage(meeting: LocalMeeting, participants: List<LocalParticipant>) {
        database.withTransaction {
            dao.putMeeting(meeting)
            dao.putParticipants(participants)
        }
    }
}
