package org.edumeeting.asistencia.data

import android.content.ContentResolver
import android.net.Uri
import android.util.Base64
import java.io.ByteArrayOutputStream
import java.security.KeyFactory
import java.security.Signature
import java.security.spec.X509EncodedKeySpec
import java.util.zip.ZipInputStream
import java.util.UUID
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive

/** Código actual (INICIALES-SSSS) y los anteriores a los horarios (INICIALES-[DDMMAA-]NN-SSS). */
internal val ATTENDANCE_CODE = Regex("^[A-Z]{2}-([0-9]{4,}|([0-9]{6}-)?[0-9]{2}-[0-9]{3,})$")

object AttendancePackageImporter {
    private const val MAX_PACKAGE_BYTES = 25 * 1024 * 1024
    private val json = Json { ignoreUnknownKeys = false }
    private val allowedFiles = setOf("manifest.json", "manifest.sig", "meeting.json", "participants.json", "verification.json")

    fun read(resolver: ContentResolver, uri: Uri, pinnedPublicKeyBase64: String): Pair<LocalMeeting, List<LocalParticipant>> {
        require(pinnedPublicKeyBase64.isNotBlank()) { "La aplicación no tiene configurada la clave pública confiable." }
        val files = mutableMapOf<String, ByteArray>()
        var total = 0
        resolver.openInputStream(uri)?.use { input ->
            ZipInputStream(input).use { zip ->
                while (true) {
                    val entry = zip.nextEntry ?: break
                    require(!entry.isDirectory && entry.name in allowedFiles) { "El paquete contiene una entrada inesperada." }
                    require(entry.name !in files) { "El paquete contiene entradas duplicadas." }
                    val output = ByteArrayOutputStream()
                    val buffer = ByteArray(8192)
                    while (true) {
                        val count = zip.read(buffer)
                        if (count < 0) break
                        total += count
                        require(total <= MAX_PACKAGE_BYTES) { "El paquete supera el tamaño permitido." }
                        output.write(buffer, 0, count)
                    }
                    files[entry.name] = output.toByteArray()
                    zip.closeEntry()
                }
            }
        } ?: error("No se pudo abrir el archivo seleccionado.")
        require(files.keys == allowedFiles) { "El paquete está incompleto." }

        val pinnedBytes = Base64.decode(pinnedPublicKeyBase64, Base64.DEFAULT)
        val verification = json.parseToJsonElement(files.getValue("verification.json").decodeToString()).jsonObject
        val packagedBytes = Base64.decode(verification.getValue("public_key").jsonPrimitive.content, Base64.DEFAULT)
        require(pinnedBytes.contentEquals(packagedBytes)) { "La clave pública del paquete no coincide con la clave confiable de la aplicación." }
        val x509Prefix = byteArrayOf(0x30, 0x2A, 0x30, 0x05, 0x06, 0x03, 0x2B, 0x65, 0x70, 0x03, 0x21, 0x00)
        val publicKey = KeyFactory.getInstance("Ed25519").generatePublic(X509EncodedKeySpec(x509Prefix + pinnedBytes))
        val verifier = Signature.getInstance("Ed25519")
        verifier.initVerify(publicKey)
        val manifestBytes = files.getValue("manifest.json")
        verifier.update(manifestBytes)
        require(verifier.verify(Base64.decode(files.getValue("manifest.sig"), Base64.DEFAULT))) {
            "La firma del paquete no es válida."
        }

        val manifest = json.parseToJsonElement(manifestBytes.decodeToString()).jsonObject
        require(manifest.getValue("schema_version").jsonPrimitive.content.toInt() == 1) {
            "La versión del paquete no es compatible."
        }
        val digests = manifest.getValue("files").jsonObject
        for ((name, expected) in digests) {
            require(name in allowedFiles && name != "manifest.json" && name != "manifest.sig") {
                "El manifiesto referencia un archivo inesperado."
            }
            val actual = java.security.MessageDigest.getInstance("SHA-256")
                .digest(files.getValue(name)).joinToString("") { "%02x".format(it.toInt() and 0xFF) }
            require(actual == expected.jsonPrimitive.content) { "El archivo $name fue alterado." }
        }
        require(digests.keys == setOf("meeting.json", "participants.json", "verification.json")) {
            "Los hashes del manifiesto están incompletos."
        }
        val packageId = manifest.getValue("package_id").jsonPrimitive.content
        val meetingData = json.parseToJsonElement(files.getValue("meeting.json").decodeToString()).jsonObject
        val meetingId = meetingData.getValue("id").jsonPrimitive.content
        UUID.fromString(packageId)
        UUID.fromString(meetingId)
        require(meetingId == manifest.getValue("meeting_id").jsonPrimitive.content)
        val pinHash = meetingData["attendance_pin_hash"]?.takeUnless { it.toString() == "null" }?.jsonPrimitive?.content.orEmpty()
        require(AttendancePin.isValidHash(pinHash)) {
            "El paquete no incluye el PIN de la reunión. Define el PIN en el servidor y exporta un paquete nuevo."
        }
        val schedules = meetingData["schedules"]?.jsonArray.orEmpty().map { element ->
            val schedule = element.jsonObject
            UUID.fromString(schedule.getValue("id").jsonPrimitive.content)
            schedule.getValue("label").jsonPrimitive.content
        }
        require(schedules.isNotEmpty()) { "El paquete no incluye los horarios de la reunión." }
        val meeting = LocalMeeting(
            id = meetingId,
            name = meetingData.getValue("name").jsonPrimitive.content,
            schedules = schedules.joinToString("\n"),
            location = meetingData.getValue("location").jsonPrimitive.content,
            allowCrossMeetingAttendance = meetingData.getValue("allow_cross_meeting_attendance").jsonPrimitive.content.toBooleanStrict(),
            invitedCount = meetingData.getValue("invited_count").jsonPrimitive.content.toInt(),
            confirmedCount = meetingData.getValue("confirmed_count").jsonPrimitive.content.toInt(),
            packageId = packageId,
            packageExportedAt = manifest.getValue("exported_at").jsonPrimitive.content,
            pinHash = pinHash,
        )
        val participants = json.parseToJsonElement(files.getValue("participants.json").decodeToString())
            .jsonArray.map { element ->
                val item = element.jsonObject
                val participantId = item.getValue("id").jsonPrimitive.content
                val code = item.getValue("code").jsonPrimitive.content
                UUID.fromString(participantId)
                item["origin_meeting_id"]?.takeUnless { it.toString() == "null" }?.jsonPrimitive?.content?.let {
                    UUID.fromString(it)
                }
                require(ATTENDANCE_CODE.matches(code)) {
                    "El paquete contiene un código de asistencia inválido."
                }
                LocalParticipant(
                    id = participantId,
                    name = item.getValue("name").jsonPrimitive.content,
                    phone = item.getValue("phone").jsonPrimitive.content,
                    originMeetingId = item["origin_meeting_id"]?.takeUnless { it.toString() == "null" }?.jsonPrimitive?.content,
                    originMeetingName = item["origin_meeting_name"]?.takeUnless { it.toString() == "null" }?.jsonPrimitive?.content,
                    meetingId = meetingId,
                    code = code,
                    scheduleLabel = item["schedule_label"]?.takeUnless { it.toString() == "null" }?.jsonPrimitive?.content.orEmpty(),
                    attendanceConfirmation = item["attendance_confirmation"]?.takeUnless { it.toString() == "null" }?.jsonPrimitive?.content.orEmpty(),
                )
            }
        require(participants.map { it.id }.distinct().size == participants.size) {
            "El paquete repite identificadores de participantes."
        }
        require(participants.map { it.code }.distinct().size == participants.size) {
            "El paquete repite códigos de asistencia."
        }
        require(participants.all { it.id.isNotBlank() && it.code.isNotBlank() }) {
            "El paquete contiene participantes incompletos."
        }
        return meeting to participants
    }
}
