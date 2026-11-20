"""Download CSV on the dataset page: GET /api/datasets/{id}/csv gives the
rows as saved (every row, not the preview), the measurements part on its own,
a file name from the dataset's name, and 404 for a dataset you can't read."""

import matplotlib

matplotlib.use("Agg")

import pandas as pd

from backend.services import datasets as ds_service
from backend.tests.test_dataset_measurements import _csv, _paste, _put_file, client  # noqa: F401 - client is a fixture
from backend.tests.test_joint_models import fleet


def test_the_csv_is_the_saved_rows_byte_for_byte(client):
    L, _ = fleet(n=30)
    ds = _paste(client, L, name="Pump lives")
    r = client.get(f"/api/datasets/{ds}/csv")
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("text/csv")
    assert 'filename="Pump lives.csv"' in r.headers["content-disposition"]
    saved = ds_service.get_dataset(client.db, ds)
    assert r.content == bytes(saved.data)
    back = pd.read_csv(pd.io.common.BytesIO(r.content))
    assert len(back) == len(L) > 8  # every row, not the page's preview
    pd.testing.assert_frame_equal(back, L.reset_index(drop=True), check_dtype=False)


def test_the_measurements_part_downloads_on_its_own(client):
    L, R = fleet(n=12)
    ds = _paste(client, L, name="Feed pumps")
    assert _put_file(client, f"/api/datasets/{ds}/measurements", R).status_code == 200
    r = client.get(f"/api/datasets/{ds}/csv?part=measurements")
    assert r.status_code == 200, r.text
    assert 'filename="Feed pumps measurements.csv"' in r.headers["content-disposition"]
    assert len(pd.read_csv(pd.io.common.BytesIO(r.content))) == len(R)
    # The life data is still the default.
    assert len(pd.read_csv(pd.io.common.BytesIO(client.get(f"/api/datasets/{ds}/csv").content))) == len(L)


def test_samples_download_and_unknown_ids_are_404(client):
    assert client.get("/api/datasets/sample-ds-pumps/csv").status_code == 200
    assert client.get("/api/datasets/nope/csv").status_code == 404
    assert client.get("/api/datasets/sample-ds-pumps/csv?part=other").status_code == 422


def test_file_names_drop_characters_a_file_cannot_hold():
    assert ds_service.csv_filename('A/B: "x"?') == "AB x.csv"
    assert ds_service.csv_filename("") == "dataset.csv"
    assert ds_service.csv_filename("Pumps", "measurements") == "Pumps measurements.csv"
