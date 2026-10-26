package org.edumeeting.llamadas

import java.util.concurrent.TimeUnit
import okhttp3.OkHttpClient
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import okhttp3.tls.HandshakeCertificates
import okhttp3.tls.HeldCertificate
import org.json.JSONObject
import org.junit.After
import org.junit.Assert.*
import org.junit.Before
import org.junit.Test

class DjangoSessionApiTest {
    private lateinit var server: MockWebServer
    private lateinit var api: DjangoSessionApi

    @Before
    fun setUp() {
        val certificate = HeldCertificate.Builder().addSubjectAlternativeName("localhost").build()
        val serverCertificates = HandshakeCertificates.Builder().heldCertificate(certificate).build()
        val clientCertificates = HandshakeCertificates.Builder().addTrustedCertificate(certificate.certificate).build()
        server = MockWebServer()
        server.useHttps(serverCertificates.sslSocketFactory(), false)
        server.start()
        api = DjangoSessionApi(
            server.url("/").toString(),
            OkHttpClient.Builder().sslSocketFactory(clientCertificates.sslSocketFactory(), clientCertificates.trustManager),
        )
    }

    @After
    fun tearDown() {
        server.shutdown()
    }

    private fun login() {
        server.enqueue(MockResponse()
            .setBody("""<input name="csrfmiddlewaretoken" value="form-token">""")
            .addHeader("Set-Cookie", "csrftoken=before-login; Path=/; Secure"))
        server.enqueue(MockResponse().setResponseCode(302)
            .addHeader("Location", "/")
            .addHeader("Set-Cookie", "sessionid=session-value; Path=/; Secure; HttpOnly")
            .addHeader("Set-Cookie", "csrftoken=rotated-token; Path=/; Secure"))
        api.login("User.Mixed", "Mixed Password&+")
    }

    @Test
    fun loginAndQueriesPreserveCookiesCsrfMeetingAndJson() {
        login()
        assertEquals("GET", server.takeRequest().method)
        val loginRequest = server.takeRequest()
        assertEquals("POST", loginRequest.method)
        assertEquals("form-token", loginRequest.getHeader("X-CSRFToken"))
        assertTrue(loginRequest.body.readUtf8().contains("password=Mixed%20Password%26%2B"))
        assertTrue(loginRequest.getHeader("Cookie")!!.contains("csrftoken=before-login"))
        assertEquals(server.url("/accounts/login/").toString(), loginRequest.getHeader("Referer"))

        api.meetingId = "meeting-123"
        server.enqueue(MockResponse().setBody("""{"ok":true}"""))
        assertTrue(api.post("/api/v1/meetings/members/", JSONObject().put("registrars", org.json.JSONArray(listOf(2)))).getBoolean("ok"))
        val post = server.takeRequest()
        assertEquals("rotated-token", post.getHeader("X-CSRFToken"))
        assertEquals("meeting-123", post.getHeader("X-EduMeeting-Meeting"))
        assertTrue(post.getHeader("Cookie")!!.contains("sessionid=session-value"))
        assertTrue(post.getHeader("Content-Type")!!.startsWith("application/json"))
        assertEquals(2, JSONObject(post.body.readUtf8()).getJSONArray("registrars").getInt(0))

        server.enqueue(MockResponse().setBody("""{"results":[]}"""))
        api.get("/api/v1/participants/search/?q=Ana%20Luna&page=2")
        val get = server.takeRequest()
        assertEquals("/api/v1/participants/search/?q=Ana%20Luna&page=2", get.path)
        assertEquals("application/json", get.getHeader("Accept"))
    }

    @Test
    fun logoutClearsSessionAndMeeting() {
        login()
        server.takeRequest()
        server.takeRequest()
        api.meetingId = "meeting-123"
        server.enqueue(MockResponse().setBody("""{"ok":true}"""))
        api.logout()
        server.takeRequest()
        assertNull(api.meetingId)
        server.enqueue(MockResponse().setBody("{}"))
        api.get("/api/v1/session/")
        assertNull(server.takeRequest().getHeader("Cookie"))
        assertThrows(IllegalStateException::class.java) { api.post("/api/v1/calls/next/", JSONObject()) }
    }

    @Test
    fun errorsAreExplicitAndRedirectsAreNotFollowed() {
        server.enqueue(MockResponse().setResponseCode(403).setBody("""{"error":"Sin permiso"}"""))
        assertEquals("Sin permiso", assertThrows(IllegalStateException::class.java) { api.get("/api/v1/session/") }.message)
        server.takeRequest()
        server.enqueue(MockResponse().setResponseCode(500).setBody("<html>Error</html>"))
        assertTrue(assertThrows(IllegalStateException::class.java) { api.get("/api/v1/session/") }.message!!.contains("500"))
        server.takeRequest()
        server.enqueue(MockResponse().setResponseCode(302).addHeader("Location", "/accounts/login/"))
        assertTrue(assertThrows(IllegalStateException::class.java) { api.get("/api/v1/session/") }.message!!.contains("sesión venció"))
        server.takeRequest()
        assertNull(server.takeRequest(100, TimeUnit.MILLISECONDS))
        server.enqueue(MockResponse().setBody("<html>Not JSON</html>"))
        assertTrue(assertThrows(IllegalStateException::class.java) { api.get("/api/v1/session/") }.message!!.contains("JSON inválida"))
    }

    @Test
    fun rejectsInvalidCredentialsMissingCsrfAndInsecureUrls() {
        server.enqueue(MockResponse().setBody("""<input name="csrfmiddlewaretoken" value="token">"""))
        server.enqueue(MockResponse().setBody("Invalid login"))
        assertTrue(assertThrows(IllegalStateException::class.java) { api.login("user", "wrong") }.message!!.contains("Credenciales"))
        server.enqueue(MockResponse().setBody("<html>No token</html>"))
        assertTrue(assertThrows(IllegalStateException::class.java) { api.login("user", "wrong") }.message!!.contains("token CSRF"))
        assertThrows(IllegalArgumentException::class.java) { DjangoSessionApi("http://localhost") }
        assertThrows(IllegalArgumentException::class.java) { api.get("//other-server/path") }
    }
}
