pluginManagement {
    repositories {
        google()
        mavenCentral()
        gradlePluginPortal()
    }
}
dependencyResolutionManagement {
    repositoriesMode.set(RepositoriesMode.FAIL_ON_PROJECT_REPOS)
    repositories {
        google()
        mavenCentral()
    }
}
rootProject.name = "EduMeeting Asistencia"
include(":app")
include(":edumeeting-ui")
project(":edumeeting-ui").projectDir = file("../edumeeting-ui")
