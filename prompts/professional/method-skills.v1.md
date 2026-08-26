# Method Skill Pack Prompt V1

Validate one S4-04 processing request and candidate against the selected versioned method Skill.
Preserve exact scope, source origin, method identity, metadata, calibration kind, input units,
processing parameters, observation families, limitations, safety notes, and all hashes.

Fail closed with typed issues when metadata is missing, applicability is unsupported, calibration
or units are incompatible, parameters are absent, the method changes, or an output observation is
unregistered. A successful candidate must contain at least one typed registered observation.

This boundary must execute no algorithm, instrument command, provider/model call, network call,
approval, publication, conclusion, or retry. It must not relabel simulated or laboratory evidence
as production. It must require independent review and must not claim standards compliance, expert
correctness, acceptance, or formal release.
