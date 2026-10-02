# Retrieval catalog

Run from the script directory:

```bash
python catalog_retrievals.py --bands 1 3 13 14 15 16 17
```

Defaults read `RETRIEVAL_DIR/GROUP_NAME`, `CLOUD_SCREEN_MANIFEST`, and
`CLOUD_SCREEN_CATEGORY` from `config.py`. Expected retrievals include Ch1 and
every requested Ch2 band (default: bands 1 through 18). Set `--no-ch1` for Ch2 only.

```bash
python catalog_retrievals.py --manifest /data/cloud_screening/sgp/manifest_reclassified_7_0p3.csv --bands 17 --no-ch1
python catalog_retrievals.py --retrieval-dir /data/tropoe/sgp --inventory-only
```

The scan is recursive and recognizes `tropoeOutput_Ch1.*` and
`tropoeOutput_Ch2_B<number>.*` NetCDF/CDF files. Channel/band identity comes from
these names; actual profile times come from decoded NetCDF time or ARM
base_time/time_offset. Every time record is cataloged, not only the first.
Run against a finished or paused batch for a stable snapshot.

Outputs under `<retrieval-dir>/catalog` (override with `--output-dir`):

- `files.csv`: paths, channel/band, size, modification time, profile counts and read errors.
- `profiles.csv`: actual times, profile indices, valid level counts and profile errors.
- `cases.csv`: each selected manifest case × requested configuration, matching file,
  profile index, time offset and duplicate count.
- `pending.csv`: missing/invalid matches and invalid target times.
- `summary.json`: status counts, scan settings and completion definition.

Each invocation rebuilds these reports from disk; it does not modify retrievals,
run TROPoe, or download inputs. `GROUP_TROPoe.py` reads `catalog/files.csv` once
when it starts and skips a rounded quarter-hour output only when that file has
at least one usable profile. Regenerate the catalog before restarting a batch;
the running process will not see newly completed files in its existing snapshot.
Repeated runs replace the catalog reports. Use a separate output directory to
preserve a snapshot. No manifest is required for an inventory-only scan.

A `complete` match has finite T and q at all levels, at least two levels,
a finite increasing height grid and a profile time within 60 seconds of the
manifest `retrieval_time`. Adjust with `--tolerance-seconds`; use zero for exact
matching. `duplicate` means multiple usable profiles match; inspect them before
choosing one. The closest match is reported, with file/profile ordering breaking
ties. Partial profiles at the target time are `invalid_output`; no matching
readable profile is `missing`. Unreadable files remain in `files.csv` and cannot
establish completion. All diagnostic errors are retained for inspection.

Completion here is a structural availability check, **not convergence or
scientific QC certification**. The script does not validate prior/settings
identity, spectral definitions, fill values lacking NetCDF metadata, or accuracy.
Keep configurations with different priors/settings in separate output groups.
Do not blindly rerun `pending.csv` without checking unreadable files and time
matching: this script neither removes nor overwrites them.

`summary.json` includes `completed_by_band`, for example
`{"Ch1": 100, "Ch2_B17": 92}`. With a manifest, these are counts of unique
selected case IDs with a usable match (including duplicate matches, counted once).
Without a manifest, they count distinct usable profile timestamps per configuration
across the scanned files. `completed_by_band_basis` records which definition was
used. Requested configurations with no completed retrievals are included as zero.
