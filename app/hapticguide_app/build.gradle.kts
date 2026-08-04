// Top-level build file.
// AGP 9.0 introduces built-in Kotlin support, so the org.jetbrains.kotlin.android
// plugin no longer needs to be declared here. KGP 2.2.10 is bundled by AGP 9.0.
// The Compose compiler plugin is still declared explicitly so the version is
// pinned and matches the Kotlin version AGP bundles.
plugins {
    id("com.android.application") version "9.0.1" apply false
    id("org.jetbrains.kotlin.plugin.compose") version "2.2.10" apply false
}
