# Third-party dependencies and reference material

Impact Studio installs Enola CLI 0.4.26, published by enola-labs, as a local parser dependency under Apache License 2.0. Its package carries license/notice materials; preserve them when redistributing its binary. Upstream: https://github.com/enola-labs/enola — package: https://pypi.org/project/enola-cli/0.4.26/.

The adapter and contract matcher are independently implemented Python. ImpRec, RepoHelix, AxiomCode Graph and CodexQA were reviewed for design patterns; their source is not included. Archive license identifiers: ImpRec Apache-2.0; RepoHelix MIT; AxiomCode Graph FSL-1.1-Apache-2.0; CodexQA Apache-2.0; Enola Apache-2.0.

Framework/parser dependencies are installed from requirements rather than vendored into the source ZIP; their own license obligations continue to apply.
