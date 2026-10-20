# Agent governance posture checklist

Use before tool selection. Vendor-neutral.

1. Inventory: which agents or automations exist (named and shadow)?
2. Owner: who can kill each one?
3. Spawn identity: how does it authenticate (human proxy vs workload identity)?
4. Scope: what systems can it read / write / create?
5. Secrets: where do credentials live, and what is the rotation story?
6. Evidence: what logs prove actions after the fact?
7. Blast radius: what is the worst safe failure mode?
8. Human gate: which actions require approval?
9. Cost / rate: how do we bound spend and loops?
10. Exit: how do we decommission without orphaned access?

Map answers to the ADR-0010 layers before buying an NHI or DSPM product.
