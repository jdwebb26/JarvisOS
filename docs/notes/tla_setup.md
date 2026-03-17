# TLA+ Setup For This Repo

This repo keeps TLA+ specs under [specs/tla](/home/rollan/.openclaw/workspace/jarvis-v5/specs/tla). They are offline control-plane checks, not part of the live Jarvis runtime hot path.

## What You Need

1. Java
2. `tla2tools.jar`

The repo-local default location for the TLC jar is:

```bash
tools/tla/tla2tools.jar
```

The checker script is:

```bash
scripts/tla_check.sh
```

## Install Java On Ubuntu

For a current OpenJDK runtime:

```bash
sudo apt update
sudo apt install -y openjdk-21-jre-headless
```

If you want the full JDK instead:

```bash
sudo apt update
sudo apt install -y openjdk-21-jdk-headless
```

Verify:

```bash
java -version
```

## Place `tla2tools.jar` In The Repo

Create the tool folder if needed:

```bash
mkdir -p tools/tla
```

Download `tla2tools.jar` from the official TLA+ tools page:

- <https://lamport.azurewebsites.net/tla/tools.html>

Then place it here:

```bash
cp /path/to/downloaded/tla2tools.jar tools/tla/tla2tools.jar
```

This repo does not auto-download binaries in setup scripts.

## Run All Specs

From repo root:

```bash
bash scripts/tla_check.sh
```

The script:

- fails clearly if `java` is missing
- fails clearly if `tools/tla/tla2tools.jar` is missing
- runs the three model checks in order
- stops on the first failure
- prints the spec currently running

## Override The Jar Location

If you keep the jar elsewhere:

```bash
TLA_TOOLS_JAR=/absolute/path/to/tla2tools.jar bash scripts/tla_check.sh
```

## Run A Single Spec Manually

```bash
java -cp tools/tla/tla2tools.jar tlc2.TLC -deadlock -workers auto -config specs/tla/TaskLifecycle.cfg specs/tla/TaskLifecycle.tla
java -cp tools/tla/tla2tools.jar tlc2.TLC -deadlock -workers auto -config specs/tla/ApprovalGate.cfg specs/tla/ApprovalGate.tla
java -cp tools/tla/tla2tools.jar tlc2.TLC -deadlock -workers auto -config specs/tla/SchedulerLease.cfg specs/tla/SchedulerLease.tla
```

## Current Machine Status

During this bootstrap pass:

- `java` was not present on `PATH`
- `tlc` was not present on `PATH`
- `tools/tla/tla2tools.jar` was not present

So the checker path is now bootstrapped, but TLC has not yet run on this machine.
