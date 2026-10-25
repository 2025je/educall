package org.educall.dial

import android.net.Uri
import java.net.CookieManager
import java.net.CookiePolicy
import java.net.HttpURLConnection
import java.net.URL
import java.net.URLEncoder
import org.json.JSONObject

class DjangoSessionApi(baseUrl: String) {
    private val baseUrl = baseUrl.trimEnd('/')
    private val cookieManager: CookieManager
    private var csrfToken: String? = null

    init {
        val uri = Uri.parse(this.baseUrl)
        require(uri.host != null && uri.scheme in setOf("https", "http")) {
            "Escribe una URL válida, por ejemplo https://servidor.educall.org"
        }
        require(uri.scheme == "https") {
            "Por seguridad, EduCall Dial solo permite conectarse al servidor por HTTPS."
        }
        cookieManager = CookieManager(null, CookiePolicy.ACCEPT_ORIGINAL_SERVER)
        java.net.CookieHandler.setDefault(cookieManager)
    }

    fun login(username: String, password: String) {
        val page = connection("/accounts/login/").let { connection ->
            try {
                connection.requestMethod = "GET"
                val status = connection.responseCode
                if (status !in 200..299) throw IllegalStateException("No se pudo abrir el inicio de sesión (HTTP $status).")
                connection.inputStream.bufferedReader().use { it.readText() }
            } finally {
                connection.disconnect()
            }
        }
        val token = Regex("""name=["']csrfmiddlewaretoken["']\s+value=["']([^"']+)["']""")
            .find(page)?.groupValues?.get(1)
            ?: throw IllegalStateException("El servidor no entregó el token CSRF del inicio de sesión.")
        csrfToken = token
        val fields = listOf(
            "csrfmiddlewaretoken" to token,
            "username" to username,
            "password" to password,
        ).joinToString("&") { (key, value) ->
            "${encode(key)}=${encode(value)}"
        }
        val connection = connection("/accounts/login/")
        try {
            connection.requestMethod = "POST"
            connection.doOutput = true
            connection.instanceFollowRedirects = false
            connection.setRequestProperty("Content-Type", "application/x-www-form-urlencoded")
            connection.setRequestProperty("Referer", "$baseUrl/accounts/login/")
            connection.setRequestProperty("X-CSRFToken", token)
            connection.outputStream.use { it.write(fields.toByteArray(Charsets.UTF_8)) }
            val status = connection.responseCode
            if (status !in 300..399) {
                throw IllegalStateException(
                    if (status == 200) "Credenciales incorrectas o cuenta no autorizada."
                    else "Falló el inicio de sesión (HTTP $status)."
                )
            }
        } finally {
            connection.disconnect()
        }
    }

    fun get(path: String): JSONObject = request(path, "GET", null)

    fun post(path: String, body: JSONObject): JSONObject = request(path, "POST", body.toString())

    fun logout() {
        post("/api/v1/mobile/logout/", JSONObject())
        cookieManager.cookieStore.removeAll()
        csrfToken = null
    }

    private fun request(path: String, method: String, body: String?): JSONObject {
        val connection = connection(path)
        try {
            connection.requestMethod = method
            connection.instanceFollowRedirects = false
            connection.setRequestProperty("Accept", "application/json")
            csrfToken?.let { connection.setRequestProperty("X-CSRFToken", it) }
            if (body != null) {
                connection.doOutput = true
                connection.setRequestProperty("Content-Type", "application/json; charset=utf-8")
                connection.setRequestProperty("Referer", "$baseUrl/")
                connection.outputStream.use { it.write(body.toByteArray(Charsets.UTF_8)) }
            }
            val status = connection.responseCode
            val stream = if (status in 200..299) connection.inputStream else connection.errorStream
            val response = stream?.bufferedReader()?.use { it.readText() }.orEmpty()
            val json = try {
                JSONObject(response)
            } catch (_: Exception) {
                JSONObject()
            }
            if (status !in 200..299) {
                val message = when (status) {
                    302, 401 -> "La sesión venció. Inicia sesión de nuevo."
                    else -> json.optString("error").ifBlank { "Error del servidor (HTTP $status)." }
                }
                throw IllegalStateException(message)
            }
            return json
        } finally {
            connection.disconnect()
        }
    }

    private fun connection(path: String): HttpURLConnection {
        val connection = URL("$baseUrl$path").openConnection() as HttpURLConnection
        connection.connectTimeout = 15_000
        connection.readTimeout = 20_000
        return connection
    }

    private fun encode(value: String): String = URLEncoder.encode(value, Charsets.UTF_8.name())
}
