package org.edumeeting.ui

import org.junit.Assert.assertEquals
import org.junit.Test

class FieldsTest {
    @Test
    fun digitsOnlyDropsNonDigitsAndTruncates() {
        assertEquals("1234", digitsOnly("12-34", 8))
        assertEquals("12", digitsOnly("1a2b3", 2))
        assertEquals("", digitsOnly("abc", 4))
    }
}