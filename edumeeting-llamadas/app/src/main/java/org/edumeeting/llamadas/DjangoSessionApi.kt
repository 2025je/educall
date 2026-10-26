package org.edumeeting.llamadas

import java.net.CookieManager
import java.net.CookiePolicy
import java.util.concurrent.TimeUnit
import okhttp3.HttpUrl.Companion.toHttpUrlOrNull
import okhttp3.JavaNetCookieJar
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.MultipartBody
import okhttp3.OkHttpClient
import okhttp3.RequestBody
import okhttp3.RequestBody.Companion.toRequestBody
import okhttp3.ResponseBody
import org.json.JSONException
import org.json.JSONObject
import retrofit2.Call
import retrofit2.Retrofit
import retrofit2.http.Body
import retrofit2.http.FieldMap
import retrofit2.http.FormUrlEncoded
import retrofit2.http.GET
import retrofit2.http.HeaderMap
import retrofit2.http.POST
import retrofit2.http.Url

internal interface DjangoSessionService {
    @GET
    fun get(@Url url: String, @HeaderMap headers: Map<String, String>): Call<ResponseBody>

    @POST
    fun post(
        @Url url: String,
        @HeaderMap headers: Map<String, String>,
        @Body body: RequestBody,
    ): Call<ResponseBody>

    @FormUrlEncoded
    @POST
    fun login(
        @Url url: String,
        @HeaderMap headers: Map<String, String>,
        @FieldMap fields: Map<String, String>,
    ): Call<ResponseBody>
}

class DjangoSessionApi internal constructor(baseUrl: String, clientBuilder: OkHttpClient.Builder) {
    constructor(baseUrl: String) : this(baseUrl, OkHttpClient.Builder())

    var meetingId: String? = null
    private val baseUrl = baseUrl.trimEnd('/').toHttpUrlOrNull()
        ?: throw IllegalArgumentException("Escribe una URL válida, por ejemplo https://servidor.edumeeting.org")
    private val cookieManager = CookieManager(null, CookiePolicy.ACCEPT_ORIGINAL_SERVER)
    private val cookieJar = JavaNetCookieJar(cookieManager)
    private val service: DjangoSessionService

    init {
        require(this.baseUrl.isHttps) {
            "Por seguridad, EduMeeting Llamadas solo permite conectarse al servidor por HTTPS."
        }
        val client = clientBuilder
            .cookieJar(cookieJar)
            .followRedirects(false)
            .followSslRedirects(false)
            .connectTimeout(15, TimeUnit.SECONDS)
            .readTimeout(20, TimeUnit.SECONDS)
            .build()
        service = Retrofit.Builder()
            .baseUrl("${this.baseUrl.toString().trimEnd('/')}/")
            .client(client)
            .build()
            .create(DjangoSessionService::class.java)
    }

    private fun url(path: String): String {
        require(path.startsWith("/") && !path.startsWith("//")) { "La ruta de la API no es válida." }
        return "${baseUrl.toString().trimEnd('/')}$path"
    }

    private fun headers(): MutableMap<String, String> = mutableMapOf<String, String>().apply {
        meetingId?.let { put("X-EduMeeting-Meeting", it) }
    }

    fun login(username: String, password: String) {
        val loginUrl = url("/accounts/login/")
        val pageResponse = service.get(loginUrl, headers()).execute()
        val page = (pageResponse.body() ?: pageResponse.errorBody())?.use { it.string() }.orEmpty()
        check(pageResponse.isSuccessful) {
            "No se pudo abrir el inicio de sesión (HTTP ${pageResponse.code()})."
        }
        val token = Regex("""name=["']csrfmiddlewaretoken["']\s+value=["']([^"']+)["']""")
            .find(page)?.groupValues?.get(1)
            ?: throw IllegalStateException("El servidor no entregó el token CSRF del inicio de sesión.")
        val response = service.login(
            loginUrl,
            headers().apply {
                put("Referer", loginUrl)
                put("X-CSRFToken", token)
            },
            mapOf("csrfmiddlewaretoken" to token, "username" to username, "password" to password),
        ).execute()
        (response.body() ?: response.errorBody())?.close()
        check(response.code() in 300..399) {
            if (response.code() == 200) "Credenciales incorrectas o cuenta no autorizada."
            else "Falló el inicio de sesión (HTTP ${response.code()})."
        }
    }

    fun get(path: String): JSONObject = request(path, null)

    fun post(path: String, body: JSONObject): JSONObject =
        request(path, body.toString().toRequestBody("application/json; charset=utf-8".toMediaType()))

    fun upload(path: String, fileName: String, contents: ByteArray): JSONObject = request(
        path,
        MultipartBody.Builder().setType(MultipartBody.FORM)
            .addFormDataPart("file", fileName, contents.toRequestBody("application/zip".toMediaType()))
            .build(),
    )

    fun download(path: String): ByteArray {
        val response = service.get(url(path), headers()).execute()
        if (!response.isSuccessful) {
            val text = response.errorBody()?.use { it.string() }.orEmpty()
            throw IllegalStateException(errorMessage(response.code(), text))
        }
        return response.body()?.use { it.bytes() } ?: throw IllegalStateException("El servidor no envió el archivo.")
    }

    fun logout() {
        post("/api/v1/mobile/logout/", JSONObject())
        cookieManager.cookieStore.removeAll()
        meetingId = null
    }

    private fun request(path: String, body: RequestBody?): JSONObject {
        val requestUrl = url(path)
        val headers = headers().apply { put("Accept", "application/json") }
        val call = if (body == null) {
            service.get(requestUrl, headers)
        } else {
            val csrfToken = cookieJar.loadForRequest(baseUrl)
                .firstOrNull { it.name == "csrftoken" }?.value
                ?: throw IllegalStateException("No hay un token CSRF vigente. Inicia sesión de nuevo.")
            headers["X-CSRFToken"] = csrfToken
            headers["Referer"] = "${baseUrl.toString().trimEnd('/')}/"
            service.post(requestUrl, headers, body)
        }
        val response = call.execute()
        val text = (response.body() ?: response.errorBody())?.use { it.string() }.orEmpty()
        if (!response.isSuccessful) throw IllegalStateException(errorMessage(response.code(), text))
        return try {
            JSONObject(text)
        } catch (error: JSONException) {
            throw IllegalStateException("El servidor devolvió una respuesta JSON inválida.", error)
        }
    }

    private fun errorMessage(code: Int, text: String): String {
        val detail = try {
            JSONObject(text).optString("error")
        } catch (_: JSONException) {
            ""
        }
        return when (code) {
            302, 401 -> "La sesión venció. Inicia sesión de nuevo."
            else -> detail.ifBlank { "Error del servidor (HTTP $code)." }
        }
    }
}
