package com.karthi.adaptivelink

import android.content.Context
import android.content.pm.PackageManager
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import java.math.BigInteger
import java.security.KeyPairGenerator
import java.security.KeyStore
import java.security.PrivateKey
import java.security.cert.X509Certificate
import java.util.Date
import javax.security.auth.x500.X500Principal

/**
 * This phone's identity: one key pair in the Android Keystore.
 *
 * The private key is generated inside the phone's secure hardware (StrongBox
 * where the phone has one, the TEE otherwise) and can never be read out of
 * it - not by this app, not from a backup, not by copying the app's data to
 * another phone. The computer trusts the certificate of this key and nothing
 * else, so the link works from this phone only.
 *
 * The key does not ask for a fingerprint on every use: TLS signs with it in
 * the background. The app itself is what asks for the fingerprint or screen
 * lock, when it is opened (MainActivity).
 */
object LinkIdentity {
    private const val ALIAS = "adaptive-link-phone"
    private const val STORE = "AndroidKeyStore"

    private fun store(): KeyStore = KeyStore.getInstance(STORE).apply { load(null) }

    fun exists(): Boolean = store().containsAlias(ALIAS)

    /** The certificate, creating the key first if this phone has none yet. */
    fun certificate(context: Context): X509Certificate {
        if (!exists()) create(context)
        return store().getCertificate(ALIAS) as X509Certificate
    }

    fun privateKey(): PrivateKey = store().getKey(ALIAS, null) as PrivateKey

    fun fingerprint(context: Context): String = Protocol.fingerprint(certificate(context).encoded)

    /** Forget this phone's identity. The computer will no longer know it. */
    fun delete() {
        if (exists()) store().deleteEntry(ALIAS)
    }

    private fun spec(strongBox: Boolean): KeyGenParameterSpec {
        val now = System.currentTimeMillis()
        return KeyGenParameterSpec.Builder(ALIAS, KeyProperties.PURPOSE_SIGN)
            .setAlgorithmParameterSpec(java.security.spec.ECGenParameterSpec("secp256r1"))
            // TLS hands the key an already-hashed value to sign, hence NONE.
            .setDigests(
                KeyProperties.DIGEST_NONE, KeyProperties.DIGEST_SHA256,
                KeyProperties.DIGEST_SHA384, KeyProperties.DIGEST_SHA512,
            )
            .setCertificateSubject(X500Principal("CN=Adaptive Link Phone"))
            .setCertificateSerialNumber(BigInteger.valueOf(now))
            .setCertificateNotBefore(Date(now - 24L * 3600 * 1000))
            .setCertificateNotAfter(Date(now + 3650L * 24 * 3600 * 1000))
            .setIsStrongBoxBacked(strongBox)
            .build()
    }

    private fun create(context: Context) {
        val generator = KeyPairGenerator.getInstance(KeyProperties.KEY_ALGORITHM_EC, STORE)
        val hasStrongBox = context.packageManager.hasSystemFeature(PackageManager.FEATURE_STRONGBOX_KEYSTORE)
        if (hasStrongBox) {
            // StrongBox chips differ in what they accept, and a phone that
            // refuses these parameters does not always say so with
            // StrongBoxUnavailableException. Whatever it throws, the phone's
            // ordinary secure hardware (the TEE) is still hardware-backed
            // and non-exportable, so fall back to it rather than fail.
            try {
                generator.initialize(spec(true))
                generator.generateKeyPair()
                return
            } catch (e: Exception) {
                runCatching { store().deleteEntry(ALIAS) }
            }
        }
        generator.initialize(spec(false))
        generator.generateKeyPair()
    }
}
