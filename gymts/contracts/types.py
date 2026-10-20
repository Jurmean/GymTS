"""Public wire messages. Dictionaries keep persisted and in-process forms identical.

Runtime validation is performed by SchemaRegistry and the service boundaries;
TypedDicts are provided for IDEs and static type checking, not as constructors.
"""
from random import Random
from typing import Any, Dict, List, Optional, TypedDict, Union

TimePoint = Union[str, int]
JSONValue = Any
SchemaRef = str


class ComponentRef(TypedDict):
    name: str
    version: str
    origin_ref: Optional[str]


class ArtifactRef(TypedDict):
    artifact_id: str
    revision: str
    uri: str
    content_hash: Optional[str]
    media_type: str
    schema_ref: Optional[str]
    size_bytes: Optional[int]


class DatasetAssetRef(TypedDict):
    uri: str
    sha256: str
    size_bytes: int
    media_type: str


class SourceUsagePolicy(TypedDict):
    allowed_uses: List[str]
    training_allowed: bool


class DatasetSplit(TypedDict):
    row_count: int
    split_origin: str
    input_indices: List[int]
    target_indices: List[int]


class SourceDatasetRevision(TypedDict):
    protocol_version: str
    dataset_id: str
    config: str
    revision: str
    schema_ref: str
    reader_ref: ComponentRef
    features: dict
    splits: Dict[str, DatasetSplit]
    usage_policy: SourceUsagePolicy
    source_files: List[dict]
    importer_ref: ComponentRef
    inputs: List[DatasetAssetRef]
    series: List[DatasetAssetRef]
    targets: List[DatasetAssetRef]
    quality_report_ref: Optional[DatasetAssetRef]
    card_ref: Optional[DatasetAssetRef]


class BenchmarkDatasetRef(TypedDict):
    dataset_id: str
    config: str
    revision: str
    split: str


class BenchmarkDefinition(TypedDict):
    protocol_version: str
    benchmark_id: str
    revision: str
    resolver_ref: ComponentRef
    datasets: List[BenchmarkDatasetRef]
    params: dict
    card_ref: Optional[DatasetAssetRef]


class Payload(TypedDict, total=False):
    schema_ref: str
    storage: str
    value: JSONValue
    artifact_ref: ArtifactRef


class TimeScope(TypedDict):
    start: TimePoint
    end: Optional[TimePoint]


class DataViewRef(TypedDict):
    view_id: str
    revision: str
    source_refs: List[ArtifactRef]
    selection: Payload
    as_of: Optional[TimePoint]
    purpose: str


class CandidateSpec(TypedDict):
    adapter: str
    version: str
    artifact: Optional[ArtifactRef]
    params: dict
    inherited_state: List[ArtifactRef]


class EnvironmentSpec(TypedDict):
    protocol_version: str
    adapter: str
    version: str
    source: dict
    mapping: dict
    options: dict


class TaskSpec(TypedDict):
    plugin: str
    version: str
    params: dict


class BindingSpec(TypedDict):
    variables: Dict[str, dict]
    operations: Dict[str, dict]


class SceneSpec(TypedDict):
    environment: EnvironmentSpec
    task: TaskSpec
    binding: BindingSpec


class LearningSpec(TypedDict):
    prepare: str
    online: str
    training_view: Optional[DataViewRef]
    training_targets: Optional[DataViewRef]
    alignment_schema_ref: Optional[str]
    allowed_feedback_sources: List[str]


class ExecutionSpec(TypedDict):
    mode: str
    start: dict
    scope: TimeScope
    feedback_until: Optional[TimePoint]
    seed: Optional[int]
    learning: LearningSpec
    limits: dict


class RecordingSpec(TypedDict):
    store_ref: str
    inputs: str
    outputs: str
    artifacts: str
    model_calls: str
    on_capture_failure: str
    redaction_policy_ref: Optional[ArtifactRef]
    extra_event_kinds: List[str]


class ResourceProvenance(TypedDict):
    source_refs: List[ArtifactRef]
    usage_policy_ref: Optional[ArtifactRef]
    benchmark_definition_ref: Optional[ArtifactRef]


class _ExperimentSpecBase(TypedDict):
    protocol_version: str
    name: Optional[str]
    purpose: str
    scene: SceneSpec
    candidate: CandidateSpec
    execution: ExecutionSpec
    recording: RecordingSpec
    extensions: dict


class ExperimentSpec(_ExperimentSpecBase, total=False):
    provenance: ResourceProvenance


class _ValidationReportBase(TypedDict):
    valid: bool
    resolved_spec_ref: Optional[ArtifactRef]
    issues: List[dict]


class ValidationReport(_ValidationReportBase, total=False):
    resolved_spec: Optional[dict]


class AssemblyPlan(TypedDict):
    protocol_version: str
    resolved_spec: dict
    manifests: Dict[str, dict]
    descriptions: Dict[str, dict]
    variables: List[str]
    operations: List[str]
    read_scope: TimeScope
    resource_checks: str


class CompatibilityContext(TypedDict):
    experiment: dict
    environment: dict
    task: dict
    manifests: Dict[str, dict]


class EnvironmentDescription(TypedDict):
    environment_id: str
    adapter_ref: ComponentRef
    clock_domain: str
    observation_granularity: str
    advance_mode: str
    variables: dict
    operations: dict
    capabilities: Dict[str, bool]
    context_schema_ref: Optional[str]
    native_schema_ref: Optional[str]
    default_command: Optional[dict]


class ObservationRequest(TypedDict, total=False):
    request_id: str
    kind: str
    entities: List[str]
    variables: List[str]
    cursor: Optional[str]
    advance_by: str
    max_wait_ms: int
    scope: TimeScope
    query: Optional[Payload]


class ObservationBatch(TypedDict):
    batch_id: str
    request_id: str
    session_id: str
    status: str
    cursor: str
    clock: dict
    coverage: Optional[TimeScope]
    snapshot_time: Optional[TimePoint]
    data: Optional[dict]
    context: Optional[Payload]
    feedback: List[dict]
    end: Optional[dict]


class TaskInput(TypedDict):
    run_id: str
    case_id: str
    turn_id: int
    input_id: str
    task_protocol_ref: str
    decision_time: TimePoint
    alignment_key: dict
    observation_refs: list
    payload: Payload


class CandidateFeedback(TypedDict):
    feedback_id: str
    source_feedback_ids: List[str]
    source_ref: ComponentRef
    input_id: Optional[str]
    output_id: Optional[str]
    available_at: TimePoint
    payload: Payload


class CaseClosure(TypedDict):
    case_id: str
    status: str
    reason: str


class TaskUpdate(TypedDict):
    inputs: List[TaskInput]
    feedback: List[CandidateFeedback]
    closed_cases: List[CaseClosure]
    done: bool


class CandidateOutput(TypedDict):
    input_id: str
    task_protocol_ref: str
    produced_at: str
    model_revision: Optional[str]
    payload: Payload


class TaskResult(TypedDict):
    result_id: str
    run_id: str
    case_id: str
    turn_id: int
    input_id: str
    output_id: str
    task_protocol_ref: str
    decision_time: TimePoint
    alignment_key: dict
    status: str
    payload: Payload


class TaskEffect(TypedDict):
    results: List[TaskResult]
    requests: List[dict]
    complete: bool


class EnvironmentCommand(TypedDict):
    operation_id: str
    request_id: str
    output_id: Optional[str]
    origin: str
    trigger_batch_id: Optional[str]
    name: str
    arguments: Payload
    idempotency_key: Optional[str]


class ActionReceipt(TypedDict):
    receipt_id: str
    operation_id: str
    request_id: str
    status: str
    received_at: str
    payload: Optional[Payload]
    feedback: List[dict]


class EventDraft(TypedDict):
    event_id: str
    run_id: str
    kind: str
    producer_ref: ComponentRef
    source_event_time: Optional[TimePoint]
    caused_by: List[str]
    links: dict
    payload: Payload


class RunResult(TypedDict):
    protocol_version: str
    run_id: str
    purpose: str
    status: str
    completion: str
    started_at: str
    ended_at: str
    resolved_spec_ref: ArtifactRef
    result_ref: ArtifactRef
    trace_ref: ArtifactRef
    artifact_refs: List[ArtifactRef]
    evidence_status: str
    errors: List[dict]
    summary: dict


# Contexts deliberately include live, restricted service objects and are never
# serialized wholesale. Their JSON members are recorded separately by Runner.
class RandomnessContext(TypedDict):
    seed: Optional[int]
    scope: str
    algorithm: str
    backend_enforcement: str


class CandidateContext(TypedDict, total=False):
    run_id: str
    task_protocol_ref: str
    candidate_spec: dict
    implementation_ref: ComponentRef
    session_context: Optional[Payload]
    training_targets: Optional[DataViewRef]
    alignment_schema_ref: Optional[str]
    learning: LearningSpec
    resources: Any
    traces: Any
    execution_seed: Optional[int]
    rng: Random
    randomness: RandomnessContext
TaskExecutionContext = Dict[str, Any]
SessionInfo = Dict[str, Any]
PreparationResult = Dict[str, Any]
UpdateResult = Dict[str, Any]
EnvironmentSummary = Dict[str, Any]
TaskDescription = Dict[str, Any]
TaskSummary = Dict[str, Any]
RunMetadata = Dict[str, Any]
RunRecord = Dict[str, Any]
RecordSnapshot = Dict[str, Any]
EvaluationSpec = Dict[str, Any]
ScoreSpec = Dict[str, Any]
EvaluationReport = Dict[str, Any]
ScoreResult = Dict[str, Any]
