"""Shared native job construction; retains existing login, isolation and trace contracts."""
from pathlib import Path
import json
import shutil
import sys
import tempfile
from common import atomic_write_json, load_json, sha256_file
from macos_review_host import sandbox_profile, child_environment
from report_review_host import native_review_command, review_transport_view
import review_isolation


def _probe(*args, **kwargs):
    # Resolve the original host entry point at call time, including isolated tests.
    from report_review_host import _probe as probe
    return probe(*args, **kwargs)


def cleanup_workspaces(workspaces):
    """Remove only this factory's temporary paths; preserve the caller's outcome."""
    for workspace in workspaces:
        try:
            shutil.rmtree(workspace)
        except FileNotFoundError:
            pass
        except OSError as exc:
            # Only the owned temporary path and filesystem failure are reported;
            # no files are read. ASCII JSON also works in legacy Windows consoles.
            diagnostic = {'code': 'NATIVE_REVIEW_WORKSPACE_CLEANUP_INCOMPLETE',
                'path': str(workspace), 'error_type': type(exc).__name__,
                'reason': exc.strerror or str(exc)}
            try:
                sys.stderr.write(json.dumps(diagnostic, ensure_ascii=True) + '\n')
            except (OSError, ValueError):
                pass


def make_job_factory(task_dir, output_dir, binary, isolation, slots, *, runtime_binding=False, resume_existing=False,
                     effort=None):
    tool_free = isolation == review_isolation.TOOL_FREE
    if isolation not in {review_isolation.MACOS, review_isolation.TOOL_FREE}:
        raise ValueError('REVIEW_ISOLATION_BACKEND_INVALID')
    profile_name = 'isolation-policy.json' if tool_free else 'sandbox.sb'
    login_checked = []
    workspaces, workspace_by_slot = [], {}
    def allocate_workspaces():
        if workspaces:
            return
        created = []
        try:
            for _ in slots:
                created.append(Path(tempfile.mkdtemp(prefix='ipr-module-review-')))
            if len(created) == 1 and not tool_free:
                # A one-batch visual run still needs a distinct denied probe target.
                created.append(Path(tempfile.mkdtemp(prefix='ipr-review-control-')))
            workspace_by_slot.update(zip(slots, created))
            workspaces.extend(created)
        except BaseException:
            cleanup_workspaces(created)
            workspace_by_slot.clear()
            workspaces.clear()
            raise
    if not resume_existing:
        allocate_workspaces()
    def make_job(chain, group, packet, images, prompt, *, retained=False, workspace_slot=None):
        directory = output_dir / str(chain) / group
        if runtime_binding and not retained:
            from native_runtime_binding import ensure_fresh_runtime
            ensure_fresh_runtime(output_dir, binary, isolation, packet['task'], resume_existing=resume_existing)
        directory.mkdir(parents=True, exist_ok=retained)
        packet_path = directory / 'packet.json'
        prompt_path = directory / 'prompt.txt'
        if retained:
            if not packet_path.is_file() or load_json(packet_path) != packet or not prompt_path.is_file() or prompt_path.read_text(encoding='utf-8') != prompt:
                raise ValueError('FINAL_REVIEW_RETAINED_PACKET_OR_PROMPT_CHANGED')
            other = directory / ('sandbox.sb' if tool_free else 'isolation-policy.json')
            if other.is_file():
                # A resumed review keeps one isolation method; never mix backends inside a retained session.
                raise ValueError('FINAL_REVIEW_RETAINED_ISOLATION_BACKEND_CHANGED')
            profile = directory / profile_name
            trace_path = directory / 'events.jsonl'
            if not profile.is_file() or not trace_path.is_file() or not (directory / 'stderr.log').is_file():
                raise ValueError('FINAL_REVIEW_RETAINED_HOST_FILES_MISSING')
            manifest = []
            from common import sha256_bytes
            for name, data in images.items():
                path = directory / name
                if not path.is_file() or sha256_file(path) != sha256_bytes(data):
                    raise ValueError('FINAL_REVIEW_RETAINED_IMAGE_CHANGED')
                manifest.append({'name': name, 'path': str(path), 'sha256': sha256_file(path)})
            job = {'chain_id': str(chain), 'module_id': group, 'directory': directory,
                'packet_path': packet_path, 'prompt_path': prompt_path, 'profile': profile, 'prompt': prompt,
                'trace_path': trace_path, 'image_manifest': manifest, 'isolation': isolation}
            from report_review_host import seal_review_job
            seal_review_job(job, packet, images)
            return job
        # Retained sessions require only their existing signed files. The first
        # fresh session allocates every original slot before any peer probe runs.
        allocate_workspaces()
        workspace = workspace_by_slot[workspace_slot or (chain, group)]
        atomic_write_json(packet_path, packet)
        prompt_path.write_bytes(prompt.encode('utf-8'))
        atomic_write_json(workspace / 'frozen-input.json', review_transport_view(packet))
        profile = directory / profile_name
        if tool_free:
            controls = []
            if not login_checked:
                review_isolation.login_status(binary, workspace, child_environment())
                login_checked.append(True)
            command = native_review_command(binary, None, workspace)
            if effort:
                from report_review_host import with_effort
                command = with_effort(command, effort)
        else:
            peers = [path for path in workspaces if path != workspace]
            # Probe fixtures are host-created before any reviewer starts.
            for peer in peers:
                (peer / 'isolation-control.txt').write_text('peer only\n')
            profile.write_text(sandbox_profile(binary, [task_dir, output_dir, *peers,
                Path.home() / 'Documents', Path.home() / 'Downloads', Path.home() / 'Desktop',
                Path.home() / '.codex/sessions', Path.home() / '.codex/worktrees']))
            controls = _probe(binary, workspace, peers[0], task_dir, output_dir, blocked_peers=peers)
            if not login_checked:
                # One ChatGPT login check per host run is enough; it was repeated for every session.
                from macos_review_host import require_chatgpt_auth
                require_chatgpt_auth(binary, profile, workspace)
                login_checked.append(True)
            command = native_review_command(binary, profile, workspace)
            if effort:
                from report_review_host import with_effort
                command = with_effort(command, effort)
        if len(prompt) > 1048576:
            raise ValueError('REPORT_REVIEW_HOST_INPUT_TOO_LARGE_AFTER_LOSSLESS_ENCODING')
        manifest = []
        for name, data in images.items():
            image_path = workspace / name
            image_path.write_bytes(data)
            # Copies also remain in host audit storage for repeatable receipts.
            saved = directory / name
            saved.write_bytes(data)
            manifest.append({'name': name, 'path': str(saved), 'sha256': sha256_file(saved)})
            command[-1:-1] = ['--image', str(image_path)]
        if tool_free:
            # Written last: it lists the workspace files, including the attached images.
            review_isolation.write_policy(profile, binary, workspace, child_environment(), image_names=list(images))
        job = {'chain_id': str(chain), 'module_id': group, 'workspace': workspace,
            'directory': directory, 'packet_path': packet_path, 'prompt_path': prompt_path,
            'profile': profile, 'controls': controls, 'command': command, 'prompt': prompt,
            'trace_path': directory / 'events.jsonl', 'stderr_path': directory / 'stderr.log', 'image_manifest': manifest,
            'isolation': isolation}
        from report_review_host import seal_review_job
        seal_review_job(job, packet, images)
        return job
    return make_job, workspaces
