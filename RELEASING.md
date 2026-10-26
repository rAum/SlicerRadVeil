# Building, testing and releasing SlicerRadVeil

## How the extension reaches users

```
 you: git tag v0.2.0 && git push --tags
        │
        ▼
 release.yml ── CI gate: unit tests + self-test inside Slicer Stable & Preview
        │        on Linux (the exact files the package ships) + real radveil
        ├── GitHub release with SlicerRadVeil-v0.2.0.zip (manual/offline install)
        └── fast-forwards the `release` branch to the tag
                 │
                 ▼
 Slicer factory (Kitware) builds `release` every night for Slicer Stable and
 Preview, uploads the packages ──► Extensions Manager on all platforms next day
```

The [Slicer/ExtensionsIndex](https://github.com/Slicer/ExtensionsIndex) entry
(`RadVeil.json`) uses `"scm_revision": "release"`, so only tagged releases are
shipped and no index pull request is needed per release. Work on `main` freely.

The radveil Python package itself is not bundled: the module installs
`REQUIREMENT` from `RadVeil/RadVeilLib/backend.py` from PyPI on first use.

## Workflows

| workflow | when | what |
|---|---|---|
| `ci.yml` | push, PR, manual, called by `release.yml` | unit tests (Linux/macOS/Windows × Python 3.9/3.12); packaging check; self-test of the packaged module in the latest Slicer Stable + Preview (Linux, mock backend); the published radveil wheel installed into Slicer Stable's Python and run on MRHead, with screenshots uploaded as the `screenshots` artifact. |
| `release.yml` | tag `v*` on `main` | CI gate, GitHub release with the module zip and the CHANGELOG section as notes, fast-forward `release`. Tags with a suffix (`v0.2.0-rc1`) make a GitHub pre-release only. |

Not set up yet: a nightly CI run, a weekly check for new radveil releases
(`radveil-watch`), and Dependabot for the actions.

Slicer is downloaded from download.slicer.org (latest Stable / latest Preview
for the runner's OS and architecture), checked against its published SHA-512
and cached by revision (`.github/actions/setup-slicer`). No Slicer build is
needed: this is a pure-Python extension.

## One-time setup

1. Create `github.com/rAum/SlicerRadVeil`, push `main`, and add the
   `3d-slicer-extension` topic (About → Topics; the index checklist asks for it).
2. **Settings → Actions → General → Workflow permissions:** "Read and write"
   and "Allow GitHub Actions to create and approve pull requests" (for the
   radveil bump PRs).
3. If `release` is a protected branch, allow GitHub Actions to push to it
   (or the release workflow cannot ship).
4. Real screenshot: download the `screenshots` artifact of a green CI run
   (*Real radveil on MRHead + screenshots* job), commit `RadVeil.png` as
   `Screenshots/RadVeil.png` and point `EXTENSION_SCREENSHOTURLS` in
   `CMakeLists.txt` to it. Check it looks right first: it is what the
   Extensions Manager shows.
5. Tag the first release (`v0.1.0`); this creates the `release` branch.
6. Submit to the index: fork Slicer/ExtensionsIndex, add `RadVeil.json` to
   `main` (Slicer Preview) **and** to the branch of the latest Stable (e.g.
   `5.10`), open the PRs and complete the new-extension checklist. New Stable
   branches are created from `main`, so later Stables inherit the entry.

### Optional: notify on radveil releases

Add to radveil's `release.yml`, after publishing to PyPI, with a fine-grained
token that has *Contents: read and write* on SlicerRadVeil stored as
`SLICER_RADVEIL_DISPATCH_TOKEN`:

```yaml
      - name: Tell SlicerRadVeil
        env:
          GH_TOKEN: ${{ secrets.SLICER_RADVEIL_DISPATCH_TOKEN }}
        run: gh api repos/rAum/SlicerRadVeil/dispatches -f event_type=radveil-released
```

This needs the `radveil-watch` workflow, which is not set up yet.

## Releasing

```bash
git checkout main && git pull
git tag v0.2.0 && git push origin v0.2.0
```

Then watch the *Release* run. The next day, check the extension's row on
[slicer.cdash.org](https://slicer.cdash.org/) and install it from the
Extensions Manager.

## When something breaks

- **Preview self-test fails**: Slicer's API changed. Fix on
  `main` and release. If the fix is incompatible with the current Stable,
  keep a branch for Stable (e.g. `5.10`) and point that ExtensionsIndex
  branch's `scm_revision` at it.
- **Real-radveil job fails**: a new radveil in range broke the module, or a
  wheel is missing for one platform. Users installing now get that version,
  so fix quickly or tighten `REQUIREMENT` and release.
- **A file works from source but not when installed**: it is missing from
  `RadVeil/CMakeLists.txt`; `tools/stage_module.py --check` (in CI) reports it.

## Running the checks locally

```bash
pip install numpy pytest pyflakes packaging
pytest tests/ && python tools/stage_module.py --check
# in Slicer, against the packaged file set:
python tools/stage_module.py /tmp/stage
tools/ci_run_selftest.sh /path/to/Slicer /tmp/stage/RadVeil /tmp/selftest.log
```
