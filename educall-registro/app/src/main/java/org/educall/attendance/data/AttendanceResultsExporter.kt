package org.educall.attendance.data

import android.content.ContentResolver
import android.net.Uri
import java.util.UUID
import java.util.zip.ZipEntry
import java.util.zip.ZipOutputStream
import kotlinx.serialization.Serializable
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.Json

object AttendanceResultsExporter {
    @Serializable
    private data class Results(
        val schema_version: Int,
        val export_id: String,
        val meeting_id: String,
        val source_package_id: String,
        val device_id: String,
        val operator_label: String,
        val records: List<Record>,
    )

    @Serializable
    private data class Record(
        val id: String,
        val participant_id: String,
        val participant_name: String,
        val origin_meeting_id: String?,
        val origin_meeting_name: String?,
        val effective_meeting_id: String,
        val source_package_id: String,
        val method: String,
        val recorded_at: String,
        val timezone: String,
        val device_id: String,
        val operator_label: String,
        val exception_note: String,
    )

    fun write(resolver: ContentResolver, uri: Uri, meeting: LocalMeeting, records: List<LocalAttendance>) {
        val first = records.firstOrNull()
        val data = Results(
            schema_version = 1,
            export_id = UUID.randomUUID().toString(),
            meeting_id = meeting.id,
            source_package_id = meeting.packageId,
            device_id = first?.deviceId.orEmpty(),
            operator_label = first?.operatorLabel.orEmpty(),
            records = records.map {
                Record(
                    id = it.id,
                    participant_id = it.participantId,
                    participant_name = it.participantName,
                    origin_meeting_id = it.originMeetingId,
                    origin_meeting_name = it.originMeetingName,
                    effective_meeting_id = it.effectiveMeetingId,
                    source_package_id = it.sourcePackageId,
                    method = it.method,
                    recorded_at = it.recordedAt,
                    timezone = it.timezone,
                    device_id = it.deviceId,
                    operator_label = it.operatorLabel,
                    exception_note = it.exceptionNote,
                )
            },
        )
        resolver.openOutputStream(uri, "w")?.use { output ->
            ZipOutputStream(output).use { zip ->
                zip.putNextEntry(ZipEntry("results.json"))
                zip.write(Json.encodeToString(data).toByteArray(Charsets.UTF_8))
                zip.closeEntry()
            }
        } ?: error("No se pudo guardar el archivo de resultados.")
    }
}
