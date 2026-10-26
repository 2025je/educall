package org.edumeeting.llamadas

import java.io.BufferedReader
import java.io.StringReader
import java.time.Instant
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test

class CallBoardTest {
    private val payload = """
        {
          "meeting_id": "m1", "meeting_name": "Piura", "generated_at": "2025-05-01T10:00:00-05:00",
          "queue": {"pending": 4, "scheduled": 1, "follow_up": 2, "in_progress": 1, "completed": 7},
          "on_call": 1, "last_event_id": 42,
          "operators": [
            {"id": 1, "username": "ana", "full_name": "Ana Luna", "state": "on_call", "state_label": "En llamada",
             "current_call": {"task_id": "t1", "participant": "Pedro", "status": "assigned", "status_label": "Asignada",
                              "since": "2025-05-01T09:58:30.123456-05:00", "lease_expires_at": "2025-05-01T10:08:30-05:00"},
             "last_attempt": null, "call_attempts": 3, "attempts_last_24h": 2, "accepted": 1},
            {"id": 2, "username": "beto", "full_name": "", "state": "idle", "state_label": "Sin llamada asignada",
             "current_call": null,
             "last_attempt": {"participant": "Rosa", "outcome": "no_answer", "outcome_label": "No contesta", "at": "2025-05-01T14:55:00Z"},
             "call_attempts": 5, "attempts_last_24h": 5, "accepted": 0}
          ]
        }
    """.trimIndent()

    @Test
    fun parsesOperatorsCurrentCallsAndQueue() {
        val board = parseCallBoard(JSONObject(payload))
        assertEquals("Piura", board.meetingName)
        assertEquals(1, board.onCall)
        assertEquals(42L, board.lastEventId)
        assertEquals(4, board.queue.getValue("pending"))
        assertEquals(1, board.queue.getValue("scheduled"))
        assertEquals(PHASE_INVITATION, board.callPhase)
        assertEquals("Older servers omit exhausted/to_confirm", 0, board.queue.getValue("to_confirm"))
        val (ana, beto) = board.operators
        assertEquals("Pedro", ana.participant)
        assertEquals("Asignada", ana.callStatus)
        assertEquals(Instant.parse("2025-05-01T14:58:30.123456Z"), ana.since)
        assertNull(ana.lastOutcome)
        assertNull(beto.participant)
        assertEquals("No contesta", beto.lastOutcome)
        assertEquals("Rosa", beto.lastParticipant)
        assertEquals("", beto.fullName)
        assertEquals(5, beto.attemptsLast24h)
    }

    @Test
    fun parsesConfirmationPhaseCounters() {
        val json = JSONObject(payload).put("call_phase", "confirmation")
        json.getJSONObject("queue").put("exhausted", 3).put("to_confirm", 6)
        val board = parseCallBoard(json)
        assertEquals(PHASE_CONFIRMATION, board.callPhase)
        assertEquals(3, board.queue.getValue("exhausted"))
        assertEquals(6, board.queue.getValue("to_confirm"))
    }

    @Test
    fun elapsedTimeIsHumanReadableAndNeverNegative() {
        val start = Instant.parse("2025-05-01T10:00:00Z")
        assertEquals("45 s", elapsedLabel(start, start.plusSeconds(45)))
        assertEquals("2 min 5 s", elapsedLabel(start, start.plusSeconds(125)))
        assertEquals("0 s", elapsedLabel(start, start.minusSeconds(3)))
    }

    private fun read(text: String, topic: String = "calls", cursor: Long = 0) =
        readServerSentEvents(BufferedReader(StringReader(text)), topic, cursor)

    @Test
    fun serverSentEventsStopAtTheAwaitedTopic() {
        val stream = ": keep-alive\n\nid: 7\nevent: attendance\ndata: {}\n\nid: 9\nevent: calls\ndata: {\"event\":\"assigned\"}\n\nid: 11\nevent: calls\ndata: {}\n\n"
        assertEquals(StreamResult(9, true), read(stream))
    }

    @Test
    fun streamEndWithoutTopicKeepsTheNewestCursor() {
        assertEquals(StreamResult(7, false), read(": keep-alive\n\nid: 7\nevent: attendance\ndata: {}\n\n: keep-alive\n\n", cursor = 3))
        assertEquals(StreamResult(3, false), read("", cursor = 3))
        assertEquals(StreamResult(3, false), read("id: 8\nevent: calls\ndata: {}", cursor = 3))
    }
}
