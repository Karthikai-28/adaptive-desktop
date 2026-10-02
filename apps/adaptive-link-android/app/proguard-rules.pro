# Shrink, do not rename. The size of the app is almost all unused library
# code (the extended icon set alone is tens of megabytes), and removing it is
# what this is for. Names are left alone so that a stack trace reads as the
# source does, and the app's own classes are kept whole because its on-device
# test calls them directly.
-dontobfuscate
-keep class com.karthi.adaptivelink.** { *; }

# OkHttp and Okio reference optional platform classes that are not on Android.
-dontwarn okhttp3.internal.platform.**
-dontwarn org.conscrypt.**
-dontwarn org.bouncycastle.**
-dontwarn org.openjsse.**

# The on-device test shares these with the app at run time (its own APK does
# not carry a second copy), so they are kept whole. They are small; the size
# was in the icon set and the unused parts of Compose and CameraX.
-keep class kotlin.** { *; }
-keep class kotlinx.coroutines.** { *; }
-keep class okhttp3.** { *; }
-keep class okio.** { *; }
