"""A tiny extension for test_extensions.py: one route and two pages."""

from pathlib import Path

from fastapi import APIRouter

from backend.extensions import OPERATORS, SIGNED_IN, Extension, Mount

HERE = Path(__file__).parent

router = APIRouter(prefix="/api/dummy")


@router.get("/ping")
def ping() -> dict:
    return {"pong": True}


def _step(db, local, dry_run):
    return {"step": "dummy", "dry_run": dry_run}


def extension() -> Extension:
    return Extension(
        name="dummy",
        routers=[router],
        mounts=[
            Mount(id="ops", label="Dummy operators", path="/dummy-ops", bundle=HERE / "ops.js",
                  section="account", audience=OPERATORS, assets={"extra.js": HERE / "extra.js"}),
            Mount(id="all", label="Dummy everyone", path="/dummy-all", bundle=HERE / "all.js",
                  section="workspace", audience=SIGNED_IN),
        ],
        jobs=[_step],
    )
