"""Download the public ReliaSoft example projects the BlockSim importer is
tested against into ``backend/tests/fixtures/external/blocksim/``.

The files are ReliaSoft's copyright, so they are *not* committed (that folder is
gitignored); ``backend/tests/test_rbd_import_blocksim.py`` runs its integration
tests only when they are present. They come from the Internet Archive's copies
of the example pages reliasoft.com used to publish.

Usage::

    python backend/scripts/fetch_rbd_import_fixtures.py          # the core set
    python backend/scripts/fetch_rbd_import_fixtures.py --all    # + every other example
"""

from __future__ import annotations

import argparse
import sys
import urllib.request
from pathlib import Path

DEST = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "external" / "blocksim"

# (Wayback timestamp, original URL). The ``id_`` suffix returns the raw bytes
# instead of the archive's HTML wrapper.
CORE = [
    ("20121023193114", "http://www.reliasoft.com/BlockSim/examples/rc1/blocksim_example1.rsrp"),
    ("20170819141136", "http://www.reliasoft.com:80/BlockSim/examples/rc1/blocksim_example1_V9.rsr9"),
    ("20171019093149", "http://www.reliasoft.com:80/BlockSim/examples/rc2/blocksim_example2_V9.rsr9"),
    ("20150407043619", "http://www.reliasoft.com/synthesis/examples/synthesis9_flight_instruments_simulation.rsr9"),
    ("20160404225646", "http://reliasoft.com/synthesis/examples/synthesis10_flight_instruments_simulation.rsgz10"),
    ("20200810115850", "https://www.reliasoft.com/images/examples/bs_rc1/blocksim_example1_V20.rsgz20"),
]

EXTRA = [
    ("20121023192857", "http://www.reliasoft.com/BlockSim/examples/rc2/blocksim_example2.rsrp"),
    ("20121023192658", "http://www.reliasoft.com/BlockSim/examples/rc3/blocksim_example3.rsrp"),
    ("20121023192800", "http://www.reliasoft.com/BlockSim/examples/rc4/blocksim_example4.rsrp"),
    ("20170925010724", "http://www.reliasoft.com:80/BlockSim/examples/rc4/blocksim_example4_V9.rsr9"),
    ("20121023192958", "http://www.reliasoft.com/BlockSim/examples/rc5/blocksim_example5.rsrp"),
    ("20121023192555", "http://www.reliasoft.com/BlockSim/examples/rc6/blocksim_example6.rsrp"),
    ("20200810105001", "https://www.reliasoft.com/images/examples/bs_ex4/BlockSim_Example4_EventAnalysis_V20.rsgz20"),
    ("20120610050427", "http://www.reliasoft.com/synthesis/examples/synthesis8_flight_instruments_simulation.rsrp"),
    ("20120610051025", "http://www.reliasoft.com/synthesis/examples/synthesis8_flight_instruments_analytical.rsrp"),
    ("20150406231526", "http://www.reliasoft.com/synthesis/examples/synthesis9_flight_instruments_analytical.rsr9"),
    ("20160404232718", "http://reliasoft.com/synthesis/examples/synthesis10_flight_instruments_analytical.rsgz10"),
    ("20120610050318", "http://www.reliasoft.com/synthesis/examples/synthesis8_fault_tree.rsrp"),
    ("20150406231517", "http://www.reliasoft.com/synthesis/examples/synthesis9_fault_tree.rsr9"),
    ("20160404231922", "http://reliasoft.com/synthesis/examples/synthesis10_fault_tree.rsgz10"),
]


def wayback_url(timestamp: str, url: str) -> str:
    return f"https://web.archive.org/web/{timestamp}id_/{url}"


def fetch(timestamp: str, url: str, force: bool = False) -> Path:
    name = url.rsplit("/", 1)[-1]
    target = DEST / name
    if target.exists() and not force:
        print(f"have  {name}")
        return target
    src = wayback_url(timestamp, url)
    print(f"fetch {name} <- {src}")
    req = urllib.request.Request(src, headers={"User-Agent": "reliafy-test-fixtures"})
    with urllib.request.urlopen(req, timeout=180) as resp:
        data = resp.read()
    tmp = target.with_suffix(target.suffix + ".part")
    tmp.write_bytes(data)
    tmp.replace(target)
    return target


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--all", action="store_true", help="also fetch the other BlockSim / Synthesis examples")
    ap.add_argument("--force", action="store_true", help="re-download files already present")
    args = ap.parse_args(argv)
    DEST.mkdir(parents=True, exist_ok=True)
    failed = []
    for ts, url in CORE + (EXTRA if args.all else []):
        try:
            fetch(ts, url, args.force)
        except Exception as exc:  # noqa: BLE001 - report and carry on
            print(f"  failed: {exc}", file=sys.stderr)
            failed.append(url)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
