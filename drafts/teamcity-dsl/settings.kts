import jetbrains.buildServer.configs.kotlin.v2018_1.*
import jetbrains.buildServer.configs.kotlin.v2018_1.buildSteps.script
import jetbrains.buildServer.configs.kotlin.v2018_1.triggers.finishBuildTrigger
import jetbrains.buildServer.configs.kotlin.v2018_1.vcs.GitVcsRoot

/*
 * TeamCity Kotlin DSL - TDC integration tests project (IN-662).
 * Target server: TeamCity Enterprise 2018.1.3  =>  API "2018.1", Kotlin 1.2.
 *
 * One template = one slot build. Per component under test the factory
 * integrationTests() stamps out slot configs (lin-x64 / lin-arm / lin-arm64)
 * wired to that component's EXISTING build configuration (snapshot + artifact
 * dependency + finish-build trigger). All test logic lives in the tdc-runner
 * repo (python core + ci/run_tests.sh); the DSL only wires configs, params
 * and the three build steps: secrets -> run -> cleanup(always).
 *
 * CAUTION (inherited from the CONAN sandbox):
 *  - Kotlin block comments NEST: never put slash-star sequences (e.g. a path
 *    glob like "reports" + two stars) inside a comment.
 *  - Secrets NEVER go through the synced DSL. Password parameters
 *    tdc.secret.<name> are defined BY HAND on the parent project; the DSL
 *    only references them as percent-params. credentialsJSON placeholders in
 *    DSL break "Apply" (could not decrypt) - do not add them.
 *  - This file must reach the settings repo byte-exact via git. ASCII only.
 *
 * Prerequisites (manual, once):
 *  - internal mirror of tdc-runner in Bitbucket (agents cannot reach GitHub);
 *    its clone URL goes to tdc.runner.repo.url below (project key = lead call);
 *  - uploaded SSH key (name in tdc.runner.repo.key) with read access to it;
 *  - agents: docker + Compose v2, buildAgent.properties carries
 *    system.agent.cpu.arch (x86_64 / arm / aarch64), daemon.json carries
 *    bip + default-address-pools (office subnet clash).
 */

version = "2018.1"

// ---------------------------------------------------------------------------
// Slot dictionary: os-arch pairs and the agent cpu arch they require
// ---------------------------------------------------------------------------
data class TdcSlot(
    val idSuffix: String,    // build-config id tail (stable, never rename)
    val os: String,          // lin (win = phase 2)
    val arch: String,        // x64 | arm | arm64  (the .nupkg slot axis)
    val agentArch: String    // system.agent.cpu.arch value on the agent
)

val TDC_SLOTS = listOf(
    TdcSlot("lin_x64",   "lin", "x64",   "x86_64"),
    TdcSlot("lin_arm",   "lin", "arm",   "arm"),
    TdcSlot("lin_arm64", "lin", "arm64", "aarch64")
)

// ---------------------------------------------------------------------------
// VCS: component repo comes through the EXISTING shared parametrized root
// AbsoluteId("Bitbucket") (url scm/%repoProject%/%repoName%.git) - same
// mechanism as the CONAN sandbox, no new auth. The tdc-runner tool repo is a
// second, fixed root checked out into the tdc-runner/ subdir.
// ---------------------------------------------------------------------------
object TdcRunnerVcs : GitVcsRoot({
    id("TdcRunnerRepo")
    name = "tdc-runner (integration test runner)"
    url = "%tdc.runner.repo.url%"
    branch = "refs/heads/master"
    authMethod = uploadedKey {
        userName = "git"
        uploadedKey = "%tdc.runner.repo.key%"
    }
})

// ---------------------------------------------------------------------------
// The slot template: 3 steps, 2 vcs roots, arch-pinned agent requirement
// ---------------------------------------------------------------------------
object TdcSlotTests : Template({
    id("TdcSlotTests")
    name = "TDC INTEGRATION TESTS (slot)"
    description = "Runs test_docker_config configurations of one slot via tdc-runner; steps: secrets -> run -> cleanup(always)"

    vcs {
        root(AbsoluteId("Bitbucket"))
        root(TdcRunnerVcs, "+:. => tdc-runner")
    }

    params {
        param("tdc.slot.os", "lin")
        param("tdc.slot.arch", "x64")
        param("tdc.agent.arch", "x86_64")
        // secrets step body; the factory generates the real one per component.
        // Default is a no-op so secret-less components need nothing at all.
        param("tdc.secrets.script", "#!/bin/bash\necho no secrets required")
        // env interface of the universal launcher (fail-closed on the CI side)
        param("env.TDC_SLOT", "%tdc.slot.os%-%tdc.slot.arch%")
        param("env.TDC_ARTIFACTS", ".tc-artifacts")
        param("env.TDC_OUT", ".tdc-out")
        param("env.TDC_BUILD_ID", "%teamcity.build.id%")
        param("env.TDC_REGISTRY_PREFIXES", "%tdc.registry.prefixes%")
        param("env.TDC_SECRETS", "%system.teamcity.build.tempDir%/tdc-secrets")
    }

    steps {
        script {
            name = "1 secrets"
            scriptContent = "%tdc.secrets.script%"
        }
        script {
            name = "2 run tests"
            scriptContent = """
                #!/bin/bash
                set -euo pipefail
                bash tdc-runner/ci/run_tests.sh
            """.trimIndent()
        }
        script {
            name = "3 cleanup"
            // "Always, even if build stop command was issued": containers are
            // children of dockerd and survive a TC Stop; python finally does not.
            executionMode = BuildStep.ExecutionMode.ALWAYS
            scriptContent = """
                #!/bin/bash
                docker ps -aq --filter label=tc.in662 | xargs -r docker rm -f
                docker volume ls -q --filter label=tc.in662 | xargs -r docker volume rm -f
                rm -rf "%env.TDC_SECRETS%"
                exit 0
            """.trimIndent()
        }
    }

    artifactRules = ".tdc-out/reports/** => reports"

    requirements {
        equals("system.agent.type", "build-linux")
        equals("system.agent.cpu.arch", "%tdc.agent.arch%")
    }
})

// ---------------------------------------------------------------------------
// Factory: one component under test -> subproject with N slot configs
// ---------------------------------------------------------------------------
data class TdcComponent(
    val name: String,             // repo slug, e.g. "elara_openide_backend"
    val repoProject: String,      // Bitbucket project key, e.g. "SCADA"
    val repoName: String,         // repo slug for the shared Bitbucket root
    val buildConfigId: String,    // ext id of the EXISTING build configuration
                                  // producing this component's artifacts
    val slots: List<String> = listOf("lin-x64", "lin-arm", "lin-arm64"),
    val secrets: List<String> = listOf()   // names for tdc.secret.<name> params
)

/** Bash body for step "1 secrets": materialize password params as files. */
fun secretsScript(names: List<String>): String {
    val sb = StringBuilder()
    sb.append("#!/bin/bash\n")
    sb.append("set -euo pipefail\n")
    sb.append("umask 077\n")
    sb.append("mkdir -p \"${'$'}TDC_SECRETS\"\n")
    names.forEach { n ->
        // %%s survives TC substitution as a literal percent-s for printf;
        // the password param itself resolves at build time, not in the DSL.
        sb.append("printf '%%s' \"%tdc.secret.$n%\" > \"${'$'}TDC_SECRETS/$n\"\n")
    }
    sb.append("echo \"secrets: ${names.size} file(s) prepared\"\n")
    return sb.toString()
}

fun Project.integrationTests(c: TdcComponent) {
    val idBase = c.name.split("_", "-").joinToString("") { it.capitalize() }

    subProject {
        id("${idBase}_IT")
        name = c.name.toUpperCase() + " TESTS"

        TDC_SLOTS.filter { s -> c.slots.contains(s.os + "-" + s.arch) }.forEach { s ->
            buildType {
                id("${idBase}_IT_${s.idSuffix}")
                name = "IT ${s.os}-${s.arch}"
                templates(TdcSlotTests)
                params {
                    // drive the shared Bitbucket root at the component repo
                    param("repoProject", c.repoProject)
                    param("repoName", c.repoName)
                    param("tdc.slot.os", s.os)
                    param("tdc.slot.arch", s.arch)
                    param("tdc.agent.arch", s.agentArch)
                    if (c.secrets.isNotEmpty()) {
                        param("tdc.secrets.script", secretsScript(c.secrets))
                    }
                }
                dependencies {
                    dependency(AbsoluteId(c.buildConfigId)) {
                        snapshot {
                            onDependencyFailure = FailureAction.FAIL_TO_START
                            onDependencyCancel = FailureAction.CANCEL
                            reuseBuilds = ReuseBuilds.SUCCESSFUL
                        }
                        artifacts {
                            buildRule = sameChainOrLastFinished()
                            artifactRules = "+:** => .tc-artifacts"
                            cleanDestination = true
                        }
                    }
                }
                triggers {
                    finishBuildTrigger {
                        // v2018_1 API: buildTypeExtId (renamed in 2019.x);
                        // successfulOnly defaults to FALSE - set explicitly
                        buildTypeExtId = c.buildConfigId
                        successfulOnly = true
                    }
                }
            }
        }
    }
}

// ---------------------------------------------------------------------------
// Project root - global params + the component list (edit this daily)
// ---------------------------------------------------------------------------
project {
    description = "TDC integration tests (IN-662): test_docker_config runner via Kotlin DSL"

    template(TdcSlotTests)
    vcsRoot(TdcRunnerVcs)

    params {
        // internal mirror of tdc-runner; project key/location = lead decision
        param("tdc.runner.repo.url", "ssh://git@bitbucket.inc.elara.local/dev/tdc-runner.git")
        // name of the uploaded SSH key with read access to the mirror
        param("tdc.runner.repo.key", "teamcity")
        param("tdc.registry.prefixes", "proget.inc.elara.local/")
        // defaults for the shared Bitbucket root; every component overrides
        param("repoProject", "dev")
        param("repoName", "tdc-runner")
        // tdc.secret.<name> password params: define BY HAND on the parent
        // project (never here - see CAUTION above).
    }

    // ===== components under test =====
    // Pilot goes live after the OpenIde decisions (build images in the build
    // configuration instead of compose build:, docker.sock question):
    //
    // integrationTests(TdcComponent(
    //     name = "elara_openide_backend",
    //     repoProject = "SCADA",
    //     repoName = "elara_openide_backend",
    //     buildConfigId = "OpenIdeBackend_Build",         // real ext id here
    //     slots = listOf("lin-x64"),
    //     secrets = listOf("postgres_user", "postgres_password")
    // ))
}
