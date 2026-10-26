package org.edumeeting.llamadas

import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class SuperuserWorkspaceTest {
    @Test
    fun parsesAccountDirectory() {
        val directory = parseAccountDirectory(JSONObject("""
            {"users": [{"id": 3, "username": "ANA", "first_name": "Ana", "last_name": "Ruiz", "full_name": "Ana Ruiz",
              "is_active": false, "initials": "AR", "last_login": null,
              "groups": [{"id": 2, "name": "OPERADOR", "label": "Operador de llamadas"}]}],
             "groups": [{"id": 1, "name": "ADMINISTRADOR", "label": "Administrador de reuniones"},
                        {"id": 2, "name": "OPERADOR", "label": "Operador de llamadas"}]}
        """))
        val account = directory.accounts.single()
        assertEquals("ANA", account.username)
        assertFalse(account.isActive)
        assertEquals("AR", account.initials)
        assertEquals(listOf(AccountGroup(2, "OPERADOR", "Operador de llamadas")), account.groups)
        assertEquals(listOf("ADMINISTRADOR", "OPERADOR"), directory.groups.map { it.name })
    }

    @Test
    fun payloadOmitsEmptyPasswordsAndNormalizesFields() {
        val payload = accountPayload(" LUIS ", " Luis ", "Pérez", setOf(3, 1), "lp", true, "", "")
        assertEquals("LUIS", payload.getString("username"))
        assertEquals("Luis", payload.getString("first_name"))
        assertEquals("LP", payload.getString("initials"))
        assertEquals("[1,3]", payload.getJSONArray("groups").toString())
        assertTrue(payload.getBoolean("is_active"))
        assertFalse(payload.has("password1"))
        assertFalse(payload.has("password2"))
    }

    @Test
    fun payloadSendsPasswordsWhenTyped() {
        val payload = accountPayload("ANA", "", "", emptySet(), "", false, "secreto-1", "secreto-2")
        assertEquals("secreto-1", payload.getString("password1"))
        assertEquals("secreto-2", payload.getString("password2"))
        assertFalse(payload.getBoolean("is_active"))
    }
}
