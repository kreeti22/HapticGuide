### 🛠️ AI App Architect Prompt: HapticGuide Build Stability

> **Context:** You are working on a modern Android project using **AGP 9.0+** and **Gradle 9.1+**. The development environment uses **Java 25** (IDE) and **Java 17** (Build).
>
> **Mandatory Guardrails:**
>
> 1. **AGP 9.0 Compatibility**:
>    * AGP 9.0 uses "Built-in Kotlin." Never re-add `id("org.jetbrains.kotlin.android")` to build files unless opting out.
>    * Avoid using the deprecated `kotlinOptions { jvmTarget = "..." }` block. AGP 9.0 automatically aligns the Kotlin target with `compileOptions.targetCompatibility`.
>    * If explicit compiler configuration is needed, use the new `kotlin { compilerOptions { ... } }` DSL.
>
> 2. **Version Synchronization**:
>    * **Gradle Version**: Must stay at **9.1.0 or higher** to support the AGP 9.0 API and Java 25 compatibility.
>    * **JDK Version**: Always ensure `compileOptions` and `jvmTarget` are explicitly set to **Java 11 or 17** for the application source code to maintain compatibility with the target SDK.
>
> 3. **Hermetic Configuration**:
>    * Never hardcode machine-specific paths (e.g., `C:\Users\...`) in `gradle.properties` or `local.properties`. 
>    * Rely on the IDE's `#JAVA_HOME` or `#GRADLE_LOCAL_JAVA_HOME` macros in `.idea/gradle.xml` to keep the project portable.
>
> 4. **Pre-Change Verification**:
>    * Before updating any dependency in `build.gradle.kts` (especially AGP, Compose, or Kotlin), check the official Android [Gradle Version Compatibility Matrix](https://developer.android.com/build/releases/gradle-plugin#updating-gradle).
>    * Immediately run `gradle_sync` after any build script modification to catch "Incompatible JVM" errors before proceeding with feature development.
