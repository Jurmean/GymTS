"""Native classic data loader, with future targets withheld from the public source."""
from gymts.contracts import digest
from gymts_timeseries.sources import publish_snapshot
from .runtime import TimeCopilotRuntime


def prepare_airpassengers(gym, implementation, *, history=120, horizon=12):
    native = TimeCopilotRuntime(implementation, timeout_seconds=180).invoke({"mode": "dataset"})
    if type(history) is not int or type(horizon) is not int or history < 48 or horizon < 1 or history + horizon > len(native["values"]):
        raise ValueError("AirPassengers split must provide >=48 history observations and an existing positive future horizon")
    recipe = {key: value for key, value in native.items() if key != "values"}
    recipe.update(history=history, horizon=horizon,
                  split_semantics="public prefix [0,history); private evaluation future [history,history+horizon)")
    token = digest(recipe).removeprefix("sha256:")
    sample = {"sample_token": token, "series": [{"name": "passengers", "values": native["values"][:history]}],
        "context": {"start": native["start"], "freq": native["freq"], "seasonality": native["seasonality"], "horizon": horizon},
        "annotations": {"dataset": "AirPassengers", "history_length": history}}
    source = publish_snapshot(gym, [sample], dataset_revision=digest(recipe))
    private = {"forecast": native["values"][history:history+horizon], "recipe": recipe}
    private_ref = gym.artifacts.save_json(private, "gymts.json/1")
    return {**source, "private_ref": private_ref, "recipe": recipe}
