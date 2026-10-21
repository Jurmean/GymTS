"""Import only in the native worker; module-level objects survive DJ spawn.

No GymTS import. Native processing algorithms are invoked without replacement.
"""
import collections
from pathlib import Path
from data_juicer.ops.base_op import OPERATORS
from data_juicer.ops.mapper import generate_qa_from_text_mapper as qa_module
from .common import append_jsonl, native_rows, now, row_identity, sha, write_json


class AuditRun:
    def __init__(self, actual, directory, index, name):
        self.actual, self.directory, self.index, self.name = actual, str(directory), index, name

    def __call__(self, *args, **kwargs):
        directory = Path(self.directory)
        incoming = kwargs.get("dataset", args[0] if args else None)
        before = native_rows(incoming)
        event = {"index": self.index, "operator": self.name, "started_at": now(),
                 "input": before, "input_members": [row_identity(row) for row in before]}
        append_jsonl(directory / "stages-journal.jsonl", dict(event, status="started"))
        try:
            outgoing = self.actual(*args, **kwargs)
            after = native_rows(outgoing)
        except BaseException as error:
            failed = dict(event, status="failed", ended_at=now(),
                          error={"type": type(error).__name__, "message": str(error)})
            append_jsonl(directory / "stages-journal.jsonl", failed)
            write_json(directory / ("stage-%02d.json" % self.index), failed)
            raise
        out_ids = {row["sample_id"] for row in after}
        completed = dict(event, status="succeeded", ended_at=now(), output=after,
            output_members=[row_identity(row) for row in after],
            dropped_ids=[row["sample_id"] for row in before if row["sample_id"] not in out_ids],
            output_count_by_source=dict(collections.Counter(row["sample_id"] for row in after)))
        write_json(directory / ("stage-%02d.json" % self.index), completed)
        append_jsonl(directory / "stages-journal.jsonl", completed)
        return outgoing


@OPERATORS.register_module("gymts_audited_native_qa_mapper")
class AuditedNativeQA(qa_module.GenerateQAFromTextMapper):
    def __init__(self, audit_path: str = "", **kwargs):
        self.audit_path = audit_path
        super().__init__(**kwargs)

    def process_batched(self, samples, rank=None):
        if not self.audit_path:
            raise ValueError("QA audit_path must be explicitly configured before execution")
        original_get_model = qa_module.get_model
        ids = iter(samples["sample_id"])
        call_path = self.audit_path
        class PipelineIO:
            def __init__(self, actual):
                self.actual = actual
            def __call__(self, messages, **kwargs):
                sample_id = next(ids)
                call_id = "dj-model-" + sha({"sample_id": sample_id, "messages": messages})
                value = {"call_id": call_id, "attempt_id": "attempt-1", "sample_id": sample_id,
                    "started_at": now(), "messages": messages, "params": kwargs,
                    "effective_params": {"pipeline_kwargs": kwargs,
                                         "generation_config": self.actual.generation_config.to_dict()}}
                append_jsonl(call_path, dict(value, status="started", ended_at=None))
                try:
                    actual = self.actual(messages, **kwargs)
                except BaseException as error:
                    append_jsonl(call_path, dict(value, status="failed", ended_at=now(),
                        error={"type": type(error).__name__, "message": str(error)}))
                    raise
                append_jsonl(call_path, dict(value, status="succeeded", ended_at=now(), response=actual))
                return actual
        def observed_get_model(*args, **kwargs):
            model, processor = original_get_model(*args, **kwargs)
            return PipelineIO(model), processor
        qa_module.get_model = observed_get_model
        try:
            return super().process_batched(samples, rank)
        finally:
            qa_module.get_model = original_get_model
