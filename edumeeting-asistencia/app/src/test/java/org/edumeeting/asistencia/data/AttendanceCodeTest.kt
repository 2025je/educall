package org.edumeeting.asistencia.data

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class AttendanceCodeTest {
    @Test
    fun acceptsCurrentAndLegacyCodes() {
        listOf("JU-0001", "AB-12345", "JU-251026-07-001", "JU-07-001").forEach { assertTrue(it, ATTENDANCE_CODE.matches(it)) }
    }

    @Test
    fun rejectsMalformedCodes() {
        listOf("JU-001", "ju-0001", "J-0001", "JU-0001-", "JU-2510-07-001", "").forEach { assertFalse(it, ATTENDANCE_CODE.matches(it)) }
    }
}
