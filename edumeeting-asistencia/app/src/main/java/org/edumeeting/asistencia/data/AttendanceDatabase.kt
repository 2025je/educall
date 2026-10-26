package org.edumeeting.asistencia.data

import androidx.room.Database
import androidx.room.RoomDatabase
import androidx.room.migration.Migration
import androidx.sqlite.db.SupportSQLiteDatabase

@Database(
    entities = [LocalMeeting::class, LocalParticipant::class, LocalAttendance::class, MeetingSelectionAudit::class],
    version = 3,
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

        // Las reuniones ya no tienen número ni una sola fecha: tienen varios horarios.
        val MIGRATION_2_3 = object : Migration(2, 3) {
            override fun migrate(db: SupportSQLiteDatabase) {
                db.execSQL(
                    "CREATE TABLE LocalMeeting_new (id TEXT NOT NULL, name TEXT NOT NULL, schedules TEXT NOT NULL, " +
                        "location TEXT NOT NULL, allowCrossMeetingAttendance INTEGER NOT NULL, invitedCount INTEGER NOT NULL, " +
                        "confirmedCount INTEGER NOT NULL, packageId TEXT NOT NULL, packageExportedAt TEXT NOT NULL, " +
                        "pinHash TEXT NOT NULL DEFAULT '', PRIMARY KEY(id))",
                )
                db.execSQL(
                    "INSERT INTO LocalMeeting_new (id, name, schedules, location, allowCrossMeetingAttendance, invitedCount, " +
                        "confirmedCount, packageId, packageExportedAt, pinHash) SELECT id, name, startsAt, location, " +
                        "allowCrossMeetingAttendance, invitedCount, confirmedCount, packageId, packageExportedAt, pinHash FROM LocalMeeting",
                )
                db.execSQL("DROP TABLE LocalMeeting")
                db.execSQL("ALTER TABLE LocalMeeting_new RENAME TO LocalMeeting")
                db.execSQL("ALTER TABLE LocalParticipant ADD COLUMN scheduleLabel TEXT NOT NULL DEFAULT ''")
                db.execSQL("ALTER TABLE LocalParticipant ADD COLUMN attendanceConfirmation TEXT NOT NULL DEFAULT ''")
            }
        }
    }
}
