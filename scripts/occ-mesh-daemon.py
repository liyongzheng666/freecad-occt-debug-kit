#!/usr/bin/env python3
# =====================================================================
# occ-mesh-daemon — watch a debug session's assets/*.brep, mesh them with
# occ-debug-mesh, and APPEND `update` events that upgrade the viewer's
# placeholder bbox into a real triangle mesh.
#
# This is the M2-3 "A 独立守护进程 watch assets/" producer (see
# docs/occ-mesh-daemon-plan.md §3/§4/§7). It is fully decoupled from the
# debugged process: it never runs inside a frozen breakpoint, it only watches
# the shared <session>/ directory and shells out to the mesher CLI.
#
# WHAT IT DOES (plan §3/§4, slices S1 + S3):
#   - watch assets/**/*.brep
#   - associate each brep -> entity id via the `add` event that references it
#     (op=="add", asset.format=="occt-brep" -> take its `id`)
#   - mesh it: subprocess [$OCC_DEBUG_MESH_BIN, brep, <base>.mesh.json] w/ timeout
#   - sha256 the produced mesh.json (hashlib, 64 hex)                  (V7)
#   - flock(LOCK_EX) + atomic single-line APPEND of ONE `update` event with
#     run_id="<orig run>/mesh", self-managed monotonic seq, and
#     patch.asset = {format:"print-mesh", path, sha256}               (V1/N4)
#   - then APPEND one `defect` add per entry of <base>.defects.json,
#     stamping ref.entity_id (S3 / §4)
#   - idempotent: skip if mesh.json already exists OR id already in emitted set
#   - --with-uv: fold <base>.geom.json UV pcurves into patch.metadata.uv (P0b)
#
# FAILURE PATH (N6, plan §5): a partial mesh (partial=true) is still a success —
# we emit the update with whatever meshed + its defects. A process failure or
# timeout keeps the placeholder and emits a `note(level:"capture_failure")`
# instead of an update.
#
# DISCIPLINE: NEVER truncate events.ndjson — append only (plan §8).
#
# Standard library ONLY (no third-party deps; same stack as the Bridge).
#
#   Usage:
#     scripts/occ-mesh-daemon.py [--session DIR] [--interval 0.2] [--once] [--with-uv]
#
#   Defaults:
#     --session   $OCC_DEBUG_SESSION, else .occ-debug/sessions/dev
#     mesher bin  $OCC_DEBUG_MESH_BIN, else tools/occ-debug-mesh/build/occ-debug-mesh
# =====================================================================
import argparse
import fcntl
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

SCHEMA_VERSION = "1.0"
# plan §3 step 2b (V2 layer 2): hard kill a runaway mesher. Configurable via
# $OCC_DEBUG_MESH_TIMEOUT (seconds) or --timeout.
DEFAULT_TIMEOUT_S = float(os.environ.get("OCC_DEBUG_MESH_TIMEOUT", "30"))


def repo_root() -> Path:
    # scripts/occ-mesh-daemon.py -> repo root is the parent of scripts/.
    return Path(__file__).resolve().parent.parent


def default_mesher() -> str:
    env = os.environ.get("OCC_DEBUG_MESH_BIN")
    if env:
        return env
    return str(repo_root() / "tools" / "occ-debug-mesh" / "build" / "occ-debug-mesh")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fp:
        for chunk in iter(lambda: fp.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def brep_base(brep: Path) -> Path:
    """<base> = brep path with the trailing .brep removed.

    The mesher writes <base>.mesh.json / <base>.geom.json / <base>.defects.json.
    """
    return brep.with_suffix("")  # drops ".brep"


def asset_rel_path(assets_dir: Path, target: Path) -> str:
    """Path relative to <session>/assets/, no leading slash (schema asset.path)."""
    return target.relative_to(assets_dir).as_posix()


def uvpairs(flat):
    """Flat [u0,v0,u1,v1,…] -> [[u0,v0],[u1,v1],…] (geom sidecar pcurves)."""
    return [[flat[i], flat[i + 1]] for i in range(0, len(flat), 2)]


class Daemon:
    def __init__(self, session: Path, mesher: str, interval: float,
                 with_uv: bool = False, timeout: float = DEFAULT_TIMEOUT_S):
        self.session = session
        self.assets = session / "assets"
        self.events_path = session / "events.ndjson"
        self.mesher = mesher
        self.interval = interval
        self.with_uv = with_uv
        self.timeout = timeout

        # Incremental tail of events.ndjson: byte offset already consumed.
        self._offset = 0
        # brep asset.path (relative to assets/) -> entity id, from `add` events.
        self.brep2id = {}
        # session_id discovered from existing events (we must reuse it).
        self.session_id = None
        # Per-mesh-run monotonic seq, namespaced by our own run_id "<run>/mesh".
        self._seq_by_run = {}
        # entity ids we have already emitted an update for (idempotency).
        self.emitted = set()

    # ---- events.ndjson tail -> brep2id / session_id ---------------------
    def scan_events(self) -> None:
        if not self.events_path.exists():
            return
        size = self.events_path.stat().st_size
        if size < self._offset:
            # File shrank (shouldn't happen under append-only discipline, but be
            # safe): re-read from the start rather than read garbage.
            self._offset = 0
            self.brep2id.clear()
            self.session_id = None
        with self.events_path.open("r", encoding="utf-8") as fp:
            fp.seek(self._offset)
            for line in fp:
                if not line.endswith("\n"):
                    # Partial trailing line (writer mid-append): stop here and
                    # resume from this offset next tick. Do not advance past it.
                    break
                self._offset += len(line.encode("utf-8"))
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    ev = json.loads(stripped)
                except json.JSONDecodeError:
                    continue
                if self.session_id is None:
                    sid = ev.get("session_id")
                    if isinstance(sid, str) and sid:
                        self.session_id = sid
                run_id = ev.get("run_id")
                # Reconstruct OUR run namespace from events a prior daemon wrote,
                # so a restart stays monotonic (V1) and never re-emits an update
                # (idempotency, plan §8): track the seq high-water mark per
                # "<run>/mesh", and remember which entity ids already got an update.
                if isinstance(run_id, str) and run_id.endswith("/mesh"):
                    seq = ev.get("seq")
                    if isinstance(seq, int):
                        self._seq_by_run[run_id] = max(self._seq_by_run.get(run_id, 0), seq)
                    if ev.get("op") == "update" and isinstance(ev.get("id"), str):
                        self.emitted.add(ev["id"])
                if ev.get("op") != "add":
                    continue
                asset = ev.get("asset")
                ent_id = ev.get("id")
                if not isinstance(asset, dict) or not isinstance(ent_id, str):
                    continue
                if asset.get("format") != "occt-brep":
                    continue
                path = asset.get("path")
                if isinstance(path, str) and path:
                    self.brep2id[path] = {"id": ent_id, "run_id": run_id}

    # ---- meshing --------------------------------------------------------
    def mesh_one(self, brep: Path, info: dict) -> bool:
        """Mesh one brep, append its `update` + defects. Returns True if it emitted."""
        base = brep_base(brep)
        mesh_json = base.with_name(base.name + ".mesh.json")
        ent_id = info["id"]
        orig_run = info.get("run_id") or "run-0001"
        mesh_run = f"{orig_run}/mesh"  # plan §3/V1: independent run namespace
        rel_brep = asset_rel_path(self.assets, brep)

        # Idempotency: an update for this id is already in the log (this process
        # OR replayed from a prior daemon — see scan_events).
        if ent_id in self.emitted:
            return False
        if mesh_json.exists():
            # Mesh on disk but no update in the log: a prior daemon crashed
            # between writing the mesh and appending its update. Recover by
            # emitting from the existing mesh — do NOT re-run the mesher (§8).
            rel, sha, n_def = self._emit_from_mesh(mesh_run, ent_id, base, mesh_json)
            self._log_emit("recovered", ent_id, rel, sha, n_def)
            return True

        cmd = [self.mesher, str(brep), str(mesh_json)]
        try:
            proc = subprocess.run(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                timeout=self.timeout,
            )
        except subprocess.TimeoutExpired:
            # N6: process timeout -> keep the placeholder, emit a capture_failure
            # note (not an update). Mark emitted so we don't re-spawn every tick.
            self.append_note(mesh_run, ent_id, rel_brep, f"timeout after {self.timeout:g}s")
            self.emitted.add(ent_id)
            sys.stderr.write(f"[occ-mesh-daemon] timeout meshing {rel_brep}\n")
            return False
        except OSError as exc:
            self.append_note(mesh_run, ent_id, rel_brep, f"spawn failed: {exc}")
            self.emitted.add(ent_id)
            sys.stderr.write(f"[occ-mesh-daemon] spawn failed for {rel_brep}: {exc}\n")
            return False
        if proc.returncode != 0 or not mesh_json.exists():
            # N6: process failure -> keep placeholder, capture_failure note, no update.
            detail = self._tail_stderr(proc.stderr) or f"exit {proc.returncode}"
            self.append_note(mesh_run, ent_id, rel_brep, f"exit {proc.returncode}: {detail}")
            self.emitted.add(ent_id)
            sys.stderr.write(f"[occ-mesh-daemon] mesher failed (rc={proc.returncode}) for {rel_brep}\n")
            return False

        # Success. A partial mesh (partial=true, some failed_faces) is NOT a
        # failure: still emit the update with whatever meshed, plus defects (N6).
        rel, sha, n_def = self._emit_from_mesh(mesh_run, ent_id, base, mesh_json)
        self._log_emit("meshed", ent_id, rel, sha, n_def)
        return True

    def _emit_from_mesh(self, mesh_run: str, ent_id: str, base: Path, mesh_json: Path):
        """Emit the update (+ defects) for an already-produced mesh.json.

        Shared by the fresh-mesh path and the restart/crash-recovery path; both
        sha256 the on-disk bytes (V7) and append under the same "<run>/mesh" seq.
        """
        sha = sha256_file(mesh_json)
        rel = asset_rel_path(self.assets, mesh_json)
        uv = self.fold_uv(base) if self.with_uv else None
        self.append_update(mesh_run, ent_id, rel, sha, uv)
        n_def = self.append_defects(mesh_run, ent_id, base)
        self.emitted.add(ent_id)
        return rel, sha, n_def

    @staticmethod
    def _log_emit(verb: str, ent_id: str, rel: str, sha: str, n_def: int) -> None:
        extra = f", {n_def} defect(s)" if n_def else ""
        sys.stderr.write(f"[occ-mesh-daemon] {verb} {ent_id} -> {rel} sha256={sha[:12]}…{extra}\n")

    @staticmethod
    def _tail_stderr(data: bytes) -> str:
        if not data:
            return ""
        lines = [ln for ln in data.decode("utf-8", "replace").strip().splitlines() if ln.strip()]
        return lines[-1] if lines else ""

    # ---- event append (flock + single atomic line) ---------------------
    def _emit(self, run_id: str, op: str, **fields) -> None:
        """Append one event under our own run namespace, monotonic seq (V1).

        Append-only + flock(LOCK_EX): protects against byte-interleaving when
        the fake-session / occdbg producer and this daemon write concurrently
        (plan §4 / risk N4). One write() of the whole line. An entity's update
        and its defects share the same "<run>/mesh" run_id and a continuous seq,
        so the reducer's lastSeqByRun stays monotonic.
        """
        seq = self._seq_by_run.get(run_id, 0) + 1
        self._seq_by_run[run_id] = seq
        event = {
            "schema_version": SCHEMA_VERSION,
            "session_id": self.session_id or "unknown",
            "run_id": run_id,
            "seq": seq,
            "timestamp_ns": time.time_ns(),
            "op": op,
            **fields,
        }
        line = json.dumps(event, ensure_ascii=False) + "\n"
        with self.events_path.open("a", encoding="utf-8") as fp:
            fcntl.flock(fp.fileno(), fcntl.LOCK_EX)
            try:
                fp.write(line)
                fp.flush()
                os.fsync(fp.fileno())
            finally:
                fcntl.flock(fp.fileno(), fcntl.LOCK_UN)

    def append_update(self, mesh_run: str, ent_id: str, mesh_rel: str, sha: str, uv=None) -> None:
        # update merges patch into the id-matched entity (cross-run via global id).
        patch = {"asset": {"format": "print-mesh", "path": mesh_rel, "sha256": sha}}
        if uv:
            patch["metadata"] = {"uv": uv}
        self._emit(mesh_run, "update", id=ent_id, patch=patch)

    def append_defects(self, mesh_run: str, ent_id: str, base: Path) -> int:
        """Append one `defect` add per entry of <base>.defects.json (S3 / §4).

        The tool's defect object is passed through verbatim; the daemon only
        stamps ref.entity_id (the tool can't know which entity owns it).
        Returns the number of defects emitted.
        """
        defects_path = base.with_name(base.name + ".defects.json")
        if not defects_path.exists():
            return 0
        try:
            defects = json.loads(defects_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            sys.stderr.write(f"[occ-mesh-daemon] defects unreadable ({defects_path.name}): {exc}\n")
            return 0
        if not isinstance(defects, list):
            return 0
        count = 0
        for i, raw in enumerate(defects):
            if not isinstance(raw, dict):
                continue
            ref = dict(raw.get("ref") or {})
            ref["entity_id"] = ent_id
            defect = {**raw, "ref": ref}
            self._emit(mesh_run, "add", id=f"{ent_id}/defect-{i}",
                       group="defects", kind="defect", defect=defect)
            count += 1
        return count

    def append_note(self, mesh_run: str, ent_id: str, asset_rel: str, detail: str) -> None:
        # N6: capture_failure -> viewer keeps the placeholder; this is diagnostic.
        self._emit(mesh_run, "note", level="capture_failure",
                   message=f"occ-debug-mesh failed for {asset_rel}: {detail}",
                   metadata={"entity_id": ent_id, "asset": asset_rel})

    def fold_uv(self, base: Path):
        """Fold the geom sidecar's UV pcurves into a viewer UV-panel payload
        (mirrors mesh-to-session.py; P0b). Gated by --with-uv since it inlines
        geometry into the event line (plan §4 keeps event lines short)."""
        geom_path = base.with_name(base.name + ".geom.json")
        if not geom_path.exists():
            return None
        try:
            geom = json.loads(geom_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None
        pc_by_face = {}
        for ge in geom.get("edges", []):
            for pc in ge.get("pcurves", []):
                pc_by_face.setdefault(pc["face_id"], []).append({
                    "label": ge["id"],
                    "is_seam": pc.get("is_seam", False),
                    "degenerate": ge.get("degenerate", False),
                    "points": uvpairs(pc["uv"]),
                })
        panels = [{
            "face_id": gf["id"],
            "surface_type": gf.get("surface_type", ""),
            "bounds": gf.get("uv_bounds"),
            "curves": pc_by_face.get(gf["id"], []),
        } for gf in geom.get("faces", [])]
        return {"panels": panels} if panels else None

    # ---- one polling tick ----------------------------------------------
    def tick(self) -> int:
        self.scan_events()
        emitted = 0
        if not self.assets.exists():
            return 0
        for brep in sorted(self.assets.rglob("*.brep")):
            rel = asset_rel_path(self.assets, brep)
            info = self.brep2id.get(rel)
            if info is None:
                # brep landed but its `add` event hasn't appeared yet — leave it
                # for a later tick (plan §3 step 2 / brep->id association note).
                continue
            if self.mesh_one(brep, info):
                emitted += 1
        return emitted

    def run_once(self) -> int:
        return self.tick()

    def run_forever(self) -> int:
        while True:
            self.tick()
            time.sleep(self.interval)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Watch <session>/assets/*.brep, mesh them, append `update` + `defect` events."
    )
    default_session = os.environ.get("OCC_DEBUG_SESSION", ".occ-debug/sessions/dev")
    ap.add_argument("--session", default=default_session,
                    help="Session directory (default: $OCC_DEBUG_SESSION or .occ-debug/sessions/dev)")
    ap.add_argument("--interval", type=float, default=0.2,
                    help="Polling interval in seconds (default: 0.2)")
    ap.add_argument("--once", action="store_true",
                    help="Scan once and exit (test mode); otherwise poll forever")
    ap.add_argument("--with-uv", action="store_true",
                    help="Fold <base>.geom.json UV pcurves into patch.metadata.uv (P0b)")
    ap.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_S,
                    help=f"Per-brep mesher timeout seconds (default: $OCC_DEBUG_MESH_TIMEOUT or {DEFAULT_TIMEOUT_S:g})")
    args = ap.parse_args(argv)

    session = Path(args.session)
    mesher = default_mesher()
    if not Path(mesher).exists():
        sys.stderr.write(
            f"[occ-mesh-daemon] mesher not found: {mesher}\n"
            f"  set $OCC_DEBUG_MESH_BIN or build with scripts/build-occ-debug-mesh.sh\n"
        )
        return 2

    daemon = Daemon(session, mesher, args.interval, with_uv=args.with_uv, timeout=args.timeout)
    print(f"[occ-mesh-daemon] session={session}")
    print(f"[occ-mesh-daemon] mesher={mesher}")
    if args.once:
        n = daemon.run_once()
        print(f"[occ-mesh-daemon] once: emitted {n} update event(s).")
        return 0
    try:
        daemon.run_forever()
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
