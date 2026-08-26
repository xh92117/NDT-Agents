# Canonical Inspection Data V1

## Purpose

S5-06 defines the provider-neutral data boundary between source parsers, instrument adapters,
deterministic signal algorithms, AI-model inference, and S4 professional processing control. The
contract describes acquired evidence; it does not parse files, control hardware, invoke a tool or
model, publish knowledge, approve evidence, or form an inspection conclusion.

## Manifest boundary

`CanonicalInspectionDataset@1.0.0` binds one exact `TenantScope`, dataset identity, explicit data
origin, one registered six-method code, structure/component/area/point/location topology,
registered-dimensional coordinates, immutable source provenance, contiguous acquisition channels,
typed acquisition settings, instrument identity, calibration records, operator identity, and a
deterministic manifest hash.

Raw sample arrays are never embedded in the manifest. Each channel binds an immutable exact-scope
artifact, bounded byte offset and length, channel identity, sample count, Decimal sample rate, UTC
time origin, dimension, unit, encoding, and content hash. Channel indexes are zero-based,
contiguous, unique, and sorted. Artifact byte ranges may not exceed their immutable object or
overlap another channel range in the same artifact. V1 datasets use homogeneous sample count,
sample rate, dimension, unit, and time origin across channels so the narrower S4-04 source boundary
cannot understate a channel bound.

## Provenance and eligibility

The source record preserves the exact source name, media type, source hash, parser identity and
version, parser-configuration hash, detected and normalized encodings, confidence, and whether
normalization was lossless. Instrument provenance preserves device, model, serial, firmware, and
adapter identities. Every calibration preserves kind, version, status, UTC validity interval,
instrument identity, and immutable evidence. The operator record preserves exact identity,
identity version, organization, and sorted qualifications.

Structural validity and use eligibility are separate. Missing or inconsistent provenance,
cross-scope/mutable artifacts, unsupported method, invalid unit, channel/range failure, lossy
normalization, or a changed manifest hash blocks processing. Formal use additionally requires
production origin, at least one qualification, and every calibration to be valid, active, and to
cover acquisition time. Invalid evidence remains representable for review but cannot become
formal-use eligible.

## Serialization and S4 bridge

Serialization is canonical UTF-8 without BOM, sorted JSON keys, compact separators, exact Decimal
text, and no non-finite values. Parsing rejects malformed UTF-8, duplicate keys, unknown fields,
and hash changes. Non-ASCII filenames and metadata are preserved without replacement.

The S4-04 bridge projects the canonical manifest into `ProcessingSourceManifest@1.0.0` and compares
an existing S4 source and request parser version against that exact projection. It preserves the shared scope, dataset/source
hash, origin, method, structure/component/location, channel/sample bounds, primary signal
dimension/unit/rate, acquisition settings, instrument/calibration/operator, acquisition time, and
parser identity. Area, point, coordinates, per-channel artifact ranges, rich device metadata,
qualifications, and encoding provenance remain in the canonical manifest and are not fabricated in
the narrower S4 shape.

## Local evidence boundary

Deterministic fixtures exercise all six methods and perform no parser, provider, network, model,
instrument, device, approval, publication, or retry action. Authorized calibrated real-device data,
production parser validation, expert gold answers, immutable CI, and TG-05 remain separate gates.
