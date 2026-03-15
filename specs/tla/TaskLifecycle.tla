---- MODULE TaskLifecycle ----
\* Small task lifecycle model for Jarvis/OpenClaw-style control-plane work items.
\* This is intentionally smaller than the runtime. It protects safety properties,
\* not every operational detail of routing, publishing, or Discord transport.

EXTENDS Naturals, Sequences, TLC

CONSTANTS TaskA, TaskB, TaskC, NULL

TASKS == {TaskA, TaskB, TaskC}
TaskStates == {
    "created",
    "routed",
    "running",
    "review_pending",
    "approved",
    "rejected",
    "completed",
    "archived",
    "failed"
}
DecisionStates == {"none", "approved", "rejected"}
TerminalStates == {"completed", "archived", "failed", "rejected"}

VARIABLES
    taskState,
    parentTask,
    emittedEvents,
    reviewRequired,
    artifactProduced,
    terminalResult,
    decisionState,
    everArchived,
    transitionCount

vars == <<
    taskState,
    parentTask,
    emittedEvents,
    reviewRequired,
    artifactProduced,
    terminalResult,
    decisionState,
    everArchived,
    transitionCount
>>

Init ==
    /\ taskState = [t \in TASKS |->
        CASE t = TaskA -> "created"
           [] t = TaskB -> "created"
           [] OTHER    -> "created"]
    /\ parentTask = [t \in TASKS |->
        CASE t = TaskC -> TaskA
           [] OTHER    -> NULL]
    /\ reviewRequired = [t \in TASKS |->
        CASE t = TaskB -> FALSE
           [] OTHER    -> TRUE]
    /\ artifactProduced = [t \in TASKS |-> FALSE]
    /\ terminalResult = [t \in TASKS |-> FALSE]
    /\ decisionState = [t \in TASKS |-> "none"]
    /\ everArchived = [t \in TASKS |-> FALSE]
    /\ emittedEvents = <<>>
    /\ transitionCount = 0

Emit(task, fromState, toState, kind) ==
    Append(
        emittedEvents,
        [task |-> task, from |-> fromState, to |-> toState, kind |-> kind]
    )

RouteTask(t) ==
    /\ taskState[t] = "created"
    /\ taskState' = [taskState EXCEPT ![t] = "routed"]
    /\ emittedEvents' = Emit(t, "created", "routed", "route")
    /\ transitionCount' = transitionCount + 1
    /\ UNCHANGED <<parentTask, reviewRequired, artifactProduced, terminalResult, decisionState, everArchived>>

StartTask(t) ==
    /\ taskState[t] = "routed"
    /\ taskState' = [taskState EXCEPT ![t] = "running"]
    /\ emittedEvents' = Emit(t, "routed", "running", "start")
    /\ transitionCount' = transitionCount + 1
    /\ UNCHANGED <<parentTask, reviewRequired, artifactProduced, terminalResult, decisionState, everArchived>>

ProduceArtifact(t) ==
    /\ taskState[t] = "running"
    /\ ~artifactProduced[t]
    /\ artifactProduced' = [artifactProduced EXCEPT ![t] = TRUE]
    /\ emittedEvents' = Append(emittedEvents, [task |-> t, kind |-> "artifact"])
    /\ UNCHANGED <<taskState, parentTask, reviewRequired, terminalResult, decisionState, everArchived, transitionCount>>

FinishWithTerminalResult(t) ==
    /\ taskState[t] = "running"
    /\ ~terminalResult[t]
    /\ terminalResult' = [terminalResult EXCEPT ![t] = TRUE]
    /\ emittedEvents' = Append(emittedEvents, [task |-> t, kind |-> "terminal_result"])
    /\ UNCHANGED <<taskState, parentTask, reviewRequired, artifactProduced, decisionState, everArchived, transitionCount>>

RequestReview(t) ==
    /\ taskState[t] = "running"
    /\ reviewRequired[t]
    /\ artifactProduced[t] \/ terminalResult[t]
    /\ taskState' = [taskState EXCEPT ![t] = "review_pending"]
    /\ emittedEvents' = Emit(t, "running", "review_pending", "request_review")
    /\ transitionCount' = transitionCount + 1
    /\ UNCHANGED <<parentTask, reviewRequired, artifactProduced, terminalResult, decisionState, everArchived>>

ApproveTask(t) ==
    /\ taskState[t] = "review_pending"
    /\ decisionState[t] = "none"
    /\ artifactProduced[t] \/ terminalResult[t]
    /\ taskState' = [taskState EXCEPT ![t] = "approved"]
    /\ decisionState' = [decisionState EXCEPT ![t] = "approved"]
    /\ emittedEvents' = Emit(t, "review_pending", "approved", "approve")
    /\ transitionCount' = transitionCount + 1
    /\ UNCHANGED <<parentTask, reviewRequired, artifactProduced, terminalResult, everArchived>>

RejectTask(t) ==
    /\ taskState[t] = "review_pending"
    /\ decisionState[t] = "none"
    /\ artifactProduced[t] \/ terminalResult[t]
    /\ taskState' = [taskState EXCEPT ![t] = "rejected"]
    /\ decisionState' = [decisionState EXCEPT ![t] = "rejected"]
    /\ emittedEvents' = Emit(t, "review_pending", "rejected", "reject")
    /\ transitionCount' = transitionCount + 1
    /\ UNCHANGED <<parentTask, reviewRequired, artifactProduced, terminalResult, everArchived>>

CompleteApprovedTask(t) ==
    /\ taskState[t] = "approved"
    /\ artifactProduced[t] \/ terminalResult[t]
    /\ taskState' = [taskState EXCEPT ![t] = "completed"]
    /\ emittedEvents' = Emit(t, "approved", "completed", "complete")
    /\ transitionCount' = transitionCount + 1
    /\ UNCHANGED <<parentTask, reviewRequired, artifactProduced, terminalResult, decisionState, everArchived>>

CompleteDirectTask(t) ==
    /\ taskState[t] = "running"
    /\ ~reviewRequired[t]
    /\ artifactProduced[t] \/ terminalResult[t]
    /\ taskState' = [taskState EXCEPT ![t] = "completed"]
    /\ emittedEvents' = Emit(t, "running", "completed", "complete_direct")
    /\ transitionCount' = transitionCount + 1
    /\ UNCHANGED <<parentTask, reviewRequired, artifactProduced, terminalResult, decisionState, everArchived>>

FailTask(t) ==
    /\ taskState[t] = "running"
    /\ taskState' = [taskState EXCEPT ![t] = "failed"]
    /\ terminalResult' = [terminalResult EXCEPT ![t] = TRUE]
    /\ emittedEvents' = Emit(t, "running", "failed", "fail")
    /\ transitionCount' = transitionCount + 1
    /\ UNCHANGED <<parentTask, reviewRequired, artifactProduced, decisionState, everArchived>>

ArchiveTask(t) ==
    /\ taskState[t] \in {"completed", "rejected", "failed"}
    /\ taskState' = [taskState EXCEPT ![t] = "archived"]
    /\ everArchived' = [everArchived EXCEPT ![t] = TRUE]
    /\ emittedEvents' = Emit(t, taskState[t], "archived", "archive")
    /\ transitionCount' = transitionCount + 1
    /\ UNCHANGED <<parentTask, reviewRequired, artifactProduced, terminalResult, decisionState>>

Next ==
    \E t \in TASKS :
        RouteTask(t)
        \/ StartTask(t)
        \/ ProduceArtifact(t)
        \/ FinishWithTerminalResult(t)
        \/ RequestReview(t)
        \/ ApproveTask(t)
        \/ RejectTask(t)
        \/ CompleteApprovedTask(t)
        \/ CompleteDirectTask(t)
        \/ FailTask(t)
        \/ ArchiveTask(t)

Spec ==
    Init
    /\ [][Next]_vars
    /\ WF_vars(\E t \in TASKS : RequestReview(t))
    /\ WF_vars(\E t \in TASKS : ApproveTask(t))
    /\ WF_vars(\E t \in TASKS : RejectTask(t))
    /\ WF_vars(\E t \in TASKS : CompleteApprovedTask(t))
    /\ WF_vars(\E t \in TASKS : CompleteDirectTask(t))
    /\ WF_vars(\E t \in TASKS : FailTask(t))
    /\ WF_vars(\E t \in TASKS : ArchiveTask(t))

NoDualApprovalRejection ==
    \A t \in TASKS :
        ~(decisionState[t] = "approved" /\ decisionState[t] = "rejected")

ArchivedNeverReturnsToRunning ==
    \A t \in TASKS :
        everArchived[t] => taskState[t] # "running"

CompletedHasArtifactOrTerminalResult ==
    \A t \in TASKS :
        taskState[t] = "completed" => (artifactProduced[t] \/ terminalResult[t])

EveryStateTransitionEmitsEvent ==
    Len(emittedEvents) >= transitionCount

ValidParentLinkage ==
    \A t \in TASKS :
        (parentTask[t] = NULL) \/ (parentTask[t] \in TASKS /\ parentTask[t] # t)

RunningWorkEventuallyLeavesRunning ==
    \A t \in TASKS :
        [](((taskState[t] = "running") /\ (artifactProduced[t] \/ terminalResult[t]))
            => <>(taskState[t] \in {"review_pending", "completed", "failed"}))

====
