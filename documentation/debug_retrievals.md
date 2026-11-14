# Retaining TROPoe debug diagnostics

Enable diagnostics for queued or legacy group execution:

```bash
python GROUP_TROPoe.py --debug
python GROUP_TROPoe.py --debug --bands Ch1 25
python GROUP_TROPoe.py --debug --debug-dir /data/my_debug_archive
```

The default root is `RETRIEVAL_DEBUG_DIR` in `config.py`
(`/data/tropoe_debug/<site>`). Mount this directory on persistent storage when
running containers. `--debug-dir` only changes the archive location; use
`--debug` to enable diagnostics.

Each attempt gets its own directory:

`<root>/<requested case YYYYMMDDHHMM>/<Ch1 or Ch2_Bn>/<UTC timestamp>_<unique suffix>/`

The unique suffix prevents collisions even for concurrent runs or repeated
attempts of the same case and band. Nothing automatically deletes these folders.

| Path inside attempt | Contents |
| --- | --- |
| `vip.txt` | VIP used for this attempt |
| `vip.npy` | TROPoe's debug VIP snapshot |
| `work/` | Debug matrices and LBLRTM working files |
| `output/` | Retrieval NetCDF and debug iteration-history pickle |
| `run.json` | Command, case and rounded retrieval times, status and published files |

With a compatible TROPoe version, debug matrices include the Jacobian (`Kij`),
prior and observation covariance information, gain, posterior covariance,
averaging kernel, state vectors, and forward-calculated spectra. The exact files
depend on the solver version and how far the retrieval progresses.

Successful runs atomically copy their NetCDF outputs into the normal shared
retrieval directory so existing cataloging continues to work. The archived
original remains in the attempt folder. Existing shared files are preserved
unless the VIP's clobber setting is enabled. Failed runs keep their diagnostic
files but do not publish their partial NetCDF outputs. A forcibly killed process
may leave `run.json` showing `running`; files already written are still retained.

Group execution still skips completed retrievals. Debug mode does not request
reruns of completed cases. To deliberately rerun one completed retrieval:

```bash
python SINGLE_TROPoe.py 202211120529 --channel 2 --band 25 --debug --clobber
```

The single-case launcher uses the same archive layout and also accepts
`--debug-dir`. Launch from the usual directory containing `TROPoe.py`, as for
normal execution. Debug mode can consume substantial storage because working
files and matrices are retained, and some solver error paths can prompt for
interactive input. Standard solver console output remains visible in the terminal.
