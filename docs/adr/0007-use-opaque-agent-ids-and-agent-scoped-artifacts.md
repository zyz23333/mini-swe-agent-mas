# Use Opaque Agent IDs and Agent-Scoped Artifacts

MAS Agent IDs use the `mas-<random-hex>` shape as opaque durable identifiers and no longer encode root identity, parent identity, sibling order, or tree position. The Root Agent remains the top-level Parent Agent through which the External MAS CLI enters MAS governance, every CLI-created Root Agent is interactive, and artifacts are scoped to individual Agents rather than to runs or Root Agents. Root discovery uses workflow parent structure and workflow type rather than an `is_root` flag, interaction-mode flag, single global root, or separate root index.

**Considered Options**

- Keep path-encoded Agent IDs such as `mas-<root>-c001-c002` and derive artifact paths from the encoded root segment.
- Introduce a separate run identifier and keep artifacts grouped by run.
- Keep separate ordinary Root Agent and Interactive Root Agent modes for different CLI commands.
- Add root or interaction-mode flags to every Agent metadata record.
- Add a separate Root Agent index for CLI status and resume.
- Add a single global root Agent and hang all user-facing Root Agents underneath it.
- Make artifacts directly Agent-scoped and keep parent-child structure in MAS governance metadata instead of Agent ID strings or artifact paths.
- Route all External MAS CLI commands through an Interactive Root Agent, with one-shot commands such as `mini-mas spawn` submitting their initial command automatically.
- Use parentless Interactive Root Agent workflows as the discovery source for external status and resume.
- Preserve parent-local sibling order as Spawn Index metadata instead of encoding it in Agent IDs.

**Consequences**

Changing Agent ID shape no longer changes artifact grouping semantics. Child Agents do not need root identity or ancestor paths to write artifacts, while Direct Child Authority remains based on Parent Agent relationships rather than on ID prefixes. One-shot CLI commands still leave an Interactive Root Agent available as the parent authority context for later status, wait, continue, or close commands. Agent metadata stays limited to identity, optional Spawn Index, and artifact description instead of carrying query flags.
