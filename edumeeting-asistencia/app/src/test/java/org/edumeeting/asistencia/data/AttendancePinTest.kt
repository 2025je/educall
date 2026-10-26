package org.edumeeting.asistencia.data

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class AttendancePinTest {
    // Generado por PBKDF2PasswordHasher de Django, igual que set_attendance_pin en el servidor.
    private val djangoHash = "pbkdf2_sha256\$210000\$fixedSalt12345678901z\$wkzP2DRxv+r4/ACdsATe7XzrF8m3WIq146jkjCXOZ5c="

    @Test
    fun acceptsTheServerPin() {
        assertTrue(AttendancePin.isValidHash(djangoHash))
        assertTrue(AttendancePin.verify("246810", djangoHash))
    }

    @Test
    fun rejectsWrongOrMalformedPins() {
        assertFalse(AttendancePin.verify("246811", djangoHash))
        assertFalse(AttendancePin.verify("24681", djangoHash))
        assertFalse(AttendancePin.verify("abcdef", djangoHash))
        assertFalse(AttendancePin.verify("246810", ""))
        assertFalse(AttendancePin.isValidHash(""))
        assertFalse(AttendancePin.isValidHash("md5\$1\$salt\$wkzP2DRxv+r4/ACdsATe7XzrF8m3WIq146jkjCXOZ5c="))
        assertFalse(AttendancePin.isValidHash("pbkdf2_sha256\$0\$salt\$wkzP2DRxv+r4/ACdsATe7XzrF8m3WIq146jkjCXOZ5c="))
    }
}
