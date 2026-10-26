package org.edumeeting.asistencia.data

import androidx.room.Database
import androidx.room.RoomDatabase
import androidx.room.migration.Migration
import androidx.sqlite.db.SupportSQLiteDatabase

@Database(
    entities = [LocalMeeting::class, LocalParticipant::class, LocalAttendance::class, MeetingSelectionAudit::class],
    version = 2,
    exportSchema = true,
)
abstract class AttendanceDatabase : RoomDatabase() {
    abstract fun attendanceDao(): AttendanceDao

    companion object {
        // Las reuniones importadas antes del PIN quedan sin PIN y exigen importar un paquete nuevo.
        val MIGRATION_1_2 = object : Migration(1, 2) {
            override fun migrate(db: SupportSQLiteDatabase) {
                db.execSQL("ALTER TABLE LocalMeeting ADD COLUMN pinHash TEXT NOT NULL DEFAULT ''")
            }
        }
    }
}
