import java.util.Properties

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("org.jetbrains.kotlin.plugin.compose")
}

// The owner's Google project (docs/ADAPTIVE_LINK.md). The three values are
// identifiers, not secrets, but they are the owner's, so they come from a
// file that is not tracked: cloud.properties, beside this build.
//   api_key=...   database_url=https://...   web_client_id=...apps.googleusercontent.com
// Without the file the app is built with account sign-in switched off and
// pairs by code only.
val cloud = Properties().apply {
    val file = rootProject.file("cloud.properties")
    if (file.exists()) file.inputStream().use { load(it) }
}
fun cloudValue(name: String): String = "\"" + (cloud.getProperty(name) ?: "").trim().replace("\"", "") + "\""

android {
    namespace = "com.karthi.adaptivelink"
    compileSdk = 35

    defaultConfig {
        applicationId = "com.karthi.adaptivelink"
        // Android 10: TLS 1.3, StrongBox, and MediaStore downloads without
        // storage permission.
        minSdk = 29
        targetSdk = 35
        versionCode = 1
        versionName = "1.0"
        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
        // The direct connection is native code, about 12 MB per kind of
        // processor. Phones are arm64; the test emulator is x86_64 and asks
        // for that as well (-Pabi=arm64-v8a,x86_64).
        ndk {
            abiFilters += ((project.findProperty("abi") as String?) ?: "arm64-v8a").split(",")
        }
        buildConfigField("String", "CLOUD_API_KEY", cloudValue("api_key"))
        buildConfigField("String", "CLOUD_DATABASE_URL", cloudValue("database_url"))
        buildConfigField("String", "CLOUD_WEB_CLIENT_ID", cloudValue("web_client_id"))
    }

    buildTypes {
        // The build that is installed. Unused library code is removed (see
        // proguard-rules.pro), which takes the app from about 60 MB to a few;
        // the on-device test runs against this same shrunk build.
        debug {
            isMinifyEnabled = true
            proguardFiles(getDefaultProguardFile("proguard-android-optimize.txt"), "proguard-rules.pro")
            testProguardFiles("proguard-test-rules.pro")
        }
        release {
            isMinifyEnabled = true
            proguardFiles(getDefaultProguardFile("proguard-android-optimize.txt"), "proguard-rules.pro")
        }
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions {
        jvmTarget = "17"
    }
    packaging {
        // Stored compressed: the direct connection's native library is 12 MB
        // as it is and under 5 MB packed, and the app is sent to the phone.
        jniLibs.useLegacyPackaging = true
    }
    buildFeatures {
        compose = true
        buildConfig = true
    }
    testOptions {
        unitTests.isReturnDefaultValues = true
    }
}

dependencies {
    implementation(platform("androidx.compose:compose-bom:2025.05.00"))
    implementation("androidx.compose.ui:ui")
    implementation("androidx.compose.material3:material3")
    implementation("androidx.compose.material:material-icons-extended")
    implementation("androidx.activity:activity-compose:1.10.1")
    implementation("androidx.core:core-ktx:1.16.0")
    implementation("androidx.lifecycle:lifecycle-runtime-ktx:2.9.4")
    implementation("androidx.biometric:biometric:1.1.0")
    // biometric 1.1.0 asks only for fragment 1.2.5, whose FragmentActivity
    // rejects the request codes the current activity-result API uses: every
    // launcher (the QR scanner, the file picker, the camera permission)
    // crashed with "Can only use lower 16 bits for requestCode". A current
    // fragment library is asked for by name.
    implementation("androidx.fragment:fragment:1.8.9")
    implementation("androidx.camera:camera-core:1.4.2")
    implementation("androidx.camera:camera-camera2:1.4.2")
    implementation("androidx.camera:camera-lifecycle:1.4.2")
    implementation("androidx.camera:camera-view:1.4.2")
    implementation("com.squareup.okhttp3:okhttp:4.12.0")
    implementation("com.journeyapps:zxing-android-embedded:4.3.0")
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.10.2")
    // Sign in with Google, through Android's own account picker.
    implementation("androidx.credentials:credentials:1.5.0")
    implementation("androidx.credentials:credentials-play-services-auth:1.5.0")
    implementation("com.google.android.libraries.identity.googleid:googleid:1.1.1")
    // The direct, peer-to-peer connection used away from the computer's network.
    implementation("io.getstream:stream-webrtc-android:1.3.8")

    testImplementation("junit:junit:4.13.2")
    testImplementation("org.json:json:20240303")

    androidTestImplementation("androidx.test.ext:junit:1.2.1")
    androidTestImplementation("androidx.test:runner:1.6.2")
}
