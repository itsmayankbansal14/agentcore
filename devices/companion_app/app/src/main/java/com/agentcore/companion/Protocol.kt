package com.agentcore.companion

import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json
import javax.crypto.Mac
import javax.crypto.spec.SecretKeySpec

/**
 * Wire protocol — MUST mirror devices/android.py on the laptop.
 *
 * Envelope JSON: {v, id, type, device, cmd, params, data, ts, auth:{token}, code}
 * Every command/ack/result/heartbeat is HMAC-SHA256 signed over "id|type|cmd|ts"
 * with the device token (replay-protected by the ts window on the laptop).
 */
object Protocol {

    const val VERSION = 1

    @Serializable
    data class Envelope(
        val v: Int = VERSION,
        val id: String = "",
        val type: String = "command",   // command|ack|result|event|heartbeat|hello|paired|pair_error|error
        val device: String = "",
        val cmd: String = "",
        val params: Map<String, String> = emptyMap(),
        val data: kotlinx.serialization.json.JsonElement? = null,
        val ts: Double = System.currentTimeMillis() / 1000.0,
        val code: String = "",
        val auth: Auth = Auth(),
    ) {
        @Serializable
        data class Auth(val token: String = "")
    }

    private val json = Json { ignoreUnknownKeys = true }

    fun encode(env: Envelope): String = json.encodeToString(Envelope.serializer(), env)
    fun decode(raw: String): Envelope = json.decodeFromString(Envelope.serializer(), raw)

    /** Sign (mutates a copy) — HMAC-SHA256("id|type|cmd|ts", token). */
    fun sign(env: Envelope, token: String): Envelope {
        val mac = Mac.getInstance("HmacSHA256")
        mac.init(SecretKeySpec(token.toByteArray(), "HmacSHA256"))
        val msg = "${env.id}|${env.type}|${env.cmd}|${env.ts}".toByteArray()
        val digest = mac.doFinal(msg).joinToString("") { "%02x".format(it) }
        return env.copy(auth = Envelope.Auth(token = digest))
    }

    fun heartbeat(seq: Int, token: String): Envelope =
        sign(Envelope(id = "hb_$seq", type = "heartbeat", cmd = ""), token)

    fun hello(deviceName: String, pairCode: String): Envelope =
        Envelope(id = "hello_${System.currentTimeMillis()}", type = "hello",
                 device = deviceName, code = pairCode)

    fun helloWithToken(deviceName: String, token: String): Envelope =
        sign(Envelope(id = "hello_${System.currentTimeMillis()}", type = "hello",
                      device = deviceName), token)

    fun ack(id: String, cmd: String, token: String): Envelope =
        sign(Envelope(id = id, type = "ack", cmd = cmd), token)

    fun result(id: String, cmd: String, ok: Boolean,
               data: Map<String, Any?>? = null, error: String? = null, token: String): Envelope {
        val payload = if (ok) mapOf("ok" to true, "data" to (data ?: emptyMap<String, Any?>()))
                      else mapOf("ok" to false, "error" to (error ?: "unknown error"))
        return sign(Envelope(id = id, type = "result", cmd = cmd,
                             data = json.parseToJsonElement(json.encodeToString(payload))), token)
    }
}
