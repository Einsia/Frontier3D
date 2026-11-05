# Execution boundary

Generated Python is untrusted. Default candidate execution uses Docker with
network disabled, a read-only root filesystem, input/output mounts, and resource
limits. Use a dedicated worker host. The local runtime executes with host
permissions and is intended only for trusted fixtures.

Generation and judging need network access to configured model services.
Generation receives the task instruction, declared local assets and required
runtime interfaces. Organizer grading notes, reference-source URLs and notices
are retained in `harness/`, `solution/` or `attribution/`, outside candidate
mounts. L1/L2 input allowlists reject attribution filenames; L3 reference
manifests contain only local image paths, identifiers, dimensions and hashes.
Use Docker generation (`GENERATOR_RUNTIME=docker`) to enforce the workspace
boundary. A model process launched locally can access files with host permissions;
prompt instructions and an input allowlist alone do not restrict that access.
Credentials stay in the user's .env or environment, outside public task
inputs and archived judge packets. Do not include credentials in bug reports.

Docker isolation is not a complete security proof. Report execution-isolation
issues privately to repository maintainers; no public contact has been
assigned in this release.
