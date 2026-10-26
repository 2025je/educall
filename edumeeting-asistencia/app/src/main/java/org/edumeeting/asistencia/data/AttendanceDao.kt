package org.edumeeting.asistencia.data

import androidx.room.Dao
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.Query
import kotlinx.coroutines.flow.Flow

data class AttendanceDisplay(
    val id: String,
    val participantId: String,
    val participantName: String,
    val originMeetingId: String?,
    val originMeetingName: String?,
    val effectiveMeetingId: String,
    val method: String,
    val recordedAt: String,
    val exportedAt: String?,
    val exceptionNote: String,
)

@Dao
interface AttendanceDao {
    @Query("SELECT * FROM LocalMeeting ORDER BY startsAt, number")
    fun meetings(): Flow<List<LocalMeeting>>

    @Query("SELECT * FROM LocalMeeting WHERE id = :id")
    suspend fun meeting(id: String): LocalMeeting?

    @Query("SELECT COUNT(*) FROM LocalParticipant WHERE meetingId = :meetingId")
    fun participantCount(meetingId: String): Flow<Int>

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun putMeeting(meeting: LocalMeeting)

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun putParticipants(participants: List<LocalParticipant>)

    @Query("SELECT * FROM LocalParticipant WHERE meetingId = :meetingId AND (name LIKE '%' || :query || '%' OR phone LIKE '%' || :query || '%' OR code LIKE '%' || :query || '%') ORDER BY name LIMIT 50")
    fun search(meetingId: String, query: String): Flow<List<LocalParticipant>>

    @Query("SELECT * FROM LocalParticipant WHERE meetingId = :meetingId AND code = :code LIMIT 1")
    suspend fun byCode(meetingId: String, code: String): LocalParticipant?

    @Query("SELECT * FROM LocalParticipant WHERE id = :id AND meetingId = :meetingId LIMIT 1")
    suspend fun participant(id: String, meetingId: String): LocalParticipant?

    @Query("SELECT * FROM LocalAttendance WHERE participantId = :participantId AND effectiveMeetingId = :meetingId LIMIT 1")
    suspend fun attendance(participantId: String, meetingId: String): LocalAttendance?

    @Insert
    suspend fun insertAttendance(attendance: LocalAttendance)

    @Query("SELECT LocalAttendance.id, LocalAttendance.participantId, LocalAttendance.participantName, LocalAttendance.originMeetingId, LocalAttendance.originMeetingName, LocalAttendance.effectiveMeetingId, LocalAttendance.method, LocalAttendance.recordedAt, LocalAttendance.exportedAt, LocalAttendance.exceptionNote FROM LocalAttendance WHERE LocalAttendance.effectiveMeetingId = :meetingId ORDER BY LocalAttendance.recordedAt")
    fun attendanceForMeeting(meetingId: String): Flow<List<AttendanceDisplay>>

    @Query("SELECT * FROM LocalAttendance WHERE effectiveMeetingId = :meetingId ORDER BY recordedAt")
    suspend fun attendanceForExport(meetingId: String): List<LocalAttendance>

    @Query("UPDATE LocalAttendance SET exportedAt = :exportedAt WHERE id IN (:ids)")
    suspend fun markExported(ids: List<String>, exportedAt: String)

    @Insert
    suspend fun auditSelection(audit: MeetingSelectionAudit)
}
