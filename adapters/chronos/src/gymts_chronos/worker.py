"""Native Chronos model/trainer. This module is only launched explicitly."""
import contextlib
import hashlib
import importlib.metadata
import inspect
import json
import math
import os
from pathlib import Path
import sys


def identity(directory):
    root = Path(directory)
    selected = sorted(p for p in root.rglob('*') if p.is_file() and
                      (p.name.endswith('.safetensors') or p.name.endswith('.bin') or p.name.endswith('.json'))
                      and '.cache' not in p.parts)
    if not any(p.name.endswith(('.bin', '.safetensors')) for p in selected):
        raise ValueError('No local checkpoint weights')
    hashes = {}
    for p in selected:
        h = hashlib.sha256()
        with p.open('rb') as f:
            for chunk in iter(lambda: f.read(8*1024*1024), b''): h.update(chunk)
        hashes[str(p.relative_to(root))] = h.hexdigest()
    encoded = json.dumps(hashes, sort_keys=True, separators=(',', ':')).encode()
    return {'files_sha256': hashes, 'sha256': hashlib.sha256(encoded).hexdigest()}


def weights_hash(model):
    import torch
    h = hashlib.sha256()
    for name, param in model.state_dict().items():
        h.update(name.encode())
        h.update(param.detach().cpu().contiguous().view(torch.uint8).numpy().tobytes())
    return h.hexdigest()


def tensor_inputs(inputs):
    import numpy as np
    return [{k: ({name: np.asarray(xs, dtype=np.float32) for name, xs in v.items()}
                 if isinstance(v, dict) else np.asarray(v, dtype=np.float32))
             for k, v in item.items()} for item in inputs]


def train(pipeline, args):
    import torch
    from transformers import TrainerCallback, set_seed
    steps = args['steps']
    if type(steps) is not int or not 1 <= steps <= 10000:
        raise ValueError('Training steps must be in [1,10000]')
    set_seed(args['seed'])
    grads, updates = [], []
    class Audit(TrainerCallback):
        def on_pre_optimizer_step(self, args, state, control, model=None, **kwargs):
            squared = sum(float(p.grad.detach().float().square().sum().item())
                          for p in model.parameters() if p.grad is not None)
            grads.append(squared**0.5)
        def on_optimizer_step(self, args, state, control, **kwargs):
            updates.append(int(state.global_step)+1)
    before = weights_hash(pipeline.model)
    updated = pipeline.fit(tensor_inputs(args['inputs']), prediction_length=args['horizon'],
        context_length=args['context_length'], num_steps=steps, batch_size=args['batch_size'],
        learning_rate=args['learning_rate'], finetune_mode='full', output_dir=args['output_dir'],
        callbacks=[Audit()], seed=args['seed'], data_seed=args['seed'], weight_decay=0.0,
        logging_steps=1, disable_tqdm=True)
    if len(updates) != steps or len(grads) != steps or not all(math.isfinite(x) for x in grads) or not any(x > 0 for x in grads):
        raise ValueError('Native training did not prove finite gradients and the requested optimizer updates')
    if not all(bool(torch.isfinite(p).all().item()) for p in updated.model.parameters()):
        raise ValueError('Native training produced non-finite parameters')
    after = weights_hash(updated.model)
    if before == after:
        raise ValueError('Native training did not change model weights')
    checkpoint = Path(args['output_dir'])/'published-checkpoint'
    updated.save_pretrained(checkpoint, safe_serialization=True)
    proof = {'initial_weights_sha256': before, 'final_weights_sha256': after, 'gradient_norms': grads,
             'optimizer_updates': len(updates), 'optimizer_step_ids': updates, 'weight_decay': 0.0,
             'requested_steps': steps, 'checkpoint': str(checkpoint), 'identity': identity(checkpoint),
             'all_parameters_finite': True, 'all_gradient_norms_finite': True,
             'device': str(updated.model.device), 'dtype': str(updated.model.dtype)}
    return updated, proof


def main():
    # GPU workers must not survive an abruptly terminated owning application.
    if sys.platform.startswith('linux'):
        import ctypes
        import signal
        parent = os.getppid()
        if ctypes.CDLL(None).prctl(1, signal.SIGTERM) != 0:
            raise RuntimeError('Could not bind native worker lifetime to its owner')
        if os.getppid() != parent:
            raise SystemExit(1)
    pipeline = None
    for line in sys.stdin:
        try:
            request = json.loads(line)
            method, args = request['method'], request['arguments']
            with contextlib.redirect_stdout(sys.stderr):
                if method == 'load':
                    import torch
                    from chronos import Chronos2Pipeline
                    from transformers import set_seed
                    set_seed(args['seed'])
                    if identity(args['model_dir']) != args['expected_identity']:
                        raise ValueError('Model bytes changed before native loading')
                    pipeline = Chronos2Pipeline.from_pretrained(args['model_dir'], device_map=args['device'],
                        local_files_only=True, torch_dtype=torch.float32)
                    result = {'identity': identity(args['model_dir']), 'native_pipeline_sha256': hashlib.sha256(
                        Path(inspect.getfile(Chronos2Pipeline)).read_bytes()).hexdigest(),
                        'versions': {n: importlib.metadata.version(n) for n in ['torch','transformers','chronos-forecasting']},
                        'device': str(pipeline.model.device), 'parameter_count': sum(p.numel() for p in pipeline.model.parameters())}
                elif pipeline is None:
                    raise ValueError('Load a local model before native operations')
                elif method == 'predict':
                    import torch
                    with torch.inference_mode():
                        quantiles, means = pipeline.predict_quantiles(tensor_inputs(args['inputs']),
                            prediction_length=args['horizon'], quantile_levels=args['quantiles'],
                            cross_learning=False, batch_size=64)
                    result = {'quantiles': [q.detach().cpu().tolist() for q in quantiles],
                              'mean': [m.detach().cpu().tolist() for m in means], 'point_statistic': 'median',
                              'cross_learning': False}
                elif method == 'train':
                    pipeline, result = train(pipeline, args)
                else:
                    raise ValueError('Unknown native operation')
            reply = {'ok': True, 'result': result}
        except Exception as error:
            reply = {'ok': False, 'error': {'type': type(error).__name__, 'message': str(error)}}
        print(json.dumps(reply, allow_nan=False), flush=True)


if __name__ == '__main__':
    main()
