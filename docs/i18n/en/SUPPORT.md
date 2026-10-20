# Getting help

Start with the [README](README.md) and [documentation index](docs/README.md). See the [FAQ](docs/faq.md) for common questions, the [environment guide](docs/environment-adapters.md) for third-party data/services, and the [adapter guide](adapters/README.md) for new projects.

| Question | Entry point |
| --- | --- |
| Reproducible error | [Bug report](https://github.com/Jurmean/GymTS/issues/new?template=bug_report.yml) |
| Feature or public-interface proposal | [Feature request](https://github.com/Jurmean/GymTS/issues/new?template=feature_request.yml) |
| New dataset, task, model, toolset, or service | [Adapter request](https://github.com/Jurmean/GymTS/issues/new?template=adapter_request.yml) |
| Usage question or unclear documentation | [General Issue](https://github.com/Jurmean/GymTS/issues/new) |
| Suspected vulnerability or sensitive-data leak | [Security policy](SECURITY.md); do not disclose details publicly |
| Community conduct concern | [Code of conduct](CODE_OF_CONDUCT.md) |

Provide exact GymTS/adapter versions, Python/OS, explicitly enabled integrations, a minimal configuration, command, expected and actual behavior, and redacted error codes/logs. Preserve the original store for result-related issues; share only necessary Run IDs, event excerpts, and artifact hashes publicly. A Run ID is a local record identifier, not permission for maintainers to access your disk.

Do not upload an entire production CAS, reference answers, access tokens, complete service connection strings, or personal-data samples. First try `python3 -B examples/quickstart.py --root /tmp/gymts-support-demo` to check the basic chain, then isolate the adapter. Report native backend installation, account, or version issues upstream when appropriate; cross-link both reports to avoid duplicate investigation.

Support currently consists of asynchronous public collaboration in the repository. The project does not declare commercial support, a ticketing service, fixed response times, or availability guarantees, and GitHub Discussions activation has not been confirmed. Real localhost service validation in research acceptance reports is not a production deployment commitment.
