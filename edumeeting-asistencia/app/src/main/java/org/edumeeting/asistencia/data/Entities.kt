package org.edumeeting.asistencia.data

import androidx.room.Entity
import androidx.room.Index
import androidx.room.PrimaryKey

@Entity
data class LocalMeeting(
    @PrimaryKey val id: String,
    val number: Int,
    val name: String,
    val startsAt: String,
    val location: String,
    val allowCrossMeetingAttendance: Boolean,
    val invitedCount: Int,
    val confirmedCount: Int,
    val packageId: String,
    val packageExportedAt: String,
)

@Entity(
    indices = [
        Index(value = ["meetingId", "code"], unique = true),
        Index(value = ["name"]),
    ],
)
data class LocalParticipant(
    @PrimaryKey val id: String,
    val name: String,
    val phone: String,
    val originMeetingId: String?,
    val originMeetingName: String?,
    val meetingId: String,
    val code: String,
)

@Entity(
    indices = [Index(value = ["participantId", "effectiveMeetingId"], unique = true)],
)
data class LocalAttendance(
    @PrimaryKey val id: String,
    val participantId: String,
    val participantName: String,
    val originMeetingId: String?,
    val originMeetingName: String?,
    val effectiveMeetingId: String,
    val method: String,
    val recordedAt: String,
    val timezone: String,
    val deviceId: String,
    val operatorLabel: String,
    val sourcePackageId: String,
    val exceptionNote: String,
    val exportedAt: String? = null,
)

@Entity
data class MeetingSelectionAudit(
    @PrimaryKey(autoGenerate = true) val id: Long = 0,
    val previousMeetingId: String?,
    val selectedMeetingId: String,
    val operatorLabel: String,
    val changedAt: String,
)
