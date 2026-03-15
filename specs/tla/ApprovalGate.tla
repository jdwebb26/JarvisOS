---- MODULE ApprovalGate ----
\* Review / approval gate model for Jarvis control-plane semantics.
\* This spec focuses on produced work, reviewer availability, and degraded-mode safety.

EXTENDS Naturals, TLC

CONSTANTS TaskA, TaskB

TASKS == {TaskA, TaskB}
TaskStates == {
    "created",
    "work_ready",
    "review_pending",
    "approved",
    "rejected",
    "ready_to_ship",
    "downstream_blocked"
}
DecisionTargets == {"none", "request", "artifact"}

VARIABLES
    taskState,
    reviewRequired,
    reviewerAvailable,
    artifactProduced,
    promotionAllowed,
    rejectionReason,
    degradedMode,
    decisionTarget

vars == <<
    taskState,
    reviewRequired,
    reviewerAvailable,
    artifactProduced,
    promotionAllowed,
    rejectionReason,
    degradedMode,
    decisionTarget
>>

Init ==
    /\ taskState = [t \in TASKS |-> "created"]
    /\ reviewRequired = [t \in TASKS |->
        CASE t = TaskA -> TRUE
           [] OTHER    -> FALSE]
    /\ reviewerAvailable = [t \in TASKS |->
        CASE t = TaskA -> TRUE
           [] OTHER    -> TRUE]
    /\ artifactProduced = [t \in TASKS |-> FALSE]
    /\ promotionAllowed = [t \in TASKS |-> FALSE]
    /\ rejectionReason = [t \in TASKS |-> ""]
    /\ degradedMode = [t \in TASKS |-> FALSE]
    /\ decisionTarget = [t \in TASKS |-> "none"]

ProduceWork(t) ==
    /\ taskState[t] = "created"
    /\ taskState' = [taskState EXCEPT ![t] = "work_ready"]
    /\ artifactProduced' = [artifactProduced EXCEPT ![t] = TRUE]
    /\ UNCHANGED <<reviewRequired, reviewerAvailable, promotionAllowed, rejectionReason, degradedMode, decisionTarget>>

RequestReview(t) ==
    /\ taskState[t] = "work_ready"
    /\ reviewRequired[t]
    /\ artifactProduced[t]
    /\ taskState' = [taskState EXCEPT ![t] = "review_pending"]
    /\ UNCHANGED <<reviewRequired, reviewerAvailable, artifactProduced, promotionAllowed, rejectionReason, degradedMode, decisionTarget>>

AutoAdvanceNoReview(t) ==
    /\ taskState[t] = "work_ready"
    /\ ~reviewRequired[t]
    /\ artifactProduced[t]
    /\ taskState' = [taskState EXCEPT ![t] = "ready_to_ship"]
    /\ promotionAllowed' = [promotionAllowed EXCEPT ![t] = TRUE]
    /\ decisionTarget' = [decisionTarget EXCEPT ![t] = "artifact"]
    /\ UNCHANGED <<reviewRequired, reviewerAvailable, artifactProduced, rejectionReason, degradedMode>>

ApproveProducedWork(t) ==
    /\ taskState[t] = "review_pending"
    /\ reviewerAvailable[t]
    /\ artifactProduced[t]
    /\ decisionTarget[t] \in {"none", "artifact"}
    /\ ~(degradedMode[t] /\ reviewRequired[t] /\ ~reviewerAvailable[t])
    /\ taskState' = [taskState EXCEPT ![t] = "approved"]
    /\ promotionAllowed' = [promotionAllowed EXCEPT ![t] = TRUE]
    /\ decisionTarget' = [decisionTarget EXCEPT ![t] = "artifact"]
    /\ rejectionReason' = [rejectionReason EXCEPT ![t] = ""]
    /\ UNCHANGED <<reviewRequired, reviewerAvailable, artifactProduced, degradedMode>>

RejectProducedWork(t) ==
    /\ taskState[t] = "review_pending"
    /\ artifactProduced[t]
    /\ taskState' = [taskState EXCEPT ![t] = "rejected"]
    /\ promotionAllowed' = [promotionAllowed EXCEPT ![t] = FALSE]
    /\ rejectionReason' = [rejectionReason EXCEPT ![t] = "review_rejected"] 
    /\ decisionTarget' = [decisionTarget EXCEPT ![t] = "artifact"]
    /\ UNCHANGED <<reviewRequired, reviewerAvailable, artifactProduced, degradedMode>>

EnterDegradedMode(t) ==
    /\ ~degradedMode[t]
    /\ degradedMode' = [degradedMode EXCEPT ![t] = TRUE]
    /\ UNCHANGED <<taskState, reviewRequired, reviewerAvailable, artifactProduced, promotionAllowed, rejectionReason, decisionTarget>>

LoseReviewer(t) ==
    /\ reviewerAvailable[t]
    /\ reviewerAvailable' = [reviewerAvailable EXCEPT ![t] = FALSE]
    /\ UNCHANGED <<taskState, reviewRequired, artifactProduced, promotionAllowed, rejectionReason, degradedMode, decisionTarget>>

RecoverReviewer(t) ==
    /\ ~reviewerAvailable[t]
    /\ reviewerAvailable' = [reviewerAvailable EXCEPT ![t] = TRUE]
    /\ UNCHANGED <<taskState, reviewRequired, artifactProduced, promotionAllowed, rejectionReason, degradedMode, decisionTarget>>

BlockRejectedDownstream(t) ==
    /\ taskState[t] = "rejected"
    /\ taskState' = [taskState EXCEPT ![t] = "downstream_blocked"]
    /\ UNCHANGED <<reviewRequired, reviewerAvailable, artifactProduced, promotionAllowed, rejectionReason, degradedMode, decisionTarget>>

Next ==
    \E t \in TASKS :
        ProduceWork(t)
        \/ RequestReview(t)
        \/ AutoAdvanceNoReview(t)
        \/ ApproveProducedWork(t)
        \/ RejectProducedWork(t)
        \/ EnterDegradedMode(t)
        \/ LoseReviewer(t)
        \/ RecoverReviewer(t)
        \/ BlockRejectedDownstream(t)

Spec ==
    Init
    /\ [][Next]_vars
    /\ WF_vars(\E t \in TASKS : ApproveProducedWork(t))
    /\ WF_vars(\E t \in TASKS : RejectProducedWork(t))
    /\ WF_vars(\E t \in TASKS : BlockRejectedDownstream(t))

NoAutoPromoteWithoutReviewer ==
    \A t \in TASKS :
        (reviewRequired[t] /\ ~reviewerAvailable[t]) => ~promotionAllowed[t]

RejectedWorkCannotProceedDownstream ==
    \A t \in TASKS :
        taskState[t] \in {"rejected", "downstream_blocked"} => ~promotionAllowed[t]

PromotionRequiresProducedWork ==
    \A t \in TASKS :
        promotionAllowed[t] => artifactProduced[t]

ReviewDecisionAppliesToProducedWork ==
    \A t \in TASKS :
        taskState[t] \in {"approved", "rejected", "ready_to_ship", "downstream_blocked"}
            => (artifactProduced[t] /\ decisionTarget[t] = "artifact")

DegradedModeDoesNotBypassReview ==
    \A t \in TASKS :
        degradedMode[t] /\ reviewRequired[t] /\ ~reviewerAvailable[t]
            => ~(promotionAllowed[t] /\ taskState[t] \in {"approved", "ready_to_ship"})

ReviewPendingEventuallyResolves ==
    \A t \in TASKS :
        []((taskState[t] = "review_pending" /\ reviewerAvailable[t] /\ artifactProduced[t])
            => <>(taskState[t] \in {"approved", "rejected", "downstream_blocked"}))

====
