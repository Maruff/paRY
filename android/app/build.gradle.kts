plugins {
    alias(libs.plugins.android.application)
    alias(libs.plugins.kotlin.android)
}

android {
    // The namespace is `org.etamil.pary` and not the reversed domain
    // `in.etamil.pary`, because `in` is a hard keyword in Kotlin and a package
    // declaration cannot use one without backticks. The applicationId keeps the
    // real domain: it is an identifier string, not a package.
    namespace = "org.etamil.pary"
    compileSdk = 35

    defaultConfig {
        applicationId = "in.etamil.pary"
        minSdk = 24
        targetSdk = 35
        versionCode = 1
        versionName = "0.1.0"
    }

    buildTypes {
        release {
            isMinifyEnabled = true
            isShrinkResources = true
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
}

dependencies {
    implementation(libs.androidx.core.ktx)
    implementation(libs.androidx.appcompat)
    implementation(libs.androidx.activity)
}
