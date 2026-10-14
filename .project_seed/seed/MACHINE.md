# Permanent Machine Context

This file records stable operational facts used across projects.

These facts are **machine context, not project architecture**.

## Primary development machine

Hostname:

```text
mythos1
```

Common human name:

```text
Bucky
```

Primary local project root:

```text
~/projects
```

Every project repository is normally cloned as:

```text
~/projects/<repo-name>
```

Do not substitute:

```text
~/<repo-name>
```

unless the actual machine state explicitly says otherwise.

## Organs

When Organs is installed on the machine, its installation/runtime location is:

```text
/srv/organs
```

This is not the normal Git clone location.

## Git routine

The human does not reliably remember routine `git switch` / `git pull` sequences.

When asking the human to update a normal main-branch checkout, provide the complete sequence:

```bash
cd ~/projects/<repo-name>
git switch main
git pull --ff-only origin main
```

If a feature branch is intended, provide the exact branch command instead.

## Machine boundary

Do not infer additional filesystem paths, services, ports, devices, or configuration from this document.

If a machine detail matters and is not documented here, inspect the actual machine state.

Do not move project architecture into machine documentation merely because the architecture happens to run on this machine.
