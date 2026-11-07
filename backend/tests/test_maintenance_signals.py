"""Signal channels: snapshots, the spectrum worked out on arrival, watch bands and
levels as derived measurement points, and the same on the Mongo-backed stores."""

from datetime import datetime, timedelta, timezone

import mongomock
import numpy as np
import pytest

from backend.maintenance import signals
from backend.maintenance.series import MongoSeries
from backend.maintenance.service import PROJECTORS, Invalid, Maintenance
from backend.maintenance.signals import MongoSnapshots
from backend.maintenance.store import GraphStore, MongoEventLog

ORG = "user-sig"
FS = 3200.0
N = 8192


def _store(backend):
    if backend == "mongo":
        db = mongomock.MongoClient()["signals"]
        return GraphStore(":memory:", PROJECTORS, MongoEventLog(db), series=MongoSeries(db),
                          snapshots=MongoSnapshots(db))
    return GraphStore(":memory:", PROJECTORS)


def _wave(freq, amp, phase=0.0, n=N, noise=0.0, seed=1):
    t = np.arange(n) / FS
    x = amp * np.sin(2 * np.pi * freq * t + phase) + 0.37  # a sensor offset
    if noise:
        x = x + np.random.default_rng(seed).normal(0, noise, n)
    return x


def _when(hours_ago):
    return (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).isoformat()


@pytest.fixture(params=["sqlite", "mongo"])
def m(request):
    return Maintenance(_store(request.param), ORG)


@pytest.fixture
def pump(m):
    pos = m.create_position("Pool pump")
    ch = m.add_signal_channel(pos["id"], None, "Pump bearing", "g", quantity="acceleration", sample_rate=FS,
                              axes=["X", "Y", "Z"], rpm=2980, tag="pump.vib")
    return m, pos, ch


def test_a_known_tone_gives_the_right_peak_and_amplitude(pump):
    m, _, ch = pump
    out = m.add_signal_snapshot(_when(1), ch["id"], axes={"X": _wave(49.7, 0.5).tolist(), "Y": _wave(99.4, 0.2).tolist(),
                                                           "Z": _wave(300, 0.1).tolist()}, running=True)
    assert out["stored"] and out["bytes"] > 0
    snap = m.signal_snapshot(out["snapshot_id"], max_points=20000)
    spec = snap["spectrum"]
    f = np.array(spec["freqs"])
    for axis, hz, amp in (("X", 49.7, 0.5), ("Y", 99.4, 0.2), ("Z", 300, 0.1)):
        y = np.array(spec["amplitudes"][axis])
        assert abs(f[y.argmax()] - hz) <= 3200 / N          # the peak is at the tone
        assert y.max() == pytest.approx(amp, rel=0.16)       # Hann scalloping at most 1.4 dB
    # The offset (0.37) is not in the spectrum or the levels.
    assert spec["amplitudes"]["X"][0] < 0.01  # far below the 0.37 offset
    assert snap["levels"]["X"]["rms"] == pytest.approx(0.5 / np.sqrt(2), rel=0.01)
    assert snap["levels"]["X"]["peak"] == pytest.approx(0.5, rel=0.01)
    assert snap["levels"]["X"]["crest"] == pytest.approx(np.sqrt(2), rel=0.01)
    assert snap["levels"]["X"]["kurtosis"] == pytest.approx(1.5, rel=0.02)  # a sine's
    # A bin-centred tone reads exactly.
    df = FS / N
    _, amp = signals.spectrum_of(_wave(df * 128, 0.8), FS)
    assert amp.max() == pytest.approx(0.8, rel=1e-3) and int(amp.argmax()) == 128


def test_band_level_equals_the_analytic_value_for_a_tone(pump):
    m, _, ch = pump
    m.add_signal_snapshot(_when(2), ch["id"], axes={a: _wave(49.7, 0.5).tolist() for a in "XYZ"})
    band = m.add_signal_band(ch["id"], "1x speed", 45, 55, axis="X")
    assert band["history_written"] == 1
    # Between bins or on one: the band reads A / sqrt(2) either way.
    for hz in (50.0, 50.19, 49.7):
        m.add_signal_snapshot(_when(1 + hz / 1000), ch["id"], axes={a: _wave(hz, 0.5, 0.3).tolist() for a in "XYZ"})
    latest = m.s.series.latest(ORG, band["point_id"])
    assert latest["value"] == pytest.approx(0.5 / np.sqrt(2), rel=0.01)
    # A band that misses the tone reads ~0.
    other = m.add_signal_band(ch["id"], "High", 400, 800, axis="X")
    assert m.s.series.latest(ORG, other["point_id"])["value"] < 0.002
    # It is an ordinary condition point: view, alarm limits and trend work.
    view = m.point(band["point_id"])
    assert view["kind"] == "condition" and view["derived"]["rule"]["type"] == "band" and view["unit"] == "g"


def test_orders_follow_the_running_speed(pump):
    m, _, ch = pump
    m.add_signal_snapshot(_when(3), ch["id"], axes={a: _wave(49.0, 0.4).tolist() for a in "XYZ"}, rpm=2940)
    m.add_signal_snapshot(_when(2), ch["id"], axes={a: _wave(50.0, 0.4).tolist() for a in "XYZ"}, rpm=3000)
    band = m.add_signal_band(ch["id"], "1x", 0.9, 1.1, axis="Y", unit="orders")
    vals = [r["value"] for r in m.s.series.recent(ORG, band["point_id"], 10)]
    assert len(vals) == 2 and all(v == pytest.approx(0.4 / np.sqrt(2), rel=0.01) for v in vals)
    # A snapshot with no speed on a channel with none is skipped by an orders band, not guessed.
    m.update_signal_channel(ch["id"], rpm=None)
    out = m.add_signal_snapshot(_when(1), ch["id"], axes={a: _wave(50.0, 0.4).tolist() for a in "XYZ"})
    assert out["derived"] == []


def test_snapshots_are_idempotent_on_channel_and_time(pump):
    m, _, ch = pump
    t = _when(5)
    data = {a: _wave(50, 0.3).tolist() for a in "XYZ"}
    m.add_signal_band(ch["id"], "1x", 45, 55, axis="X")
    first = m.add_signal_snapshot(t, ch["id"], axes=data)
    again = m.add_signal_snapshot(t, ch["tag"] and None, tag="pump.vib", axes=data)
    assert first["stored"] and again["duplicate"] and not again["stored"]
    assert m.signal_channel(ch["id"])["snapshots"]["count"] == 1
    band = m.signal_channel(ch["id"])["bands"][0]
    assert len(band["series"]) == 1  # the repeat did not add a second value
    # Different time, same content: stored.
    assert m.add_signal_snapshot(_when(4), ch["id"], axes=data)["stored"]
    assert m.signal_channel(ch["id"])["snapshots"]["count"] == 2


def test_time_must_be_given_with_a_zone(pump):
    m, _, ch = pump
    data = {"X": _wave(50, 0.3).tolist()}
    for bad in (None, "", "2026-11-03T10:00:00", "2026-11-03", "yesterday"):
        with pytest.raises(Invalid):
            m.add_signal_snapshot(bad, ch["id"], axes=data)


def test_size_and_shape_limits_have_clear_errors(pump):
    m, _, ch = pump
    with pytest.raises(Invalid, match="at most|numbers"):
        m.add_signal_snapshot(_when(1), ch["id"], axes={a: [0.1] * 200_000 for a in "XYZ"})
    with pytest.raises(Invalid, match="same number"):
        m.add_signal_snapshot(_when(1), ch["id"], axes={"X": [0.1] * 100, "Y": [0.1] * 99})
    with pytest.raises(Invalid, match="finite"):
        m.add_signal_snapshot(_when(1), ch["id"], axes={"X": [0.1] * 99 + [float("nan")]})
    with pytest.raises(Invalid, match="axes are"):
        m.add_signal_snapshot(_when(1), ch["id"], axes={"Q": [0.1] * 100})
    with pytest.raises(Invalid, match="doesn't convert"):
        m.add_signal_snapshot(_when(1), ch["id"], axes={"X": [0.1] * 100}, unit="mm/s")
    assert m.signal_channel(ch["id"])["snapshots"]["count"] == 0


def test_a_device_spectrum_is_stored_as_sent_and_gives_bands(m):
    pos = m.create_position("Fan")
    ch = m.add_signal_channel(pos["id"], None, "Fan casing", "mm/s", tag="fan")
    df = 0.5
    amp = np.zeros(1000)
    amp[100] = 2.0  # 2 mm/s peak at 50 Hz
    out = m.add_signal_snapshot(_when(1), None, tag="fan", spectrum={"df": df, "amplitudes": amp.tolist(),
                                                                    "window": "rectangular"})
    assert out["source"] == "spectrum"
    band = m.add_signal_band(ch["id"], "1x", 45, 55)
    assert m.s.series.latest(ORG, band["point_id"])["value"] == pytest.approx(2.0 / np.sqrt(2))
    # RMS amplitudes are converted to peak; non-uniform line positions are kept.
    m.add_signal_snapshot(_when(2), ch["id"], spectrum={"freqs": [0, 10, 25, 50, 100], "amplitudes": [0, 1, 1, 2, 1],
                                                       "amplitude": "rms"})
    snap = m.signal_snapshot(signals.snapshot_id(ch["id"], int((datetime.now(timezone.utc) - timedelta(hours=2)).timestamp() * 1000)
                                                 ) if False else m.signal_snapshots(ch["id"])["snapshots"][0]["id"])
    assert snap["spectrum"]["freqs"] == [0, 10, 25, 50, 100]
    assert snap["spectrum"]["amplitudes"]["value"][3] == pytest.approx(2 * np.sqrt(2), rel=1e-5)
    with pytest.raises(Invalid, match="raw|samples"):
        m.signal_snapshot(snap["id"], raw=True)


def test_a_pressure_channel_works_with_scalar_values(m):
    pos = m.create_position("Pool pump")
    ch = m.add_signal_channel(pos["id"], None, "Discharge pressure", "kPa", quantity="pressure", tag="pump.p")
    level = m.add_signal_level(ch["id"], "Discharge pressure", "value", alarm_above=250)
    base = datetime.now(timezone.utc) - timedelta(hours=3)
    for i, v in enumerate((180, 190, 200)):
        out = m.add_signal_snapshot((base + timedelta(hours=i)).isoformat(), None, tag="pump.p", value=v)
        assert out["stored"] and out["source"] == "value"
    view = m.point(level["point_id"])
    assert view["reading"] == 200 and view["unit"] == "kPa" and view["status"] == "ok"
    assert m.signal_snapshot(m.signal_snapshots(ch["id"])["snapshots"][0]["id"])["levels"]["value"]["value"] == 180
    # Past the limit: an inspection opens, like any condition point.
    out = m.add_signal_snapshot(_when(0.1), None, tag="pump.p", value=260)
    assert out["derived"][0].get("work_order")


def test_band_alarms_open_an_inspection_and_levels_are_points(pump):
    m, _, ch = pump
    band = m.add_signal_band(ch["id"], "1x", 45, 55, axis="X", alarm_above=0.2)
    out = m.add_signal_snapshot(_when(1), ch["id"], axes={a: _wave(50, 0.5).tolist() for a in "XYZ"})
    assert out["derived"][0]["work_order"]["point"] == "1x"
    rms = m.add_signal_level(ch["id"], "Overall RMS", "rms", axis="Z")
    assert m.point(rms["point_id"])["reading"] == pytest.approx(0.5 / np.sqrt(2), rel=0.01)
    with pytest.raises(Invalid):
        m.record_reading(band["point_id"], 1)  # worked out, not typed
    with pytest.raises(Invalid, match="axis"):
        m.add_signal_band(ch["id"], "no axis", 1, 2)  # three axes: which?
    m.remove_signal_band(rms["point_id"])
    out = m.add_signal_snapshot(_when(0.5), ch["id"], axes={a: _wave(50, 0.5).tolist() for a in "XYZ"})
    assert [d["name"] for d in out["derived"]] == ["1x"]


def test_preview_and_decimation_keep_peaks(pump):
    m, _, ch = pump
    sid = m.add_signal_snapshot(_when(1), ch["id"], axes={"X": _wave(137.3, 0.5, n=N).tolist()})["snapshot_id"]
    thin = m.signal_snapshot(sid, "X", max_points=300)["spectrum"]
    assert thin["decimated"] and len(thin["freqs"]) <= 300
    assert max(thin["amplitudes"]["X"]) == pytest.approx(0.5, rel=0.16)
    zoom = m.signal_snapshot(sid, "X", 130, 145, max_points=300)["spectrum"]
    assert not zoom["decimated"] and min(zoom["freqs"]) >= 130 and max(zoom["freqs"]) <= 145
    prev = m.preview_signal_band(ch["id"], 130, 145, "X")
    assert len(prev["series"]) == 1 and prev["series"][0]["value"] == pytest.approx(0.5 / np.sqrt(2), rel=0.01)
    assert m.s.series.latest(ORG, ch["id"]) is None  # nothing saved


def test_replay_rebuilds_the_same_graph(pump):
    m, _, ch = pump
    m.add_signal_band(ch["id"], "1x", 45, 55, axis="X")
    m.update_signal_channel(ch["id"], rpm=3000, mount="DE bearing")
    before = m.s.snapshot(ORG)
    m.s.rebuild()
    assert m.s.snapshot(ORG) == before
    view = m.signal_channel(ch["id"])
    assert view["rpm"] == 3000 and view["bands"][0]["rule"]["axis"] == "X"
    m.retire_signal_channel(ch["id"], "moved")
    with pytest.raises(Invalid):
        m.add_signal_snapshot(_when(1), ch["id"], axes={"X": [0.1] * 100})


# ---- slice 2: editable bands, warning levels, storage, speed tag ---------------------------------


def _shot(m, ch, hours_ago, freq=50, amp=0.5, **kw):
    return m.add_signal_snapshot(_when(hours_ago), ch["id"], axes={"X": _wave(freq, amp).tolist()}, **kw)


def test_a_new_range_makes_a_new_version_and_keeps_history(m):
    pos = m.create_position("Fan")
    ch = m.add_signal_channel(pos["id"], None, "Casing", "g", sample_rate=FS, axes=["X"], rpm=3000)
    _shot(m, ch, 3, 50)
    _shot(m, ch, 2, 50)
    band = m.add_signal_band(ch["id"], "1x", 45, 55, axis="X")
    old_id = band["point_id"]
    assert band["history_written"] == 2
    out = m.update_signal_band(old_id, low=90, high=110)
    assert out["new_version"] and out["point_id"] != old_id
    # the old version is retired and its recorded values untouched
    assert m.s.node(ORG, old_id)["retired"] and m.s.series.latest(ORG, old_id)["value"] > 0.3
    _shot(m, ch, 1, 100, 0.2)
    view = m.signal_channel(ch["id"])
    assert len(view["bands"]) == 1  # one band, not two
    b = view["bands"][0]
    assert b["point_id"] == out["point_id"] and len(b["series"]) == 3
    assert b["series"][0]["value"] == pytest.approx(0.5 / np.sqrt(2), rel=0.02)  # as measured then
    assert b["series"][2]["value"] == pytest.approx(0.2 / np.sqrt(2), rel=0.02)
    assert len(b["versions"]) == 2 and len(b["changes"]) == 1 and b["changes"][0]["t"]
    # a second edit chains on
    m.update_signal_band(out["point_id"], name="2x", high=120)
    again = m.signal_channel(ch["id"])["bands"][0]
    assert again["name"] == "2x" and len(again["versions"]) == 3 and len(again["series"]) == 3
    # replay gives the same graph and the same view
    before, shown = m.s.snapshot(ORG), m.signal_channel(ch["id"])["bands"]
    m.s.rebuild()
    assert m.s.snapshot(ORG) == before and m.signal_channel(ch["id"])["bands"] == shown


def test_name_and_limits_change_in_place(pump):
    m, _, ch = pump
    band = m.add_signal_band(ch["id"], "1x", 45, 55, axis="X")
    out = m.update_signal_band(band["point_id"], name="Running speed", alarm_above=0.4, warn_above=0.3)
    assert not out["new_version"] and out["point_id"] == band["point_id"]
    b = out["band"]
    assert (b["name"], b["alarm_above"], b["warn_above"]) == ("Running speed", 0.4, 0.3)
    cleared = m.update_signal_band(band["point_id"], warn_above=None)["band"]
    assert cleared["warn_above"] is None and cleared["alarm_above"] == 0.4
    with pytest.raises(Invalid, match="warning must be below"):
        m.update_signal_band(band["point_id"], warn_above=0.5)
    typed = m.add_point(m.create_position("x")["id"], "Hours")
    with pytest.raises(Invalid, match="isn't a band"):
        m.update_signal_band(typed.get("id") or typed["point_id"])
    before = m.s.snapshot(ORG)
    m.s.rebuild()
    assert m.s.snapshot(ORG) == before


def test_an_unchanged_range_makes_no_version_and_a_busy_band_is_refused(pump):
    m, _, ch = pump
    band = m.add_signal_band(ch["id"], "1x", 45, 55, axis="X", alarm_above=0.2)
    assert not m.update_signal_band(band["point_id"], low=45, high=55)["new_version"]
    m.add_signal_snapshot(_when(1), ch["id"], axes={"X": _wave(50, 0.5).tolist()})  # opens an alarm work order
    with pytest.raises(Invalid, match="open alarm work order"):
        m.update_signal_band(band["point_id"], low=40)
    assert len(m.signal_channel(ch["id"])["bands"]) == 1  # nothing half-made


def test_warning_levels_on_new_bands_and_levels(pump):
    m, _, ch = pump
    b = m.add_signal_band(ch["id"], "1x", 45, 55, axis="X", alarm_above=0.4, warn_above=0.25)["band"]
    assert b["warn_above"] == 0.25
    lv = m.add_signal_level(ch["id"], "RMS", "rms", axis="X", warn_above=0.1)["band"]
    assert lv["warn_above"] == 0.1 and lv["alarm_above"] is None
    with pytest.raises(Invalid):
        m.add_signal_band(ch["id"], "bad", 1, 2, axis="X", alarm_above=0.4, warn_above=0.5)


def test_storage_counts_and_warns_softly_and_deletes_nothing(pump):
    m, _, ch = pump
    assert m.signal_storage()["snapshots"] == 0 and m.signal_storage()["cap_mb"] is None
    _shot(m, ch, 2)
    _shot(m, ch, 1)
    st = m.signal_storage()
    assert st["snapshots"] == 2 and st["bytes"] > 0 and not st["over_cap"] and "warning" not in st
    capped = m.set_signal_storage_cap(1)
    assert capped["cap_mb"] == 1 and not capped["over_cap"]
    for h in range(3, 40):  # noise does not compress: about 60 kB each
        m.add_signal_snapshot(_when(h + 0.5), ch["id"], axes={"X": _wave(50, 0.5, noise=1.0, seed=h).tolist()})
    over = m.signal_storage()
    assert over["over_cap"] and "Nothing is deleted" in over["warning"] and over["snapshots"] == 39
    assert m.s.snapshots.stats(ORG, ch["id"])["count"] == 39
    assert m.set_signal_storage_cap(None)["cap_mb"] is None
    before = m.s.snapshot(ORG)
    m.s.rebuild()
    assert m.s.snapshot(ORG) == before


def test_speed_comes_from_a_tagged_speed_channel(m):
    pos = m.create_position("Motor")
    vib = m.add_signal_channel(pos["id"], None, "Vib", "g", sample_rate=FS, axes=["X"], rpm=1500)
    spd = m.add_signal_channel(pos["id"], None, "Speed", "rpm")
    bad = m.add_signal_channel(pos["id"], None, "Temp", "C")
    with pytest.raises(Invalid, match="rpm"):
        m.update_signal_channel(vib["id"], speed_channel_id=bad["id"])
    with pytest.raises(Invalid, match="itself"):
        m.update_signal_channel(vib["id"], speed_channel_id=vib["id"])
    assert m.update_signal_channel(vib["id"], speed_channel_id=spd["id"])["speed_channel_id"] == spd["id"]
    for hours, rpm in ((2.0, 1470.0), (1.0, 1490.0)):
        m.add_signal_snapshot(_when(hours), spd["id"], value=rpm)
    band = m.add_signal_band(vib["id"], "1x", 0.9, 1.1, axis="X", unit="orders")
    out = _shot(m, vib, 1.1, 24.8, 0.5)  # 1490 rpm = 24.83 Hz; nearest reading is the 1 h one (6 min away)
    snap = m.signal_snapshot(out["snapshot_id"])
    assert snap["rpm"] == 1490.0 and snap["speed_from"]["channel_id"] == spd["id"]
    assert out["derived"][0]["value"] == pytest.approx(0.5 / np.sqrt(2), rel=0.03)
    # an explicit rpm wins; no reading nearby falls back to the channel's rpm with a note
    assert m.signal_snapshot(_shot(m, vib, 1.2, rpm=1000)["snapshot_id"])["rpm"] == 1000
    far = _shot(m, vib, 30)
    assert m.signal_snapshot(far["snapshot_id"])["rpm"] == 1500 and any("speed" in n for n in far["notes"])
    assert band["point_id"]
    m.update_signal_channel(vib["id"], speed_channel_id="")
    assert m.signal_channel(vib["id"])["speed_channel_id"] is None
    before = m.s.snapshot(ORG)
    m.s.rebuild()
    assert m.s.snapshot(ORG) == before


def test_an_items_channel_says_where_the_item_is_fitted(m):
    pos = m.create_position("Feed pump")
    item_id = m.create_item("Pump P-7", serial="7")["id"]
    m.fit(pos["id"], item_id=item_id)
    ch = m.add_signal_channel(None, item_id, "Pump DE", "g", sample_rate=FS)
    head = m.signal_channels(item_id=item_id)["channels"][0]
    assert head["id"] == ch["id"] and head["position"] is None
    assert head["item"] == {"id": item_id, "name": "Pump P-7", "fitted_to": {"id": pos["id"], "name": "Feed pump"}}
    loose = m.create_item("Spare pump")
    m.add_signal_channel(None, loose["id"], "Spare DE", "g", sample_rate=FS)
    assert m.signal_channels(item_id=loose["id"])["channels"][0]["item"]["fitted_to"] is None
