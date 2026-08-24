# Knowledge Entry V1

**Contract version:** 1.0.0
**Task:** S3-01
**Status:** provider-neutral local candidate

## Entry boundary

`KnowledgeEntryGraph` is the only S3-01 start boundary. It accepts a typed explicit user intent, an
authenticated UI import action, or an approved administrator job. `READ_ONLY_QUERY` returns
`NOT_APPLICABLE` before task lookup and creates no Knowledge dispatch or physical call. The UI
model cannot carry an administrator approval object.

Every import binds request ID, task ID, trigger, intent, sorted source-artifact IDs, and the exact
tenant, project, user, roles, and permission version into a canonical candidate hash and stable
entry ID. The task repository denies missing, cross-scope, or stale-permission tasks without
returning task content.

## Task and source validation

An accepted task must:

- use task class and central budget class `K1`;
- carry the default and hard limits for the exact selected file count, while allowing an already
  valid active-limit elevation within those hard limits;
- carry a manifest-verified S2 context bundle;
- select between one and fifty unique artifacts already present in the TaskContext;
- use immutable source artifacts in the same tenant and project.

S3-01 does not inspect MIME, bytes, encoding, malware, or license metadata. Those checks begin at
S3-03. It also does not parse, OCR, normalize, index, review results, approve publication, or mutate
the knowledge base.

## Main and child topology

The graph sends explicit `RouteSignals` to the existing rules-first Main Graph. The verified route
contains exactly one `knowledge` professional assignment, is asynchronous, requires review, and
fixes Main LLM and tool calls at zero. `ChildContextFactory` then prepares one private Knowledge
context from the S2 TaskContext and requested source artifacts. Its tool list is the intersection of
the task and registered Knowledge allowlists, its side-effect class is mutating for scheduler
policy, and `user_delivery_allowed` remains false. The entry graph stops before child execution.

## Administrator jobs

An administrator job carries an internal `ApprovalStatus` produced by the S1-13 approval service.
The status must be approved and contain a grant whose approval ID, scope, task, policy, and candidate
hash match the current unexpired `KNOWLEDGE` candidate. The candidate action is
`knowledge.import.start`, target type is `knowledge_import_request`, and target ID is the exact task
ID. A stale, cross-scope, differently hashed, or incomplete approval is denied.

## UI route

`POST /v1/knowledge/imports` is registered only when both identity and Knowledge entry runtimes are
injected. Middleware derives scope from the bearer identity and selected tenant/project headers.
The versioned route policy must map the exact method and path to `knowledge:import:start`; otherwise
the request is denied before the handler. HTTP 202 exposes only entry ID, task ID, status,
asynchronous flag, review requirement, and typed next action. Internal contexts and source content
are never serialized to the UI.
