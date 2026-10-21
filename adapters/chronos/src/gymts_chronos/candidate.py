"""Native model bridge with fixed IO, checkpoint and training provenance."""
import copy
import hashlib
import io
import json
from pathlib import Path
import tempfile
import zipfile

from gymts.contracts import GymTSError, digest, new_id, utc_now
from gymts.plugin_support import component, fail, payload, unpack
from .contracts import OUTPUT, PROTOCOL, UPSTREAM, PIPELINE_SHA256, native_inputs, validate_input
from .runtime import Worker
from .worker import identity


def training_data(resources, view):
    if view is None or view.get('purpose') != 'prepare':
        fail('permission_denied', 'Offline training requires an explicit authorized prepare view')
    dataset = unpack(resources.read_view(view), resources)
    if not isinstance(dataset, dict) or dataset.get('usage') != 'training' or dataset.get('split') != 'train':
        fail('permission_denied', 'Chronos fit accepts only an explicitly training-authorized train view')
    if not isinstance(dataset.get('inputs'), list) or not dataset['inputs']:
        fail('invalid_config', 'The authorized training view has no native training inputs')
    return dataset


def checkpoint_bytes(directory, provenance):
    root = Path(directory)
    manifest = {'model': identity(root), 'training': provenance}
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_STORED) as z:
        z.writestr('gymts-checkpoint.json', json.dumps(manifest, sort_keys=True))
        for name in manifest['model']['files_sha256']:
            z.write(root/name, 'model/'+name)
    return buffer.getvalue()


def unpack_checkpoint(data, destination):
    root = Path(destination)
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        if sum(i.file_size for i in z.infolist()) > 4*1024**3:
            fail('artifact_integrity', 'Checkpoint exceeds the delivered model size limit')
        names = z.namelist()
        if len(names) != len(set(names)):
            fail('artifact_integrity', 'Duplicate archive entries')
        for name in names:
            p = Path(name)
            if p.is_absolute() or '..' in p.parts or (name != 'gymts-checkpoint.json' and not name.startswith('model/')):
                fail('artifact_integrity', 'Unsafe checkpoint archive entry')
        manifest = json.loads(z.read('gymts-checkpoint.json'))
        expected = {'gymts-checkpoint.json'} | {'model/'+n for n in manifest['model']['files_sha256']}
        if set(names) != expected:
            fail('artifact_integrity', 'Checkpoint archive membership differs from its manifest')
        z.extractall(root)
    if identity(root/'model') != manifest['model']:
        fail('artifact_integrity', 'Checkpoint content differs from its immutable manifest')
    return root/'model', manifest


class ChronosCandidate:
    def __init__(self, spec):
        self.spec, self.refs, self.worker, self.temporary = copy.deepcopy(spec), [], None, None

    @staticmethod
    def check_compatibility_spec(context):
        experiment = context['experiment']
        learning = experiment['execution']['learning']
        if learning['online'] != 'frozen' or learning['training_targets'] is not None:
            fail('unsupported_capability', 'Chronos supports offline fit or fixed checkpoint inference only')
        if experiment['candidate']['inherited_state']:
            fail('unsupported_capability', 'Use one explicit immutable checkpoint archive')
        if learning['prepare'] == 'fit' and experiment['candidate']['artifact'] is not None:
            fail('unsupported_capability', 'Initial profile fits a base checkpoint, not an inherited adapter')

    def prepare(self, context, training):
        self.resources, self.traces = context['resources'], context.get('traces')
        params = self.spec['params']
        dataset = training_data(self.resources, training) if context['learning']['prepare'] == 'fit' else None
        if dataset is None and training is not None:
            fail('unsupported_capability', 'Load-only mode does not consume training views')
        model_dir = params['model_dir']
        if self.spec['artifact'] is not None:
            self.temporary = tempfile.TemporaryDirectory(prefix='gymts-chronos-checkpoint-')
            model_dir, manifest = unpack_checkpoint(self.resources.resolve(self.spec['artifact']).read_bytes(), self.temporary.name)
        expected = identity(model_dir)
        if self.spec['artifact'] is None and expected['sha256'] != params.get('model_sha256'):
            fail('conflict', 'A base model requires the explicit frozen model content digest')
        self.worker = Worker(params['python'], params.get('timeout_seconds', 300))
        loaded = self.worker.call('load', {'model_dir': str(model_dir), 'device': params.get('device', 'cpu'),
            'seed': context['execution_seed'] or 0, 'expected_identity': expected})
        if loaded['native_pipeline_sha256'] != PIPELINE_SHA256:
            fail('conflict', 'Installed native Chronos pipeline differs from the declared fixed implementation')
        provenance_ref = None
        if context['learning']['prepare'] == 'fit':
            fit = params.get('fit')
            if not fit:
                fail('invalid_config', 'Fit requires explicit native training parameters')
            self.training_dir = tempfile.TemporaryDirectory(prefix='gymts-chronos-fit-')
            request = dict(fit, inputs=dataset['inputs'], output_dir=self.training_dir.name, seed=context['execution_seed'] or 0)
            request_ref = self.resources.save_json(request, 'gymts.json/1')
            self.refs.append(request_ref)
            proof = self.worker.call('train', request)
            provenance = {'run_id': context['run_id'], 'training_view': training, 'training_input_sha256': digest(dataset),
                          'native_implementation': UPSTREAM, 'request_ref': request_ref, 'proof': proof}
            provenance_ref = self.resources.save_json(provenance, 'gymts.json/1')
            self.refs.append(provenance_ref)
            checkpoint_ref = self.resources.save_artifact(checkpoint_bytes(proof['checkpoint'], provenance),
                {'media_type': 'application/zip', 'schema_ref': 'gymts.chronos/checkpoint-archive/1'})
            self.refs.append(checkpoint_ref)
            expected = proof['identity']
        self.revision = digest({'model': expected, 'native': UPSTREAM})
        self.refs.append(self.resources.save_json(dict(loaded, model_revision=self.revision, model_identity=expected), 'gymts.json/1'))
        return {'model_revision': self.revision, 'state_refs': copy.deepcopy(self.refs), 'training_provenance_ref': provenance_ref}

    def infer(self, task_input):
        data = validate_input(unpack(task_input['payload'], self.resources))
        request = {'inputs': native_inputs(data), 'horizon': data['context']['horizon'], 'quantiles': data['context']['quantiles']}
        request_ref = self.resources.save_json(request, 'gymts.json/1')
        started, call_id = utc_now(), new_id('chronos-model')
        response_ref, error = None, None
        try:
            result = self.worker.call('predict', request)
            response_ref = self.resources.save_json(result, 'gymts.json/1')
        except Exception as exc:
            error = exc.to_dict() if isinstance(exc, GymTSError) else GymTSError(
                'execution_failure', 'Native Chronos inference failed', details={'exception_type':type(exc).__name__}).to_dict()
            raise
        finally:
            if self.traces is not None:
                self.traces.record_model_call({'call_id': call_id, 'attempt_id': '1', 'parent_call_id': None,
                    'status': 'failed' if error else 'succeeded', 'started_at': started, 'ended_at': utc_now(),
                    'model_ref': component('amazon.chronos-2', self.revision), 'adapter_ref': component('gymts-chronos', '0.1.0'),
                    'policy_revision': self.revision, 'request_ref': request_ref, 'response_ref': response_ref,
                    'requested_params': {'quantiles': request['quantiles'], 'horizon': request['horizon']},
                    'effective_params': {'cross_learning': False, 'device': self.spec['params'].get('device', 'cpu')},
                    'tokenizer_ref': None, 'chat_template_ref': None, 'native_inputs_ref': None,
                    'prompt_token_ids_ref': None, 'response_token_ids_ref': None, 'logprobs_ref': None,
                    'usage': {'forecast_targets': len(data['context']['targets'])}, 'error': error,
                    'capture': {'requested_profile': 'io', 'acquired_fields': ['request_ref']+(['response_ref'] if response_ref else []),
                                'missing_fields': {}, 'transforms': [], 'completeness': 'complete'}})
        targets = {}
        for i, name in enumerate(data['context']['targets']):
            targets[name] = {'mean': result['mean'][0][i], 'quantiles': {
                str(float(q)): [step[j] for step in result['quantiles'][0][i]] for j, q in enumerate(request['quantiles'])}}
        return {'input_id': task_input['input_id'], 'task_protocol_ref': PROTOCOL, 'produced_at': utc_now(),
                'model_revision': self.revision, 'payload': payload(OUTPUT, {
                    'raw_text': json.dumps({'targets': targets}, allow_nan=False), 'evidence': {'model_call_id': call_id}})}

    def update(self, feedback):
        fail('unsupported_capability', 'Chronos online policy updates are not enabled')

    def finish(self):
        if self.worker:
            self.worker.close()
            self.worker = None
        if self.temporary:
            self.temporary.cleanup()
        if hasattr(self, 'training_dir'):
            self.training_dir.cleanup()
        return copy.deepcopy(self.refs)
