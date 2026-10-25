package org.educall.attendance.data

import androidx.room.Database
import androidx.room.RoomDatabase

@Database(
    entities = [LocalMeeting::class, LocalParticipant::class, LocalAttendance::class, MeetingSelectionAudit::class],
    version = 1,
    exportSchema = true,
)
abstract class AttendanceDatabase : RoomDatabase() {
    abstract fun attendanceDao(): AttendanceDao
}
