# 字段索引

由 schema.json 的 $defs 生成。每项未列出的字段均拒绝；除明确标记可省略外，字段必填。null 与省略不同。

## ComponentRef

| 字段 | 类型或取值 | 必填 | 结构约束 |
| --- | --- | --- | --- |
| id | string | 是 | {"minLength": 1} |
| version | string | 是 | {"pattern": "^\\d+\\.\\d+\\.\\d+$"} |

## Selection

| 字段 | 类型或取值 | 必填 | 结构约束 |
| --- | --- | --- | --- |
| component | ComponentRef | 是 | {} |
| params_schema_ref | string | 是 | {"minLength": 1} |
| params | object | 是 | {} |

## ArtifactRef

| 字段 | 类型或取值 | 必填 | 结构约束 |
| --- | --- | --- | --- |
| uri | string | 是 | {"minLength": 1} |
| sha256 | string | 是 | {"pattern": "^[0-9a-f]{64}$"} |
| media_type | string | 是 | {"minLength": 1} |
| schema_ref | string \| null | 是 | {} |
| size_bytes | integer | 是 | {"minimum": 0} |

## Payload

object 或 object

## TimePoint

string 或 integer

## TimeScope

| 字段 | 类型或取值 | 必填 | 结构约束 |
| --- | --- | --- | --- |
| start | TimePoint | 是 | {} |
| end | TimePoint \| null | 是 | {} |

## Clock

| 字段 | 类型或取值 | 必填 | 结构约束 |
| --- | --- | --- | --- |
| domain | event_time / sample_index / step | 是 | {} |
| now | TimePoint | 是 | {} |
| visible_until | TimePoint | 是 | {} |

## Error

| 字段 | 类型或取值 | 必填 | 结构约束 |
| --- | --- | --- | --- |
| code | incompatible / invalid_config / invalid_state / schema_mismatch / permission_denied / cursor_mismatch / transport_error / timeout / invalid_output / unknown_effect / capture_failed / cancelled / internal_error | 是 | {} |
| stage | plan / source / binding / task / method / runtime / evaluation / recording | 是 | {} |
| message | string | 是 | {"minLength": 1} |
| retry | never / idempotent_only | 是 | {} |
| effect_state | none / unknown / committed | 是 | {} |
| details | object | 是 | {} |

## Variable

| 字段 | 类型或取值 | 必填 | 结构约束 |
| --- | --- | --- | --- |
| name | string | 是 | {"minLength": 1} |
| dtype | float64 / int64 / bool / string / tensor | 是 | {} |
| unit | string | 是 | {"minLength": 1} |
| shape | list[integer] | 是 | {"minItems": 0} |
| value_schema_ref | string | 是 | {"minLength": 1} |

## OperationSpec

| 字段 | 类型或取值 | 必填 | 结构约束 |
| --- | --- | --- | --- |
| name | string | 是 | {"minLength": 1} |
| arguments_schema_ref | string | 是 | {"minLength": 1} |
| receipt_schema_ref | string | 是 | {"minLength": 1} |
| changes_state | boolean | 是 | {} |
| idempotent | boolean | 是 | {} |

## Series

| 字段 | 类型或取值 | 必填 | 结构约束 |
| --- | --- | --- | --- |
| entity | string | 是 | {"minLength": 1} |
| variable | string | 是 | {"minLength": 1} |
| unit | string | 是 | {"minLength": 1} |
| timestamps | list[TimePoint] | 是 | {"minItems": 0} |
| values | list[number \| null] | 是 | {"minItems": 0} |
| valid_mask | list[boolean] | 是 | {"minItems": 0} |
| available_at | list[TimePoint] | 是 | {"minItems": 0} |

## SeriesFrame

| 字段 | 类型或取值 | 必填 | 结构约束 |
| --- | --- | --- | --- |
| series | list[Series] | 是 | {"minItems": 0} |

## Window

| 字段 | 类型或取值 | 必填 | 结构约束 |
| --- | --- | --- | --- |
| entity | string | 是 | {"minLength": 1} |
| variable | string | 是 | {"minLength": 1} |
| unit | string | 是 | {"minLength": 1} |
| timestamps | list[string] 最少 1 项 | 是 | {"minItems": 1} |
| values | list[number \| null] 最少 1 项 | 是 | {"minItems": 1} |
| valid_mask | list[boolean] 最少 1 项 | 是 | {"minItems": 1} |

## SourceDescription

| 字段 | 类型或取值 | 必填 | 结构约束 |
| --- | --- | --- | --- |
| component | ComponentRef | 是 | {} |
| clock_domain | event_time / sample_index / step | 是 | {} |
| advance_mode | on_read / on_action / external | 是 | {} |
| observation_schema_ref | string | 是 | {"minLength": 1} |
| variables | list[Variable] 最少 1 项 | 是 | {"minItems": 1} |
| read_modes | list[next / query] 最少 1 项 | 是 | {"minItems": 1} |
| operations | list[OperationSpec] | 是 | {"minItems": 0} |
| start_modes | list[reinitialize / attach] 最少 1 项 | 是 | {"minItems": 1} |
| supports_seed | boolean | 是 | {} |
| public_context_schema_ref | string \| null | 是 | {} |

## Requirement

| 字段 | 类型或取值 | 必填 | 结构约束 |
| --- | --- | --- | --- |
| variable | string | 是 | {"minLength": 1} |
| unit | string | 是 | {"minLength": 1} |
| dtype | string | 是 | {"minLength": 1} |
| shape | list[integer] | 是 | {"minItems": 0} |

## TaskDescription

| 字段 | 类型或取值 | 必填 | 结构约束 |
| --- | --- | --- | --- |
| component | ComponentRef | 是 | {} |
| contract_ref | ComponentRef | 是 | {} |
| input_schema_ref | string | 是 | {"minLength": 1} |
| answer_schema_ref | string | 是 | {"minLength": 1} |
| alignment_schema_ref | string | 是 | {"minLength": 1} |
| required_variables | list[Requirement] 最少 1 项 | 是 | {"minItems": 1} |
| required_read_modes | list[next / query] 最少 1 项 | 是 | {"minItems": 1} |
| required_operations | list[OperationSpec] | 是 | {"minItems": 0} |
| clock_domain | event_time / sample_index / step | 是 | {} |
| minimum_points | integer | 是 | {"minimum": 1} |
| missing_policy | reject / preserve_mask | 是 | {} |
| max_turns | integer | 是 | {"minimum": 1} |

## ContractSupport

| 字段 | 类型或取值 | 必填 | 结构约束 |
| --- | --- | --- | --- |
| contract_ref | ComponentRef | 是 | {} |
| input_schema_ref | string | 是 | {"minLength": 1} |
| answer_schema_ref | string | 是 | {"minLength": 1} |
| supports_tools | boolean | 是 | {} |

## MethodDescription

| 字段 | 类型或取值 | 必填 | 结构约束 |
| --- | --- | --- | --- |
| component | ComponentRef | 是 | {} |
| contracts | list[ContractSupport] 最少 1 项 | 是 | {"minItems": 1} |
| accepted_modalities | list[string] 最少 1 项 | 是 | {"minItems": 1} |
| accepted_runtime_kinds | list[inprocess / worker_rpc] 最少 1 项 | 是 | {"minItems": 1} |
| supports_fit | boolean | 是 | {} |
| supports_update | boolean | 是 | {} |
| supports_cancellation | boolean | 是 | {} |
| required_capture | list[request / response] 最少 1 项 | 是 | {"minItems": 1} |

## RuntimeDescription

| 字段 | 类型或取值 | 必填 | 结构约束 |
| --- | --- | --- | --- |
| component | ComponentRef | 是 | {} |
| kind | inprocess / worker_rpc | 是 | {} |
| persistent_sessions | boolean | 是 | {} |
| hard_timeout | boolean | 是 | {} |
| supports_cancellation | boolean | 是 | {} |

## Binding

| 字段 | 类型或取值 | 必填 | 结构约束 |
| --- | --- | --- | --- |
| id | string | 是 | {"minLength": 1} |
| version | "1.0.0" | 是 | {} |
| variables | list[object] 最少 1 项 | 是 | {"minItems": 1} |
| operations | list[object] | 是 | {"minItems": 0} |

## ResolvedBinding

| 字段 | 类型或取值 | 必填 | 结构约束 |
| --- | --- | --- | --- |
| binding | Binding | 是 | {} |
| source_description | SourceDescription | 是 | {} |
| task_description | TaskDescription | 是 | {} |

## ReadSelection

| 字段 | 类型或取值 | 必填 | 结构约束 |
| --- | --- | --- | --- |
| entities | list[string] 最少 1 项 | 是 | {"minItems": 1} |
| variables | list[string] 最少 1 项 | 是 | {"minItems": 1} |
| scope | TimeScope \| null | 是 | {} |

## ReadIntent

| 字段 | 类型或取值 | 必填 | 结构约束 |
| --- | --- | --- | --- |
| kind | next / query | 是 | {} |
| selection | ReadSelection | 是 | {} |
| as_of | TimePoint | 是 | {} |
| max_wait_ms | integer | 是 | {"minimum": 0} |
| limit | integer | 是 | {"minimum": 1} |
| case_key | string \| null | 是 | {} |

## ServiceHandle

| 字段 | 类型或取值 | 必填 | 结构约束 |
| --- | --- | --- | --- |
| id | string | 是 | {"minLength": 1} |
| service | artifacts / evidence / credentials / tools | 是 | {} |
| operations | list[string] 最少 1 项 | 是 | {"minItems": 1} |
| resource_refs | list[ArtifactRef] | 是 | {"minItems": 0} |

## TaskContext

| 字段 | 类型或取值 | 必填 | 结构约束 |
| --- | --- | --- | --- |
| run_id | string | 是 | {"minLength": 1} |
| task_session_id | string | 是 | {"minLength": 1} |
| read_scope | TimeScope | 是 | {} |
| decision_scope | TimeScope | 是 | {} |
| decision_as_of | TimePoint | 是 | {} |
| max_turns | integer | 是 | {"minimum": 1} |

## SourceContext

| 字段 | 类型或取值 | 必填 | 结构约束 |
| --- | --- | --- | --- |
| run_id | string | 是 | {"minLength": 1} |
| handles | list[ServiceHandle] | 是 | {"minItems": 0} |

## MethodContext

| 字段 | 类型或取值 | 必填 | 结构约束 |
| --- | --- | --- | --- |
| run_id | string | 是 | {"minLength": 1} |
| method_session_id | string | 是 | {"minLength": 1} |
| handles | list[ServiceHandle] | 是 | {"minItems": 0} |
| learning | "frozen" | 是 | {} |
| input_grants | list[ArtifactRef] | 是 | {"minItems": 0} |

## Limits

| 字段 | 类型或取值 | 必填 | 结构约束 |
| --- | --- | --- | --- |
| max_inputs | integer | 是 | {"minimum": 1} |
| max_turns_per_case | integer | 是 | {"minimum": 1} |
| max_operations | integer | 是 | {"minimum": 0} |
| call_timeout_ms | integer | 是 | {"minimum": 1} |
| require_hard_timeout | boolean | 是 | {} |

## RunSpec

| 字段 | 类型或取值 | 必填 | 结构约束 |
| --- | --- | --- | --- |
| source | Selection | 是 | {} |
| task | Selection | 是 | {} |
| binding | Binding | 是 | {} |
| method | Selection | 是 | {} |
| runtime | Selection | 是 | {} |
| read_scope | TimeScope | 是 | {} |
| decision_scope | TimeScope | 是 | {} |
| decision_as_of | TimePoint | 是 | {} |
| seed | integer \| null | 是 | {} |
| limits | Limits | 是 | {} |
| recording | "strict_io" | 是 | {} |

## LockEntry

| 字段 | 类型或取值 | 必填 | 结构约束 |
| --- | --- | --- | --- |
| role | source / task / method / runtime / codec / task_contract | 是 | {} |
| component | ComponentRef | 是 | {} |
| distribution | string | 是 | {"minLength": 1} |
| implementation_sha256 | string \| null | 是 | {} |
| config_sha256 | string | 是 | {"pattern": "^[0-9a-f]{64}$"} |

## Plan

| 字段 | 类型或取值 | 必填 | 结构约束 |
| --- | --- | --- | --- |
| spec_sha256 | string | 是 | {"pattern": "^[0-9a-f]{64}$"} |
| components | list[LockEntry] 最少 4 项 | 是 | {"minItems": 4} |
| resolved_binding | ResolvedBinding | 是 | {} |
| method_description | MethodDescription | 是 | {} |
| runtime_description | RuntimeDescription | 是 | {} |
| deployment_verified | boolean | 是 | {} |
| issues | list[Error] | 是 | {"minItems": 0} |

## SourceOpenBody

| 字段 | 类型或取值 | 必填 | 结构约束 |
| --- | --- | --- | --- |
| source | Selection | 是 | {} |
| context | SourceContext | 是 | {} |
| start_mode | reinitialize / attach | 是 | {} |
| read_scope | TimeScope | 是 | {} |
| availability_cutoff | TimePoint | 是 | {} |
| allowed_entities | list[string] 最少 1 项 | 是 | {"minItems": 1} |
| allowed_variables | list[string] 最少 1 项 | 是 | {"minItems": 1} |
| allowed_operations | list[string] | 是 | {"minItems": 0} |
| seed | integer \| null | 是 | {} |

## SourceSessionInfo

| 字段 | 类型或取值 | 必填 | 结构约束 |
| --- | --- | --- | --- |
| session_id | string | 是 | {"minLength": 1} |
| source_component | ComponentRef | 是 | {} |
| source_revision | string | 是 | {"minLength": 1} |
| dataset_revision | string \| null | 是 | {} |
| actual_read_scope | TimeScope | 是 | {} |
| clock | Clock | 是 | {} |
| cursor | string | 是 | {"minLength": 1} |
| ownership | created / attached | 是 | {} |
| public_context | Payload \| null | 是 | {} |

## SourceReadBody

| 字段 | 类型或取值 | 必填 | 结构约束 |
| --- | --- | --- | --- |
| session_id | string | 是 | {"minLength": 1} |
| kind | next / query | 是 | {} |
| cursor | string | 是 | {"minLength": 1} |
| selection | ReadSelection | 是 | {} |
| as_of | TimePoint | 是 | {} |
| max_wait_ms | integer | 是 | {"minimum": 0} |
| limit | integer | 是 | {"minimum": 1} |

## SourceEnd

| 字段 | 类型或取值 | 必填 | 结构约束 |
| --- | --- | --- | --- |
| reason | source_exhausted / scope_end / terminated / truncated | 是 | {} |
| terminated | boolean | 是 | {} |
| truncated | boolean | 是 | {} |

## Feedback

| 字段 | 类型或取值 | 必填 | 结构约束 |
| --- | --- | --- | --- |
| feedback_id | string | 是 | {"minLength": 1} |
| operation_id | string \| null | 是 | {} |
| kind | reward / operation_status / event | 是 | {} |
| event_time | TimePoint | 是 | {} |
| available_at | TimePoint | 是 | {} |
| payload | Payload | 是 | {} |

## ObservationBody

| 字段 | 类型或取值 | 必填 | 结构约束 |
| --- | --- | --- | --- |
| session_id | string | 是 | {"minLength": 1} |
| request_id | string | 是 | {"minLength": 1} |
| source_revision | string | 是 | {"minLength": 1} |
| dataset_revision | string \| null | 是 | {} |
| status | data / waiting / end | 是 | {} |
| cursor_before | string | 是 | {"minLength": 1} |
| cursor_after | string | 是 | {"minLength": 1} |
| clock | Clock | 是 | {} |
| coverage | TimeScope \| null | 是 | {} |
| data | Payload \| null | 是 | {} |
| feedback | list[Feedback] | 是 | {"minItems": 0} |
| end | SourceEnd \| null | 是 | {} |

## BoundObservationBody

| 字段 | 类型或取值 | 必填 | 结构约束 |
| --- | --- | --- | --- |
| task_session_id | string | 是 | {"minLength": 1} |
| source_observation_ref | ArtifactRef | 是 | {} |
| binding | Binding | 是 | {} |
| status | data / waiting / end | 是 | {} |
| clock | Clock | 是 | {} |
| coverage | TimeScope \| null | 是 | {} |
| data | Payload \| null | 是 | {} |
| feedback | list[Feedback] | 是 | {"minItems": 0} |
| end | SourceEnd \| null | 是 | {} |

## TaskBindBody

| 字段 | 类型或取值 | 必填 | 结构约束 |
| --- | --- | --- | --- |
| task | Selection | 是 | {} |
| resolved_binding | ResolvedBinding | 是 | {} |
| context | TaskContext | 是 | {} |

## ToolSpec

| 字段 | 类型或取值 | 必填 | 结构约束 |
| --- | --- | --- | --- |
| name | string | 是 | {"minLength": 1} |
| arguments_schema_ref | string | 是 | {"minLength": 1} |
| result_schema_ref | string | 是 | {"minLength": 1} |
| changes_state | boolean | 是 | {} |

## InputDraft

| 字段 | 类型或取值 | 必填 | 结构约束 |
| --- | --- | --- | --- |
| case_key | string | 是 | {"minLength": 1} |
| turn_id | integer | 是 | {"minimum": 0} |
| contract_ref | ComponentRef | 是 | {} |
| decision_time | TimePoint | 是 | {} |
| alignment | Payload | 是 | {} |
| observation_refs | list[ArtifactRef] 最少 1 项 | 是 | {"minItems": 1} |
| input | Payload | 是 | {} |
| tools | list[ToolSpec] | 是 | {"minItems": 0} |

## CaseClosure

| 字段 | 类型或取值 | 必填 | 结构约束 |
| --- | --- | --- | --- |
| case_key | string | 是 | {"minLength": 1} |
| status | completed / incomplete | 是 | {} |
| reason | string | 是 | {"minLength": 1} |

## TaskUpdateBody

| 字段 | 类型或取值 | 必填 | 结构约束 |
| --- | --- | --- | --- |
| task_session_id | string | 是 | {"minLength": 1} |
| inputs | list[InputDraft] | 是 | {"minItems": 0} |
| closed_cases | list[CaseClosure] | 是 | {"minItems": 0} |
| stream_done | boolean | 是 | {} |

## TaskInputBody

| 字段 | 类型或取值 | 必填 | 结构约束 |
| --- | --- | --- | --- |
| task_session_id | string | 是 | {"minLength": 1} |
| case_id | string | 是 | {"minLength": 1} |
| case_key | string | 是 | {"minLength": 1} |
| turn_id | integer | 是 | {"minimum": 0} |
| contract_ref | ComponentRef | 是 | {} |
| decision_time | TimePoint | 是 | {} |
| alignment | Payload | 是 | {} |
| observation_refs | list[ArtifactRef] 最少 1 项 | 是 | {"minItems": 1} |
| input | Payload | 是 | {} |
| tools | list[ToolSpec] | 是 | {"minItems": 0} |

## MethodOpenBody

| 字段 | 类型或取值 | 必填 | 结构约束 |
| --- | --- | --- | --- |
| method | Selection | 是 | {} |
| runtime | Selection | 是 | {} |
| contract_ref | ComponentRef | 是 | {} |
| context | MethodContext | 是 | {} |

## MethodIdentity

| 字段 | 类型或取值 | 必填 | 结构约束 |
| --- | --- | --- | --- |
| implementation | ComponentRef | 是 | {} |
| configured_model | string \| null | 是 | {} |
| reported_model | string \| null | 是 | {} |
| weight_revision | string \| null | 是 | {} |
| weights_verified | boolean | 是 | {} |
| evidence_origin | live / synthetic_fixture / reference_calculation | 是 | {} |

## MethodSessionInfo

| 字段 | 类型或取值 | 必填 | 结构约束 |
| --- | --- | --- | --- |
| session_id | string | 是 | {"minLength": 1} |
| runtime_component | ComponentRef | 是 | {} |
| identity | MethodIdentity | 是 | {} |
| state | "ready" | 是 | {} |

## ToolCall

| 字段 | 类型或取值 | 必填 | 结构约束 |
| --- | --- | --- | --- |
| kind | "tool_call" | 是 | {} |
| call_id | string | 是 | {"minLength": 1} |
| name | string | 是 | {"minLength": 1} |
| arguments | Payload | 是 | {} |

## AnswerAction

| 字段 | 类型或取值 | 必填 | 结构约束 |
| --- | --- | --- | --- |
| kind | "answer" | 是 | {} |
| answer | Payload | 是 | {} |

## MethodAction

ToolCall 或 AnswerAction

## MethodResponseBody

| 字段 | 类型或取值 | 必填 | 结构约束 |
| --- | --- | --- | --- |
| session_id | string | 是 | {"minLength": 1} |
| input_id | string | 是 | {"minLength": 1} |
| invocation_id | string | 是 | {"minLength": 1} |
| contract_ref | ComponentRef | 是 | {} |
| status | ok / invalid_output / failed | 是 | {} |
| action | MethodAction \| null | 是 | {} |
| request_ref | ArtifactRef \| null | 是 | {} |
| response_ref | ArtifactRef \| null | 是 | {} |
| identity | MethodIdentity | 是 | {} |
| error | Error \| null | 是 | {} |

## TaskResultBody

| 字段 | 类型或取值 | 必填 | 结构约束 |
| --- | --- | --- | --- |
| case_id | string | 是 | {"minLength": 1} |
| input_id | string | 是 | {"minLength": 1} |
| invocation_id | string | 是 | {"minLength": 1} |
| contract_ref | ComponentRef | 是 | {} |
| decision_time | TimePoint | 是 | {} |
| alignment | Payload | 是 | {} |
| status | valid / invalid | 是 | {} |
| answer | Payload \| null | 是 | {} |
| error | Error \| null | 是 | {} |

## QueryRequest

| 字段 | 类型或取值 | 必填 | 结构约束 |
| --- | --- | --- | --- |
| kind | "query" | 是 | {} |
| request_id | string | 是 | {"minLength": 1} |
| case_key | string | 是 | {"minLength": 1} |
| input_id | string | 是 | {"minLength": 1} |
| invocation_id | string | 是 | {"minLength": 1} |
| read | ReadIntent | 是 | {} |

## CommandRequest

| 字段 | 类型或取值 | 必填 | 结构约束 |
| --- | --- | --- | --- |
| kind | "command" | 是 | {} |
| request_id | string | 是 | {"minLength": 1} |
| case_key | string | 是 | {"minLength": 1} |
| input_id | string | 是 | {"minLength": 1} |
| invocation_id | string | 是 | {"minLength": 1} |
| operation | string | 是 | {"minLength": 1} |
| arguments | Payload | 是 | {} |

## TaskRequest

QueryRequest 或 CommandRequest

## TaskEffectBody

| 字段 | 类型或取值 | 必填 | 结构约束 |
| --- | --- | --- | --- |
| task_session_id | string | 是 | {"minLength": 1} |
| case_key | string | 是 | {"minLength": 1} |
| results | list[TaskResultBody] | 是 | {"minItems": 0} |
| requests | list[TaskRequest] | 是 | {"maxItems": 1} |
| complete | boolean | 是 | {} |

## SourceActBody

| 字段 | 类型或取值 | 必填 | 结构约束 |
| --- | --- | --- | --- |
| session_id | string | 是 | {"minLength": 1} |
| operation_id | string | 是 | {"minLength": 1} |
| request_id | string | 是 | {"minLength": 1} |
| input_id | string | 是 | {"minLength": 1} |
| invocation_id | string | 是 | {"minLength": 1} |
| operation | string | 是 | {"minLength": 1} |
| arguments | Payload | 是 | {} |
| idempotency_key | string \| null | 是 | {} |

## ActionReceiptBody

| 字段 | 类型或取值 | 必填 | 结构约束 |
| --- | --- | --- | --- |
| session_id | string | 是 | {"minLength": 1} |
| operation_id | string | 是 | {"minLength": 1} |
| request_id | string | 是 | {"minLength": 1} |
| status | accepted / completed / rejected / unknown | 是 | {} |
| received_at | string | 是 | {"pattern": "^\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2}(?:\\.\\d+)?Z$", "format": "date-time"} |
| payload | Payload \| null | 是 | {} |
| feedback | list[Feedback] | 是 | {"minItems": 0} |
| error | Error \| null | 是 | {} |

## CloseBody

| 字段 | 类型或取值 | 必填 | 结构约束 |
| --- | --- | --- | --- |
| role | method / task / source | 是 | {} |
| session_id | string | 是 | {"minLength": 1} |
| reason | task_completed / source_end / scope_end / failed / cancelled | 是 | {} |

## CloseResultBody

| 字段 | 类型或取值 | 必填 | 结构约束 |
| --- | --- | --- | --- |
| role | method / task / source | 是 | {} |
| session_id | string | 是 | {"minLength": 1} |
| status | closed / detached / failed | 是 | {} |
| artifact_refs | list[ArtifactRef] | 是 | {"minItems": 0} |
| error | Error \| null | 是 | {} |

## RunSummaryBody

| 字段 | 类型或取值 | 必填 | 结构约束 |
| --- | --- | --- | --- |
| status | succeeded / failed / cancelled | 是 | {} |
| completion | task_completed / source_end / scope_end / failed / cancelled | 是 | {} |
| result_refs | list[ArtifactRef] | 是 | {"minItems": 0} |
| trace_ref | ArtifactRef | 是 | {} |
| cleanup_errors | list[Error] | 是 | {"minItems": 0} |

## ForecastParams

| 字段 | 类型或取值 | 必填 | 结构约束 |
| --- | --- | --- | --- |
| entity | string | 是 | {"minLength": 1} |
| variable | string | 是 | {"minLength": 1} |
| unit | string | 是 | {"minLength": 1} |
| window_points | integer | 是 | {"minimum": 2} |
| horizon_points | integer | 是 | {"minimum": 1} |
| sample_period_seconds | integer | 是 | {"minimum": 1} |

## TrendParams

| 字段 | 类型或取值 | 必填 | 结构约束 |
| --- | --- | --- | --- |
| entity | string | 是 | {"minLength": 1} |
| variable | string | 是 | {"minLength": 1} |
| unit | string | 是 | {"minLength": 1} |
| window_points | integer | 是 | {"minimum": 2} |
| sample_period_seconds | integer | 是 | {"minimum": 1} |
| slope_threshold | number | 是 | {"minimum": 0} |

## ForecastInput

| 字段 | 类型或取值 | 必填 | 结构约束 |
| --- | --- | --- | --- |
| window | Window | 是 | {} |
| target_times | list[string] 最少 1 项 | 是 | {"minItems": 1} |
| output_unit | string | 是 | {"minLength": 1} |

## TrendInput

| 字段 | 类型或取值 | 必填 | 结构约束 |
| --- | --- | --- | --- |
| window | Window | 是 | {} |
| criterion | object | 是 | {} |

## ForecastAnswer

| 字段 | 类型或取值 | 必填 | 结构约束 |
| --- | --- | --- | --- |
| values | list[number] 最少 1 项 | 是 | {"minItems": 1} |
| unit | string | 是 | {"minLength": 1} |

## TrendAnswer

| 字段 | 类型或取值 | 必填 | 结构约束 |
| --- | --- | --- | --- |
| direction | increasing / decreasing / stable | 是 | {} |

## ForecastAlignment

| 字段 | 类型或取值 | 必填 | 结构约束 |
| --- | --- | --- | --- |
| entity | string | 是 | {"minLength": 1} |
| variable | string | 是 | {"minLength": 1} |
| issued_at | string | 是 | {"pattern": "^\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2}(?:\\.\\d+)?Z$", "format": "date-time"} |
| target_times | list[string] 最少 1 项 | 是 | {"minItems": 1} |

## TrendAlignment

| 字段 | 类型或取值 | 必填 | 结构约束 |
| --- | --- | --- | --- |
| entity | string | 是 | {"minLength": 1} |
| variable | string | 是 | {"minLength": 1} |
| issued_at | string | 是 | {"pattern": "^\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2}(?:\\.\\d+)?Z$", "format": "date-time"} |
| window_start | string | 是 | {"pattern": "^\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2}(?:\\.\\d+)?Z$", "format": "date-time"} |
| window_end_inclusive | string | 是 | {"pattern": "^\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2}(?:\\.\\d+)?Z$", "format": "date-time"} |

## OutcomeBody

| 字段 | 类型或取值 | 必填 | 结构约束 |
| --- | --- | --- | --- |
| outcome_id | string | 是 | {"minLength": 1} |
| alignment | Payload | 是 | {} |
| available_at | string | 是 | {"pattern": "^\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2}(?:\\.\\d+)?Z$", "format": "date-time"} |
| purpose | "evaluation" | 是 | {} |
| answer | Payload | 是 | {} |
| source_ref | ArtifactRef | 是 | {} |

## EvaluationBody

| 字段 | 类型或取值 | 必填 | 结构约束 |
| --- | --- | --- | --- |
| evaluation_id | string | 是 | {"minLength": 1} |
| result_ref | ArtifactRef | 是 | {} |
| outcome_ref | ArtifactRef \| null | 是 | {} |
| as_of | string | 是 | {"pattern": "^\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2}(?:\\.\\d+)?Z$", "format": "date-time"} |
| scorer | ComponentRef | 是 | {} |
| status | scored / insufficient_evidence / invalid_result | 是 | {} |
| metrics | list[object] | 是 | {} |

## DeploymentRecord

| 字段 | 类型或取值 | 必填 | 结构约束 |
| --- | --- | --- | --- |
| id | string | 是 | {"minLength": 1} |
| base_url | string | 是 | {"minLength": 1} |
| credential_ref | string \| null | 是 | {} |
| configured_model | string | 是 | {"minLength": 1} |
| declared_weight_revision | string \| null | 是 | {} |
| expected_fingerprint | string \| null | 是 | {} |
| dialect | chatts-timeseries/v1 / chatts-vllm-text-envelope/v1 | 是 | {} |
| processor_revision | string \| null | 是 | {} |
| verification | unverified / verified | 是 | {} |

## EvidenceAppendBody

| 字段 | 类型或取值 | 必填 | 结构约束 |
| --- | --- | --- | --- |
| invocation_id | string | 是 | {"minLength": 1} |
| stage | request / response | 是 | {} |
| content_base64 | string | 是 | {} |
| media_type | string | 是 | {"minLength": 1} |
| schema_ref | string \| null | 是 | {} |

## EvidenceSavedBody

| 字段 | 类型或取值 | 必填 | 结构约束 |
| --- | --- | --- | --- |
| invocation_id | string | 是 | {"minLength": 1} |
| stage | request / response | 是 | {} |
| artifact_ref | ArtifactRef | 是 | {} |

## ExtensionEventBody

| 字段 | 类型或取值 | 必填 | 结构约束 |
| --- | --- | --- | --- |
| producer | ComponentRef | 是 | {} |
| invocation_id | string \| null | 是 | {} |
| payload | Payload | 是 | {} |

## ScoreRequestBody

| 字段 | 类型或取值 | 必填 | 结构约束 |
| --- | --- | --- | --- |
| evaluation_id | string | 是 | {"minLength": 1} |
| result_ref | ArtifactRef | 是 | {} |
| outcome_ref | ArtifactRef \| null | 是 | {} |
| as_of | string | 是 | {"pattern": "^\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2}(?:\\.\\d+)?Z$", "format": "date-time"} |
| scorer | ComponentRef | 是 | {} |

## InvocationContext

| 字段 | 类型或取值 | 必填 | 结构约束 |
| --- | --- | --- | --- |
| run_id | string | 是 | {"minLength": 1} |
| method_session_id | string | 是 | {"minLength": 1} |
| invocation_id | string | 是 | {"minLength": 1} |
| input_id | string | 是 | {"minLength": 1} |
| deadline_at | string | 是 | {"pattern": "^\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2}(?:\\.\\d+)?Z$", "format": "date-time"} |
| handles | list[ServiceHandle] | 是 | {"minItems": 0} |

## JsonValue

JSON value

## ScalarFloat64

number

## PrivateOutcomeFixture

| 字段 | 类型或取值 | 必填 | 结构约束 |
| --- | --- | --- | --- |
| gold | ForecastAnswer \| TrendAnswer | 是 | {} |
| available_at | string | 是 | {"pattern": "^\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2}(?:\\.\\d+)?Z$", "format": "date-time"} |
| purpose | "evaluation" | 是 | {} |

## InvokeBody

| 字段 | 类型或取值 | 必填 | 结构约束 |
| --- | --- | --- | --- |
| session_id | string | 是 | {"minLength": 1} |
| invocation_id | string | 是 | {"minLength": 1} |
| deadline_at | string | 是 | {"pattern": "^\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2}(?:\\.\\d+)?Z$", "format": "date-time"} |
| task_input | TaskInput | 是 | {} |

## RpcFailureBody

| 字段 | 类型或取值 | 必填 | 结构约束 |
| --- | --- | --- | --- |
| session_id | string \| null | 是 | {} |
| invocation_id | string \| null | 是 | {} |
| error | Error | 是 | {} |
| evidence_refs | list[ArtifactRef] | 是 | {"minItems": 0} |

## SourceOpen

| 字段 | 类型或取值 | 必填 | 结构约束 |
| --- | --- | --- | --- |
| protocol | "gymts.wire/2-draft.1" | 是 | {} |
| kind | "SourceOpen" | 是 | {} |
| message_id | string | 是 | {"minLength": 1} |
| sequence | integer | 是 | {"minimum": 1} |
| run_id | string | 是 | {"minLength": 1} |
| caused_by | string \| null | 是 | {} |
| recorded_at | string | 是 | {"pattern": "^\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2}(?:\\.\\d+)?Z$", "format": "date-time"} |
| body | SourceOpenBody | 是 | {} |

## SourceOpened

| 字段 | 类型或取值 | 必填 | 结构约束 |
| --- | --- | --- | --- |
| protocol | "gymts.wire/2-draft.1" | 是 | {} |
| kind | "SourceOpened" | 是 | {} |
| message_id | string | 是 | {"minLength": 1} |
| sequence | integer | 是 | {"minimum": 1} |
| run_id | string | 是 | {"minLength": 1} |
| caused_by | string \| null | 是 | {} |
| recorded_at | string | 是 | {"pattern": "^\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2}(?:\\.\\d+)?Z$", "format": "date-time"} |
| body | SourceSessionInfo | 是 | {} |

## SourceRead

| 字段 | 类型或取值 | 必填 | 结构约束 |
| --- | --- | --- | --- |
| protocol | "gymts.wire/2-draft.1" | 是 | {} |
| kind | "SourceRead" | 是 | {} |
| message_id | string | 是 | {"minLength": 1} |
| sequence | integer | 是 | {"minimum": 1} |
| run_id | string | 是 | {"minLength": 1} |
| caused_by | string \| null | 是 | {} |
| recorded_at | string | 是 | {"pattern": "^\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2}(?:\\.\\d+)?Z$", "format": "date-time"} |
| body | SourceReadBody | 是 | {} |

## Observation

| 字段 | 类型或取值 | 必填 | 结构约束 |
| --- | --- | --- | --- |
| protocol | "gymts.wire/2-draft.1" | 是 | {} |
| kind | "Observation" | 是 | {} |
| message_id | string | 是 | {"minLength": 1} |
| sequence | integer | 是 | {"minimum": 1} |
| run_id | string | 是 | {"minLength": 1} |
| caused_by | string \| null | 是 | {} |
| recorded_at | string | 是 | {"pattern": "^\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2}(?:\\.\\d+)?Z$", "format": "date-time"} |
| body | ObservationBody | 是 | {} |

## BoundObservation

| 字段 | 类型或取值 | 必填 | 结构约束 |
| --- | --- | --- | --- |
| protocol | "gymts.wire/2-draft.1" | 是 | {} |
| kind | "BoundObservation" | 是 | {} |
| message_id | string | 是 | {"minLength": 1} |
| sequence | integer | 是 | {"minimum": 1} |
| run_id | string | 是 | {"minLength": 1} |
| caused_by | string \| null | 是 | {} |
| recorded_at | string | 是 | {"pattern": "^\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2}(?:\\.\\d+)?Z$", "format": "date-time"} |
| body | BoundObservationBody | 是 | {} |

## TaskBind

| 字段 | 类型或取值 | 必填 | 结构约束 |
| --- | --- | --- | --- |
| protocol | "gymts.wire/2-draft.1" | 是 | {} |
| kind | "TaskBind" | 是 | {} |
| message_id | string | 是 | {"minLength": 1} |
| sequence | integer | 是 | {"minimum": 1} |
| run_id | string | 是 | {"minLength": 1} |
| caused_by | string \| null | 是 | {} |
| recorded_at | string | 是 | {"pattern": "^\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2}(?:\\.\\d+)?Z$", "format": "date-time"} |
| body | TaskBindBody | 是 | {} |

## TaskUpdate

| 字段 | 类型或取值 | 必填 | 结构约束 |
| --- | --- | --- | --- |
| protocol | "gymts.wire/2-draft.1" | 是 | {} |
| kind | "TaskUpdate" | 是 | {} |
| message_id | string | 是 | {"minLength": 1} |
| sequence | integer | 是 | {"minimum": 1} |
| run_id | string | 是 | {"minLength": 1} |
| caused_by | string \| null | 是 | {} |
| recorded_at | string | 是 | {"pattern": "^\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2}(?:\\.\\d+)?Z$", "format": "date-time"} |
| body | TaskUpdateBody | 是 | {} |

## TaskInput

| 字段 | 类型或取值 | 必填 | 结构约束 |
| --- | --- | --- | --- |
| protocol | "gymts.wire/2-draft.1" | 是 | {} |
| kind | "TaskInput" | 是 | {} |
| message_id | string | 是 | {"minLength": 1} |
| sequence | integer | 是 | {"minimum": 1} |
| run_id | string | 是 | {"minLength": 1} |
| caused_by | string \| null | 是 | {} |
| recorded_at | string | 是 | {"pattern": "^\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2}(?:\\.\\d+)?Z$", "format": "date-time"} |
| body | TaskInputBody | 是 | {} |

## MethodOpen

| 字段 | 类型或取值 | 必填 | 结构约束 |
| --- | --- | --- | --- |
| protocol | "gymts.wire/2-draft.1" | 是 | {} |
| kind | "MethodOpen" | 是 | {} |
| message_id | string | 是 | {"minLength": 1} |
| sequence | integer | 是 | {"minimum": 1} |
| run_id | string | 是 | {"minLength": 1} |
| caused_by | string \| null | 是 | {} |
| recorded_at | string | 是 | {"pattern": "^\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2}(?:\\.\\d+)?Z$", "format": "date-time"} |
| body | MethodOpenBody | 是 | {} |

## MethodOpened

| 字段 | 类型或取值 | 必填 | 结构约束 |
| --- | --- | --- | --- |
| protocol | "gymts.wire/2-draft.1" | 是 | {} |
| kind | "MethodOpened" | 是 | {} |
| message_id | string | 是 | {"minLength": 1} |
| sequence | integer | 是 | {"minimum": 1} |
| run_id | string | 是 | {"minLength": 1} |
| caused_by | string \| null | 是 | {} |
| recorded_at | string | 是 | {"pattern": "^\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2}(?:\\.\\d+)?Z$", "format": "date-time"} |
| body | MethodSessionInfo | 是 | {} |

## Invoke

| 字段 | 类型或取值 | 必填 | 结构约束 |
| --- | --- | --- | --- |
| protocol | "gymts.wire/2-draft.1" | 是 | {} |
| kind | "Invoke" | 是 | {} |
| message_id | string | 是 | {"minLength": 1} |
| sequence | integer | 是 | {"minimum": 1} |
| run_id | string | 是 | {"minLength": 1} |
| caused_by | string \| null | 是 | {} |
| recorded_at | string | 是 | {"pattern": "^\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2}(?:\\.\\d+)?Z$", "format": "date-time"} |
| body | InvokeBody | 是 | {} |

## MethodResponse

| 字段 | 类型或取值 | 必填 | 结构约束 |
| --- | --- | --- | --- |
| protocol | "gymts.wire/2-draft.1" | 是 | {} |
| kind | "MethodResponse" | 是 | {} |
| message_id | string | 是 | {"minLength": 1} |
| sequence | integer | 是 | {"minimum": 1} |
| run_id | string | 是 | {"minLength": 1} |
| caused_by | string \| null | 是 | {} |
| recorded_at | string | 是 | {"pattern": "^\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2}(?:\\.\\d+)?Z$", "format": "date-time"} |
| body | MethodResponseBody | 是 | {} |

## TaskEffect

| 字段 | 类型或取值 | 必填 | 结构约束 |
| --- | --- | --- | --- |
| protocol | "gymts.wire/2-draft.1" | 是 | {} |
| kind | "TaskEffect" | 是 | {} |
| message_id | string | 是 | {"minLength": 1} |
| sequence | integer | 是 | {"minimum": 1} |
| run_id | string | 是 | {"minLength": 1} |
| caused_by | string \| null | 是 | {} |
| recorded_at | string | 是 | {"pattern": "^\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2}(?:\\.\\d+)?Z$", "format": "date-time"} |
| body | TaskEffectBody | 是 | {} |

## TaskResult

| 字段 | 类型或取值 | 必填 | 结构约束 |
| --- | --- | --- | --- |
| protocol | "gymts.wire/2-draft.1" | 是 | {} |
| kind | "TaskResult" | 是 | {} |
| message_id | string | 是 | {"minLength": 1} |
| sequence | integer | 是 | {"minimum": 1} |
| run_id | string | 是 | {"minLength": 1} |
| caused_by | string \| null | 是 | {} |
| recorded_at | string | 是 | {"pattern": "^\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2}(?:\\.\\d+)?Z$", "format": "date-time"} |
| body | TaskResultBody | 是 | {} |

## SourceAct

| 字段 | 类型或取值 | 必填 | 结构约束 |
| --- | --- | --- | --- |
| protocol | "gymts.wire/2-draft.1" | 是 | {} |
| kind | "SourceAct" | 是 | {} |
| message_id | string | 是 | {"minLength": 1} |
| sequence | integer | 是 | {"minimum": 1} |
| run_id | string | 是 | {"minLength": 1} |
| caused_by | string \| null | 是 | {} |
| recorded_at | string | 是 | {"pattern": "^\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2}(?:\\.\\d+)?Z$", "format": "date-time"} |
| body | SourceActBody | 是 | {} |

## ActionReceipt

| 字段 | 类型或取值 | 必填 | 结构约束 |
| --- | --- | --- | --- |
| protocol | "gymts.wire/2-draft.1" | 是 | {} |
| kind | "ActionReceipt" | 是 | {} |
| message_id | string | 是 | {"minLength": 1} |
| sequence | integer | 是 | {"minimum": 1} |
| run_id | string | 是 | {"minLength": 1} |
| caused_by | string \| null | 是 | {} |
| recorded_at | string | 是 | {"pattern": "^\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2}(?:\\.\\d+)?Z$", "format": "date-time"} |
| body | ActionReceiptBody | 是 | {} |

## Close

| 字段 | 类型或取值 | 必填 | 结构约束 |
| --- | --- | --- | --- |
| protocol | "gymts.wire/2-draft.1" | 是 | {} |
| kind | "Close" | 是 | {} |
| message_id | string | 是 | {"minLength": 1} |
| sequence | integer | 是 | {"minimum": 1} |
| run_id | string | 是 | {"minLength": 1} |
| caused_by | string \| null | 是 | {} |
| recorded_at | string | 是 | {"pattern": "^\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2}(?:\\.\\d+)?Z$", "format": "date-time"} |
| body | CloseBody | 是 | {} |

## Closed

| 字段 | 类型或取值 | 必填 | 结构约束 |
| --- | --- | --- | --- |
| protocol | "gymts.wire/2-draft.1" | 是 | {} |
| kind | "Closed" | 是 | {} |
| message_id | string | 是 | {"minLength": 1} |
| sequence | integer | 是 | {"minimum": 1} |
| run_id | string | 是 | {"minLength": 1} |
| caused_by | string \| null | 是 | {} |
| recorded_at | string | 是 | {"pattern": "^\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2}(?:\\.\\d+)?Z$", "format": "date-time"} |
| body | CloseResultBody | 是 | {} |

## RunSummary

| 字段 | 类型或取值 | 必填 | 结构约束 |
| --- | --- | --- | --- |
| protocol | "gymts.wire/2-draft.1" | 是 | {} |
| kind | "RunSummary" | 是 | {} |
| message_id | string | 是 | {"minLength": 1} |
| sequence | integer | 是 | {"minimum": 1} |
| run_id | string | 是 | {"minLength": 1} |
| caused_by | string \| null | 是 | {} |
| recorded_at | string | 是 | {"pattern": "^\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2}(?:\\.\\d+)?Z$", "format": "date-time"} |
| body | RunSummaryBody | 是 | {} |

## Outcome

| 字段 | 类型或取值 | 必填 | 结构约束 |
| --- | --- | --- | --- |
| protocol | "gymts.wire/2-draft.1" | 是 | {} |
| kind | "Outcome" | 是 | {} |
| message_id | string | 是 | {"minLength": 1} |
| sequence | integer | 是 | {"minimum": 1} |
| run_id | string | 是 | {"minLength": 1} |
| caused_by | string \| null | 是 | {} |
| recorded_at | string | 是 | {"pattern": "^\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2}(?:\\.\\d+)?Z$", "format": "date-time"} |
| body | OutcomeBody | 是 | {} |

## Evaluation

| 字段 | 类型或取值 | 必填 | 结构约束 |
| --- | --- | --- | --- |
| protocol | "gymts.wire/2-draft.1" | 是 | {} |
| kind | "Evaluation" | 是 | {} |
| message_id | string | 是 | {"minLength": 1} |
| sequence | integer | 是 | {"minimum": 1} |
| run_id | string | 是 | {"minLength": 1} |
| caused_by | string \| null | 是 | {} |
| recorded_at | string | 是 | {"pattern": "^\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2}(?:\\.\\d+)?Z$", "format": "date-time"} |
| body | EvaluationBody | 是 | {} |

## RpcFailure

| 字段 | 类型或取值 | 必填 | 结构约束 |
| --- | --- | --- | --- |
| protocol | "gymts.wire/2-draft.1" | 是 | {} |
| kind | "RpcFailure" | 是 | {} |
| message_id | string | 是 | {"minLength": 1} |
| sequence | integer | 是 | {"minimum": 1} |
| run_id | string | 是 | {"minLength": 1} |
| caused_by | string \| null | 是 | {} |
| recorded_at | string | 是 | {"pattern": "^\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2}(?:\\.\\d+)?Z$", "format": "date-time"} |
| body | RpcFailureBody | 是 | {} |

## EvidenceAppend

| 字段 | 类型或取值 | 必填 | 结构约束 |
| --- | --- | --- | --- |
| protocol | "gymts.wire/2-draft.1" | 是 | {} |
| kind | "EvidenceAppend" | 是 | {} |
| message_id | string | 是 | {"minLength": 1} |
| sequence | integer | 是 | {"minimum": 1} |
| run_id | string | 是 | {"minLength": 1} |
| caused_by | string \| null | 是 | {} |
| recorded_at | string | 是 | {"pattern": "^\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2}(?:\\.\\d+)?Z$", "format": "date-time"} |
| body | EvidenceAppendBody | 是 | {} |

## EvidenceSaved

| 字段 | 类型或取值 | 必填 | 结构约束 |
| --- | --- | --- | --- |
| protocol | "gymts.wire/2-draft.1" | 是 | {} |
| kind | "EvidenceSaved" | 是 | {} |
| message_id | string | 是 | {"minLength": 1} |
| sequence | integer | 是 | {"minimum": 1} |
| run_id | string | 是 | {"minLength": 1} |
| caused_by | string \| null | 是 | {} |
| recorded_at | string | 是 | {"pattern": "^\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2}(?:\\.\\d+)?Z$", "format": "date-time"} |
| body | EvidenceSavedBody | 是 | {} |

## ExtensionEvent

| 字段 | 类型或取值 | 必填 | 结构约束 |
| --- | --- | --- | --- |
| protocol | "gymts.wire/2-draft.1" | 是 | {} |
| kind | "ExtensionEvent" | 是 | {} |
| message_id | string | 是 | {"minLength": 1} |
| sequence | integer | 是 | {"minimum": 1} |
| run_id | string | 是 | {"minLength": 1} |
| caused_by | string \| null | 是 | {} |
| recorded_at | string | 是 | {"pattern": "^\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2}(?:\\.\\d+)?Z$", "format": "date-time"} |
| body | ExtensionEventBody | 是 | {} |

## ScoreRequest

| 字段 | 类型或取值 | 必填 | 结构约束 |
| --- | --- | --- | --- |
| protocol | "gymts.wire/2-draft.1" | 是 | {} |
| kind | "ScoreRequest" | 是 | {} |
| message_id | string | 是 | {"minLength": 1} |
| sequence | integer | 是 | {"minimum": 1} |
| run_id | string | 是 | {"minLength": 1} |
| caused_by | string \| null | 是 | {} |
| recorded_at | string | 是 | {"pattern": "^\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2}(?:\\.\\d+)?Z$", "format": "date-time"} |
| body | ScoreRequestBody | 是 | {} |

## Message

SourceOpen 或 SourceOpened 或 SourceRead 或 Observation 或 BoundObservation 或 TaskBind 或 TaskUpdate 或 TaskInput 或 MethodOpen 或 MethodOpened 或 Invoke 或 MethodResponse 或 TaskEffect 或 TaskResult 或 SourceAct 或 ActionReceipt 或 Close 或 Closed 或 RunSummary 或 Outcome 或 Evaluation 或 RpcFailure 或 EvidenceAppend 或 EvidenceSaved 或 ExtensionEvent 或 ScoreRequest

## Trace

list[Message]

## SnapshotParams

| 字段 | 类型或取值 | 必填 | 结构约束 |
| --- | --- | --- | --- |
| path | string | 是 | {} |

## CsvParams

| 字段 | 类型或取值 | 必填 | 结构约束 |
| --- | --- | --- | --- |
| path | string | 是 | {} |

## OlsParams

| 字段 | 类型或取值 | 必填 | 结构约束 |
| --- | --- | --- | --- |

## InprocessParams

| 字段 | 类型或取值 | 必填 | 结构约束 |
| --- | --- | --- | --- |

## ChatTSParams

| 字段 | 类型或取值 | 必填 | 结构约束 |
| --- | --- | --- | --- |
| codec_ref | ComponentRef | 是 | {} |
| deployment_ref | string | 是 | {} |
| dialect | chatts-timeseries/v1 / chatts-vllm-text-envelope/v1 | 是 | {} |
| model | string | 是 | {} |
| generation | object | 是 | {} |

