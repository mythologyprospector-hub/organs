# Organs Integration Contract

This is a universal project-seed reference for machines that provide **Organs** as shared runtime infrastructure.

Organs is infrastructure external to the project. A project does not own Organs, redefine its contracts, or copy its implementation into the project merely to obtain a shared capability.

## Shared-world principle

Organs is the common runtime plumbing for the owner's project world. Every project should account for Organs when considering its operating environment and architecture. This does **not** mean every project must use every organ, that every feature must make a runtime call, or that every repository must be tightly coupled to Organs. Projects may remain independent and user-facing experiences may be standalone. Organs is available when its capabilities are useful; integration should be deliberate, contract-based, and proportionate to a real need.

When starting or materially redesigning work, inspect the current Organs repository and the other relevant project repositories before deciding whether to reuse a capability, establish a bridge, keep the project independent, or propose a shared improvement. Do not assume a capability exists just because it would be convenient.

## Rule

**When a project needs a capability Organs provides, use Organs through its published interface instead of creating a competing project-local version.**

A project remains responsible for its own domain logic, domain data, architecture, and project-specific contracts.

Organs is shared machine infrastructure. A project must not modify the Organs installation, its shared configuration, or another project's Organs integration as an incidental part of project work. Changes to shared infrastructure require explicit authorization and should be treated as a separate system-level change.

## Discovery

Organs **Registry** is the discovery root.

Services that participate in Organs should register themselves and discover peer services through Registry rather than hardcoding peer addresses when Registry discovery is appropriate.

Do not assume service addresses or ports from this seed. The installed Organs configuration and Registry are authoritative.

For each Organs dependency, make clear whether that capability is required or optional. Do not silently replace an unavailable shared capability with a competing project-local implementation merely to hide an infrastructure failure.

## Communications / BUS

Organs **Communications** provides the shared event BUS.

Use it when components need shared inter-service event transport, pub/sub behavior, or BUS dispatch. Do not create another project-local event bus solely because the project needs ordinary service-to-service events.

The BUS transports events; it does not establish their meaning or truth.

## Memory

Organs **Memory** provides runtime memory and state primitives.

It may be used for information that needs to persist across runtime activity or services when its capabilities fit the need.

Organs Memory is **not automatically the project's domain database, source of truth, epistemic authority, or canonical project documentation**. Project-specific durable truth belongs in the appropriate project-controlled storage and documents.

## Telemetry

Organs **Telemetry** records operational activity and provides operational history/querying.

Use it for runtime observations such as what happened, where, when, duration, status, and correlation. Do not treat telemetry by itself as proof that a domain claim is true.

## Service boundary

A service participating in Organs should follow the shared service conventions exposed by Organs, including:

- `GET /health` for health status;
- `GET /info` for identity, version, capabilities, and API information;
- the shared error envelope;
- Registry registration and heartbeat;
- service discovery through Registry where appropriate;
- explicit, documented capabilities.

Use the actual installed Organs implementation as the source of truth for current API details.

## Safety and agency

Organs includes bounded execution and safety/approval mechanisms. Project services must not bypass those mechanisms simply to make implementation easier.

In particular, do not silently turn an infrastructure convenience into autonomous authority. Consequential actions should retain the human-approval boundaries defined by the installed Organs contracts.

## What the seed does not prescribe

This document does **not** require every project to use every Organs organ.

It does not prescribe:

- a project architecture;
- a project programming language;
- a particular database;
- a particular service decomposition;
- project-specific API paths;
- project-specific domain semantics;
- a particular deployment topology.

The rule is simply to recognize Organs as shared machine infrastructure and reuse its capabilities when they fit the project's needs.

## Source of truth

This file is a bootstrap contract, not a copy of the Organs implementation.

Before integrating with Organs, inspect the installed/current Organs repository and use its current published contracts. Never invent an endpoint, port, capability, or behavior from memory.

Do not place environment-specific endpoints, credentials, tokens, or other machine secrets into the project seed or source-controlled project files merely to make an Organs integration convenient.
