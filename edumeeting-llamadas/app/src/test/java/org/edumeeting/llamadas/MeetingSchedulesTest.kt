package org.edumeeting.llamadas

import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test

class MeetingSchedulesTest {
    private val meeting = JSONObject(
        """
        {
          "id": "m1", "name": "Piura", "location": "Auditorio", "active": true, "call_phase": "confirmation",
          "schedules": [
            {"id": "s1", "starts_at": "2025-05-10T15:00:00Z", "location": "", "starts_at_local": "2025-05-10 10:00",
             "label": "10/05/2025 10:00", "participant_count": 2},
            {"id": "s2", "starts_at": "2025-05-11T20:30:00Z", "location": "Sala B", "starts_at_local": "2025-05-11 15:30",
             "label": "11/05/2025 15:30 · Sala B", "participant_count": 0}
          ],
          "call_lease_minutes": 12, "retry_delay_minutes": 30, "max_call_attempts": 4,
          "follow_up_delay_minutes": 90, "prioritize_follow_ups": false
        }
        """.trimIndent(),
    )

    @Test
    fun parsesManagedMeetingWithSchedulesAndQueueRules() {
        val parsed = parseManagedMeeting(meeting)
        assertEquals("Piura", parsed.name)
        assertEquals(PHASE_CONFIRMATION, parsed.callPhase)
        assertEquals(listOf("s1", "s2"), parsed.schedules.map { it.id })
        assertEquals(ScheduleDraft("s2", "2025-05-11", "15:30", "Sala B", 0), parsed.schedules[1])
        assertEquals(2, parsed.schedules[0].participantCount)
        assertEquals(QueueSettings("12", "30", "4", "90", false), parsed.queue)
    }

    @Test
    fun missingPhaseDefaultsToInvitation() {
        val parsed = parseManagedMeeting(JSONObject().put("id", "m2").put("name", "Lima"))
        assertEquals(PHASE_INVITATION, parsed.callPhase)
        assertTrue(parsed.schedules.isEmpty())
    }

    @Test
    fun scheduleOptionsUseServerLabels() {
        assertEquals(
            listOf(ScheduleOption("s1", "10/05/2025 10:00"), ScheduleOption("s2", "11/05/2025 15:30 · Sala B")),
            scheduleOptions(meeting),
        )
        assertEquals(listOf(ScheduleOption("s1", "10/05/2025 10:00")), parseScheduleOptions(meeting.getJSONArray("schedules").also { it.remove(1) }))
    }

    @Test
    fun requestBodyKeepsIdsAndSkipsEmptyRows() {
        val body = meetingRequestBody(
            "Piura", "Auditorio",
            listOf(ScheduleDraft("s1", "2025-05-10", "10:00"), ScheduleDraft(day = "2025-05-12", time = "09:15", location = "Patio"), ScheduleDraft()),
            QueueSettings("12", "30", "4", "90", false),
            callPhase = PHASE_CONFIRMATION,
        )
        val schedules = body.getJSONArray("schedules")
        assertEquals(2, schedules.length())
        assertEquals("s1", schedules.getJSONObject(0).getString("id"))
        assertEquals("2025-05-10 10:00", schedules.getJSONObject(0).getString("starts_at"))
        assertFalse(schedules.getJSONObject(1).has("id"))
        assertEquals("Patio", schedules.getJSONObject(1).getString("location"))
        assertEquals(PHASE_CONFIRMATION, body.getString("call_phase"))
        assertEquals(4, body.getInt("max_call_attempts"))
        assertFalse(body.getBoolean("prioritize_follow_ups"))
        assertFalse(meetingRequestBody("X", "", listOf(ScheduleDraft(day = "2025-05-12", time = "09:15")), QueueSettings(), null).has("call_phase"))
    }

    @Test
    fun scheduleProblemsAreReportedBeforeSending() {
        assertNotNull(scheduleProblem(listOf(ScheduleDraft())))
        assertNotNull(scheduleProblem(listOf(ScheduleDraft(day = "2025-05-10", time = "10:00"), ScheduleDraft(day = "2025-05-11"))))
        assertNotNull(scheduleProblem(listOf(ScheduleDraft(day = "2025-05-10", time = "10:00"), ScheduleDraft(day = "2025-05-10", time = "10:00"))))
        assertNull(scheduleProblem(listOf(ScheduleDraft(day = "2025-05-10", time = "10:00"), ScheduleDraft())))
    }

    @Test
    fun queueSettingsValidateRanges() {
        assertTrue(QueueSettings().valid)
        assertFalse(QueueSettings(leaseMinutes = "0").valid)
        assertFalse(QueueSettings(maxAttempts = "").valid)
        assertFalse(QueueSettings(retryDelayMinutes = "20000").valid)
    }
}
