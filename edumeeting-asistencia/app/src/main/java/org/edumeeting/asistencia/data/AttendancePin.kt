package org.edumeeting.asistencia.data

import java.security.MessageDigest
import java.util.Base64
import javax.crypto.SecretKeyFactory
import javax.crypto.spec.PBEKeySpec

/** Verifica sin conexión el PIN de la reunión contra el hash PBKDF2 (formato Django) del paquete firmado. */
object AttendancePin {
    private const val ALGORITHM = "pbkdf2_sha256"
    private const val MAX_ITERATIONS = 2_000_000
    val PIN_PATTERN = Regex("^[0-9]{6,8}$")

    fun isValidHash(encoded: String): Boolean = parse(encoded) != null

    fun verify(pin: String, encoded: String): Boolean {
        val (iterations, salt, expected) = parse(encoded) ?: return false
        if (!PIN_PATTERN.matches(pin)) return false
        val spec = PBEKeySpec(pin.toCharArray(), salt.toByteArray(Charsets.UTF_8), iterations, expected.size * 8)
        return try {
            val actual = SecretKeyFactory.getInstance("PBKDF2WithHmacSHA256").generateSecret(spec).encoded
            MessageDigest.isEqual(actual, expected)
        } finally {
            spec.clearPassword()
        }
    }

    private fun parse(encoded: String): Triple<Int, String, ByteArray>? {
        val parts = encoded.split('$')
        if (parts.size != 4 || parts[0] != ALGORITHM || parts[2].isEmpty()) return null
        val iterations = parts[1].toIntOrNull()?.takeIf { it in 1..MAX_ITERATIONS } ?: return null
        val hash = runCatching { Base64.getDecoder().decode(parts[3]) }.getOrNull()?.takeIf { it.size >= 16 } ?: return null
        return Triple(iterations, parts[2], hash)
    }
}
