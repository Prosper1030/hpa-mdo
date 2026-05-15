# Phase 3 CFD Tool Installation Log

- started_at: 2026-05-15T02:04:40Z
- cwd: /Volumes/Samsung SSD/hpa-mdo
- policy: no sudo; open-source tooling only; Homebrew cask preferred before source build.

## Source Check

- OpenFOAM Foundation macOS route currently points users to Multipass/Ubuntu packages.
- The native macOS Homebrew route selected here is gerlero/openfoam/openfoam, which packages OpenFOAM.app for macOS and exposes an `openfoam` command.

## Commands

```text
$ brew tap gerlero/openfoam
==> Auto-updating Homebrew...
Adjust how often this is run with `$HOMEBREW_AUTO_UPDATE_SECS` or disable with
`$HOMEBREW_NO_AUTO_UPDATE=1`. Hide these hints with `$HOMEBREW_NO_ENV_HINTS=1` (see `man brew`).
==> Auto-updated Homebrew!
Updated 4 taps (steipete/tap, jlcodes99/cockpit-tools, homebrew/core and homebrew/cask).
==> New Formulae
arf: Modern R console with syntax highlighting and fuzzy search
backplane-cli: CLI for interacting with the OpenShift Backplane API
cargo-insta: Snapshot testing CLI for Rust
fallow: Codebase intelligence for TypeScript and JavaScript
gascity: Orchestration-builder SDK for multi-agent coding workflows
hexapoda: Colorful modal hex editor
mado: Fast Markdown linter written in Rust
nettle@3: Low-level cryptographic library
osdctl: CLI tool for managed OpenShift clusters
tinyice: Modern, all-in-one Icecast-compatible audio/video streaming server
vcfanno: Annotate a VCF with other VCFs/BEDs/tabixed files
==> New Casks
amore: App distribution platform with Sparkle, code signing, and notarization
github-copilot-app: Native client for GitHub Copilot
input0: Voice input tool with AI transcription
notion-cli: Command-line interface for Notion
openwork: Unofficial desktop GUI for OpenCode
runtimeviewer: Inspect Objective-C and Swift runtime interfaces
shichizip: 7-Zip derivative GUI
sshfs-mac: Network filesystem client to connect to SSH servers
blackbar

You have 66 outdated formulae and 2 outdated casks installed.

==> Tapping gerlero/openfoam
Cloning into '/opt/homebrew/Library/Taps/gerlero/homebrew-openfoam'...
Tapped 10 casks and 3 formulae (32 files, 302.7KB).

$ brew install --no-quarantine gerlero/openfoam/openfoam
Error: Calling the `--[no-]quarantine` switch is disabled! There is no replacement.
```

- finished_at: 2026-05-15T02:04:51Z

## Retry Without Deprecated Homebrew Quarantine Flag

```text
$ brew install gerlero/openfoam/openfoam
==> Fetching downloads for: gerlero/openfoam/openfoam
✔︎ Cask openfoam (2.1.3)
==> Installing Cask openfoam
==> Moving App 'OpenFOAM-v2512.app' to '/Applications/OpenFOAM-v2512.app'
==> Linking Binary 'openfoam' to '/opt/homebrew/bin/openfoam2512'
==> Linking Binary 'openfoam' to '/opt/homebrew/bin/openfoam'
🍺  openfoam was successfully installed!
```

- retry_finished_at: 2026-05-15T02:07:42Z
