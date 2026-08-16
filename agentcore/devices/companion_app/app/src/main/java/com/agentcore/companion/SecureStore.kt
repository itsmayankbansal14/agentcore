package com.agentcore.companion

import android.content.Context
import androidx.security.crypto.EncryptedSharedPreferences
import androidx.security.crypto.MasterKey

/** Persists the device token + laptop URL in EncryptedSharedPreferences (Keystore-backed). */
object SecureStore {
    private const val FILE = "agentcore_secure"
    private const val KEY_TOKEN = "device_token"
    private const val KEY_URL = "laptop_url"
    private const val KEY_NAME = "device_name"

    private fun prefs(ctx: Context) = EncryptedSharedPreferences.create(
        ctx,
        FILE,
        MasterKey.Builder(ctx).setKeyScheme(MasterKey.KeyScheme.AES256_GCM).build(),
        EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
        EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM,
    )

    fun save(ctx: Context, token: String, url: String, name: String) {
        prefs(ctx).edit()
            .putString(KEY_TOKEN, token)
            .putString(KEY_URL, url)
            .putString(KEY_NAME, name)
            .apply()
    }

    fun token(ctx: Context): String = prefs(ctx).getString(KEY_TOKEN, "") ?: ""
    fun url(ctx: Context): String = prefs(ctx).getString(KEY_URL, "") ?: ""
    fun name(ctx: Context): String = prefs(ctx).getString(KEY_NAME, "My Phone") ?: "My Phone"
    fun clear(ctx: Context) { prefs(ctx).edit().clear().apply() }
}
