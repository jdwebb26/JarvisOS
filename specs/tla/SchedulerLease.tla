---- MODULE SchedulerLease ----
\* Small scheduler lease model for Jarvis/OpenClaw routing and worker ownership.
\* This is not a full scheduler spec; it protects ownership, expiry, once-only,
\* and bounded retry behavior.

EXTENDS Naturals, TLC

CONSTANTS JobA, JobB, Owner1, Owner2, NONE

JOBS == {JobA, JobB}
OWNERS == {Owner1, Owner2}
JobStates == {"queued", "leased", "running", "retry_wait", "succeeded", "failed", "expired"}
Outcomes == {"none", "success", "failure", "expired"}

VARIABLES
    jobState,
    leaseOwner,
    leaseActive,
    runCount,
    maxRetries,
    lastOutcome,
    onceOnly,
    successCount

vars == <<
    jobState,
    leaseOwner,
    leaseActive,
    runCount,
    maxRetries,
    lastOutcome,
    onceOnly,
    successCount
>>

Init ==
    /\ jobState = [j \in JOBS |-> "queued"]
    /\ leaseOwner = [j \in JOBS |-> NONE]
    /\ leaseActive = [j \in JOBS |-> FALSE]
    /\ runCount = [j \in JOBS |-> 0]
    /\ maxRetries = [j \in JOBS |->
        CASE j = JobA -> 2
           [] OTHER   -> 1]
    /\ lastOutcome = [j \in JOBS |-> "none"]
    /\ onceOnly = [j \in JOBS |->
        CASE j = JobA -> TRUE
           [] OTHER   -> FALSE]
    /\ successCount = [j \in JOBS |-> 0]

Claim(j, o) ==
    /\ j \in JOBS
    /\ o \in OWNERS
    /\ jobState[j] \in {"queued", "retry_wait", "expired"}
    /\ ~leaseActive[j]
    /\ ~(onceOnly[j] /\ successCount[j] >= 1)
    /\ runCount[j] < maxRetries[j]
    /\ jobState' = [jobState EXCEPT ![j] = "leased"]
    /\ leaseOwner' = [leaseOwner EXCEPT ![j] = o]
    /\ leaseActive' = [leaseActive EXCEPT ![j] = TRUE]
    /\ runCount' = [runCount EXCEPT ![j] = @ + 1]
    /\ UNCHANGED <<maxRetries, lastOutcome, onceOnly, successCount>>

StartRun(j) ==
    /\ jobState[j] = "leased"
    /\ leaseActive[j]
    /\ jobState' = [jobState EXCEPT ![j] = "running"]
    /\ UNCHANGED <<leaseOwner, leaseActive, runCount, maxRetries, lastOutcome, onceOnly, successCount>>

FinishSuccess(j) ==
    /\ jobState[j] = "running"
    /\ leaseActive[j]
    /\ jobState' = [jobState EXCEPT ![j] = "succeeded"]
    /\ leaseOwner' = [leaseOwner EXCEPT ![j] = NONE]
    /\ leaseActive' = [leaseActive EXCEPT ![j] = FALSE]
    /\ lastOutcome' = [lastOutcome EXCEPT ![j] = "success"]
    /\ successCount' = [successCount EXCEPT ![j] = @ + 1]
    /\ UNCHANGED <<runCount, maxRetries, onceOnly>>

FinishFailureRetry(j) ==
    /\ jobState[j] = "running"
    /\ leaseActive[j]
    /\ runCount[j] < maxRetries[j]
    /\ jobState' = [jobState EXCEPT ![j] = "retry_wait"]
    /\ leaseOwner' = [leaseOwner EXCEPT ![j] = NONE]
    /\ leaseActive' = [leaseActive EXCEPT ![j] = FALSE]
    /\ lastOutcome' = [lastOutcome EXCEPT ![j] = "failure"]
    /\ UNCHANGED <<runCount, maxRetries, onceOnly, successCount>>

FinishFailureTerminal(j) ==
    /\ jobState[j] = "running"
    /\ leaseActive[j]
    /\ runCount[j] >= maxRetries[j]
    /\ jobState' = [jobState EXCEPT ![j] = "failed"]
    /\ leaseOwner' = [leaseOwner EXCEPT ![j] = NONE]
    /\ leaseActive' = [leaseActive EXCEPT ![j] = FALSE]
    /\ lastOutcome' = [lastOutcome EXCEPT ![j] = "failure"]
    /\ UNCHANGED <<runCount, maxRetries, onceOnly, successCount>>

ExpireLease(j) ==
    /\ jobState[j] \in {"leased", "running"}
    /\ leaseActive[j]
    /\ jobState' = [jobState EXCEPT ![j] = "expired"]
    /\ leaseOwner' = [leaseOwner EXCEPT ![j] = NONE]
    /\ leaseActive' = [leaseActive EXCEPT ![j] = FALSE]
    /\ lastOutcome' = [lastOutcome EXCEPT ![j] = "expired"]
    /\ UNCHANGED <<runCount, maxRetries, onceOnly, successCount>>

Next ==
    \E j \in JOBS :
        (\E o \in OWNERS : Claim(j, o))
        \/ StartRun(j)
        \/ FinishSuccess(j)
        \/ FinishFailureRetry(j)
        \/ FinishFailureTerminal(j)
        \/ ExpireLease(j)

Spec ==
    Init
    /\ [][Next]_vars
    /\ WF_vars(\E j \in JOBS : StartRun(j))
    /\ WF_vars(\E j \in JOBS : FinishSuccess(j))
    /\ WF_vars(\E j \in JOBS : FinishFailureRetry(j))
    /\ WF_vars(\E j \in JOBS : FinishFailureTerminal(j))
    /\ WF_vars(\E j \in JOBS : ExpireLease(j))

SingleOwnerPerJob ==
    \A j \in JOBS :
        leaseActive[j] => leaseOwner[j] \in OWNERS

OnceOnlyRunsAtMostOnceSuccessfully ==
    \A j \in JOBS :
        onceOnly[j] => successCount[j] <= 1

FailedJobsRespectRetryBudget ==
    \A j \in JOBS :
        jobState[j] = "failed" => runCount[j] <= maxRetries[j]

LeasedJobsStayVisible ==
    \A j \in JOBS :
        jobState[j] \in JobStates

ActiveLeaseHasRunnableState ==
    \A j \in JOBS :
        leaseActive[j] => (jobState[j] \in {"leased", "running"} /\ leaseOwner[j] \in OWNERS)

NoDisappearingJobs ==
    \A j \in JOBS :
        jobState[j] \in JobStates

LeasedJobsEventuallyResolve ==
    \A j \in JOBS :
        [](leaseActive[j] => <>(jobState[j] \in {"succeeded", "failed", "expired"} \/ ~leaseActive[j]))

====
