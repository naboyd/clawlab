# Maintainer archive (local only)

Paths listed in `MANIFEST.txt` were removed from the public clawlab tree. They live
here for lab maintainers who still need training benches, legacy PAM/nginx snippets,
DHCP sidecar deploy, or one-shot scrub scripts.

**Not installed by default.** Beta testers should use the scripts documented in
`docs/Troubleshooting scripts.md` and `docs/USER-GUIDE.md`.

## Restore a path into the repo checkout

From the repo root:

```bash
cp -R _archive/admin-access/alice admin-access/
cp -R _archive/dhcp-sidecar .
# …see MANIFEST.txt for full paths
```

Or re-run `bash admin-access/populate-maintainer-archive.sh` after pulling an older
commit that still contained these files.

## Regenerate this tree

```bash
bash admin-access/populate-maintainer-archive.sh
```

The `_archive/` directory (except this README and `MANIFEST.txt`) is gitignored.
